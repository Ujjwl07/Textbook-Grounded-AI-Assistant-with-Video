"""One entry point for every AI call, with fallback across free-tier providers.

    text = call_llm("quiz_generate", prompt, system="...", json_mode=True)

Each task has an ordered chain of providers (ROUTES). The router tries them in
order, one attempt each, and moves on when a provider is rate-limited, over
quota, slow or broken. All three providers speak the OpenAI chat-completions
API, so one SDK client works for all of them with a different base_url.

Rules (see ``call_llm``):
  - 429 / quota      -> next provider at once; this provider cools down
                        (Retry-After, else 60 s; about an hour for daily quotas)
  - timeout / 5xx    -> one short retry on the same provider, then next
  - 400 / 401 / 403  -> raise LLMRequestError: a code or key problem, not load
  - bad JSON         -> one repair retry on the same provider, then next
  - all failed       -> AllProvidersFailedError listing each provider's reason

``call_llm`` is synchronous (and thread-safe) on purpose: async code calls it
through ``acall_llm``, which runs it on a worker thread so a slow provider never
blocks the event loop.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import random
import re
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple

from dotenv import load_dotenv

# backend/.env, wherever the process was started from. Keys are never hardcoded.
load_dotenv(Path(__file__).resolve().parents[2] / ".env")

logger = logging.getLogger("textbook_assistant.llm_router")

# --------------------------------------------------------------------------
# Configuration: every base URL and model ID lives here.
#
# Model IDs checked on 2026-11-25:
#   - Gemini: the key's own OpenAI-compatible /models list.
#   - OpenRouter: the public /api/v1/models list, ":free" variants only, then a
#     live JSON test of each (the Gemma 4 free models were rate-limited upstream).
#   - Groq: console.groq.com/docs/models and /docs/deprecations. Groq shut
#     llama-3.3-70b-versatile and llama-3.1-8b-instant for free/dev tiers on
#     2026-08-16 and names openai/gpt-oss-120b and openai/gpt-oss-20b as their
#     replacements, so those fill the "70B" and "8B instant" roles.
# --------------------------------------------------------------------------
PROVIDERS: Dict[str, dict] = {
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "api_key_env": "GEMINI_API_KEY",
        "models": {
            "large": os.getenv("LLM_MODEL") or "gemini-3.6-flash",
            "small": os.getenv("LLM_MODEL") or "gemini-3.6-flash",
        },
        "extra_body": {},
        "merge_system": False,
    },
    "groq": {
        "base_url": "https://api.groq.com/openai/v1",
        "api_key_env": "GROQ_API_KEY",
        "models": {
            "large": "openai/gpt-oss-120b",  # the "70B" role
            "small": "openai/gpt-oss-20b",   # the "8B instant" role
        },
        # gpt-oss reasons before answering and those tokens count toward
        # max_tokens; "low" keeps short JSON answers from being cut off.
        "extra_body": {"reasoning_effort": "low"},
        "merge_system": False,
    },
    "openrouter": {
        "base_url": "https://openrouter.ai/api/v1",
        "api_key_env": "OPENROUTER_API_KEY",
        "models": {
            "large": "nvidia/nemotron-3.5-super-vl:free",
            "small": "inclusionai/ling-3.2-flash:free",
        },
        # OpenRouter tries these, in order, when the main free model is
        # rate-limited upstream (free models often are). Sent as "models".
        "alt_models": {
            "large": ["google/gemma-4-31b-it:free", "baidu/ernie-5.5-flash-preview:free"],
            "small": ["baidu/ernie-5.5-flash-preview:free", "particle-ai/particle-1:free"],
        },
        "extra_body": {},
        # Some free models have no system role; fold the system text into the user turn.
        "merge_system": True,
        "headers": {"X-Title": "TextbookAI"},
    },
}

# Ordered fallback chain per task: (provider, model size).
ROUTES: Dict[str, List[Tuple[str, str]]] = {
    "video_script": [("gemini", "large"), ("groq", "large"), ("openrouter", "large")],
    "quiz_generate": [("groq", "large"), ("gemini", "large"), ("openrouter", "large")],
    "mistake_analysis": [("groq", "small"), ("openrouter", "small"), ("gemini", "small")],
    "doubt_answer": [("gemini", "large"), ("openrouter", "large"), ("groq", "large")],
}

# Seconds per request. The video script is long and Gemini thinks first, so it
# gets more room; everything else uses the ~30 s default.
TIMEOUTS: Dict[str, float] = {"video_script": 90.0}
DEFAULT_TIMEOUT = 30.0
MAX_TOKENS_CAP = 8192
RETRY_BACKOFF_SECONDS = 1.5          # the one retry after a timeout / 5xx
DEFAULT_COOLDOWN_SECONDS = 60.0      # 429 without Retry-After
DAILY_QUOTA_COOLDOWN_SECONDS = 3600.0
CACHE_TTL_SECONDS = 600.0
CACHE_MAX_ENTRIES = 256

_DAILY_HINT = re.compile(r"per[ -]?day|daily|\bRPD\b|\bTPD\b|requests per day|tokens per day", re.I)


# --------------------------------------------------------------------------
# Errors
# --------------------------------------------------------------------------
class LLMRequestError(RuntimeError):
    """400 / 401 / 403 (or an unknown model): a key or code problem.

    Not retried and not passed to the next provider, because every provider
    would be sent the same broken request, or the key needs fixing.
    """

    def __init__(self, provider: str, status: Optional[int], message: str) -> None:
        super().__init__(f"{provider} rejected the request (HTTP {status}): {message}")
        self.provider = provider
        self.status = status


class AllProvidersFailedError(RuntimeError):
    """Every provider in the task's route failed. ``failures`` says why, per provider."""

    def __init__(self, task: str, failures: List[Tuple[str, str]]) -> None:
        detail = "; ".join(f"{name}: {why}" for name, why in failures) or "no providers configured"
        super().__init__(f"All providers failed for '{task}': {detail}")
        self.task = task
        self.failures = failures


class _Skip(Exception):
    """Internal: give up on this provider and try the next one."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


# --------------------------------------------------------------------------
# Shared state (thread-safe: video jobs and background tasks call concurrently)
# --------------------------------------------------------------------------
@dataclass
class _State:
    lock: threading.Lock = field(default_factory=threading.Lock)
    cooldown_until: Dict[str, float] = field(default_factory=dict)
    cache: Dict[str, Tuple[float, str, str]] = field(default_factory=dict)  # key -> (expires, text, provider)
    clients: Dict[str, object] = field(default_factory=dict)


_state = _State()
_clock: Callable[[], float] = time.monotonic
_sleep: Callable[[float], None] = time.sleep


def reset_state() -> None:
    """Forget cooldowns, cache and clients (used by tests and after key changes)."""
    with _state.lock:
        _state.cooldown_until.clear()
        _state.cache.clear()
        _state.clients.clear()


def _api_key(provider: str) -> str:
    return (os.getenv(PROVIDERS[provider]["api_key_env"]) or "").strip()


def is_configured(provider: str) -> bool:
    return len(_api_key(provider)) > 10


def is_task_configured(task: str) -> bool:
    """True if at least one provider on the task's route has a key."""
    return any(is_configured(name) for name, _ in ROUTES.get(task, []))


def cooldown_remaining(provider: str) -> float:
    with _state.lock:
        return max(0.0, _state.cooldown_until.get(provider, 0.0) - _clock())


def _start_cooldown(provider: str, seconds: float, why: str) -> None:
    with _state.lock:
        until = _clock() + seconds
        # Never shorten an existing (e.g. daily) cooldown.
        _state.cooldown_until[provider] = max(until, _state.cooldown_until.get(provider, 0.0))
    logger.warning("LLM router: %s cooling down for %.0fs (%s)", provider, seconds, why)


def _client(provider: str):
    """One OpenAI SDK client per provider, created lazily."""
    with _state.lock:
        client = _state.clients.get(provider)
        if client is None:
            from openai import OpenAI  # imported here so tests can stub _create_completion

            cfg = PROVIDERS[provider]
            client = OpenAI(
                api_key=_api_key(provider),
                base_url=cfg["base_url"],
                max_retries=0,  # the router decides when to retry
                default_headers=cfg.get("headers"),
            )
            _state.clients[provider] = client
        return client


# --------------------------------------------------------------------------
# One request to one provider
# --------------------------------------------------------------------------
def _create_completion(provider: str, model: str, messages: list, *, json_mode: bool,
                       max_tokens: int, timeout: float) -> str:
    """Send one chat completion. Raises the openai SDK's exceptions on HTTP errors."""
    cfg = PROVIDERS[provider]
    kwargs = dict(model=model, messages=messages, max_tokens=max_tokens, timeout=timeout, temperature=0.2)
    if json_mode:
        kwargs["response_format"] = {"type": "json_object"}
    extra = dict(cfg.get("extra_body") or {})
    for size, alternates in (cfg.get("alt_models") or {}).items():
        if cfg["models"].get(size) == model and alternates:
            extra["models"] = [model, *alternates]
    if extra:
        kwargs["extra_body"] = extra
    response = _client(provider).chat.completions.create(**kwargs)
    choice = response.choices[0] if response.choices else None
    text = (choice.message.content or "").strip() if choice and choice.message else ""
    if choice is not None and choice.finish_reason == "length":
        raise _Skip(f"answer cut off at max_tokens={max_tokens}")
    if not text:
        raise _Skip("empty answer")
    return text


def _messages(provider: str, prompt: str, system: Optional[str]) -> list:
    if not system:
        return [{"role": "user", "content": prompt}]
    if PROVIDERS[provider].get("merge_system"):
        return [{"role": "user", "content": f"{system}\n\n{prompt}"}]
    return [{"role": "system", "content": system}, {"role": "user", "content": prompt}]


def _status_of(exc: Exception) -> Optional[int]:
    return getattr(exc, "status_code", None) or getattr(getattr(exc, "response", None), "status_code", None)


def _retry_after(exc: Exception) -> Optional[float]:
    headers = getattr(getattr(exc, "response", None), "headers", None) or {}
    value = headers.get("retry-after") or headers.get("Retry-After")
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _short(text: str, limit: int = 160) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[:limit] + "..."


def _is_transient(exc: Exception) -> bool:
    """Timeouts, dropped connections and 5xx: worth one more try."""
    import openai

    if isinstance(exc, (openai.APITimeoutError, openai.APIConnectionError, TimeoutError)):
        return True
    status = _status_of(exc)
    return status is not None and status >= 500


def parse_json(text: str):
    """json.loads after stripping ``` fences and anything around the JSON."""
    cleaned = text.strip()
    if "```" in cleaned:
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.I)
        cleaned = re.sub(r"\s*```$", "", cleaned).strip()
    match = re.search(r"(\[.*\]|\{.*\})", cleaned, re.S)
    if match:
        cleaned = match.group(1)
    return json.loads(cleaned)


def _try_provider(task: str, provider: str, model: str, prompt: str, system: Optional[str],
                  json_mode: bool, max_tokens: int) -> str:
    """At most one attempt, plus one retry for timeout/5xx or one repair for bad JSON."""
    import openai

    timeout = TIMEOUTS.get(task, DEFAULT_TIMEOUT)
    messages = _messages(provider, prompt, system)
    transient_retry_used = False
    repair_used = False

    while True:
        try:
            text = _create_completion(provider, model, messages, json_mode=json_mode,
                                      max_tokens=max_tokens, timeout=timeout)
        except _Skip:
            raise
        except openai.RateLimitError as exc:
            message = str(exc)
            if _DAILY_HINT.search(message):
                _start_cooldown(provider, DAILY_QUOTA_COOLDOWN_SECONDS, "daily quota reached")
            else:
                _start_cooldown(provider, _retry_after(exc) or DEFAULT_COOLDOWN_SECONDS, "rate limited (429)")
            raise _Skip(f"rate limited (429): {_short(message)}")
        except Exception as exc:  # noqa: BLE001 - classified below
            status = _status_of(exc)
            if status in (400, 401, 403):
                raise LLMRequestError(provider, status, _short(str(exc))) from exc
            if status == 404:
                # Usually a model ID that was withdrawn (free models come and go).
                # Fix the ID in PROVIDERS; meanwhile the next provider can answer.
                logger.error("LLM router: %s says model %s does not exist; update PROVIDERS", provider, model)
                raise _Skip(f"model not found (404): {model}")
            if status == 402:
                # OpenRouter: out of credits / free allowance. Treat like a daily quota.
                _start_cooldown(provider, DAILY_QUOTA_COOLDOWN_SECONDS, "payment required (402)")
                raise _Skip("out of credits (402)")
            if status == 413:
                raise _Skip("prompt too large for this provider (413)")
            if _is_transient(exc) and not transient_retry_used:
                transient_retry_used = True
                delay = RETRY_BACKOFF_SECONDS + random.uniform(0, 0.5)
                logger.warning("LLM router: %s %s failed (%s), retrying once in %.1fs",
                               provider, task, _short(str(exc) or type(exc).__name__, 80), delay)
                _sleep(delay)
                continue
            raise _Skip(f"{'timeout/server error' if _is_transient(exc) else 'error'}: "
                        f"{_short(str(exc) or type(exc).__name__)}")

        if not json_mode:
            return text
        try:
            parse_json(text)
            return text
        except ValueError:
            if repair_used:
                raise _Skip("returned invalid JSON twice")
            repair_used = True
            logger.warning("LLM router: %s returned invalid JSON for %s, asking it to repair", provider, task)
            messages = messages + [
                {"role": "assistant", "content": text[:6000]},
                {"role": "user", "content": "That was not valid JSON. Reply again with ONLY the corrected, "
                                            "complete JSON and nothing else."},
            ]


# --------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------
def call_llm_with_provider(task: str, prompt: str, *, system: Optional[str] = None,
                           json_mode: bool = False, max_tokens: int = 1024,
                           use_cache: bool = True) -> Tuple[str, str]:
    """Like ``call_llm`` but also returns which provider answered."""
    if task not in ROUTES:
        raise ValueError(f"Unknown LLM task '{task}'. Known tasks: {', '.join(ROUTES)}")
    max_tokens = max(1, min(int(max_tokens), MAX_TOKENS_CAP))

    key = hashlib.sha256(json.dumps([task, system, prompt, json_mode, max_tokens]).encode()).hexdigest()
    if use_cache:
        with _state.lock:
            hit = _state.cache.get(key)
            if hit and hit[0] > _clock():
                logger.info("LLM router: %s served from cache (originally %s)", task, hit[2])
                return hit[1], hit[2]

    failures: List[Tuple[str, str]] = []
    started = time.perf_counter()
    for provider, size in ROUTES[task]:
        if not is_configured(provider):
            failures.append((provider, "no API key"))
            continue
        wait = cooldown_remaining(provider)
        if wait > 0:
            failures.append((provider, f"cooling down ({wait:.0f}s left)"))
            continue
        model = PROVIDERS[provider]["models"][size]
        try:
            text = _try_provider(task, provider, model, prompt, system, json_mode, max_tokens)
        except _Skip as skip:
            logger.warning("LLM router: %s via %s (%s) failed: %s", task, provider, model, skip.reason)
            failures.append((provider, skip.reason))
            continue
        except LLMRequestError:
            logger.error("LLM router: %s via %s (%s) was rejected; not falling back", task, provider, model)
            raise

        skipped = f" after {', '.join(name for name, _ in failures)} failed" if failures else ""
        logger.info("LLM router: %s answered by %s (%s) in %.1fs%s",
                    task, provider, model, time.perf_counter() - started, skipped)
        if use_cache:
            with _state.lock:
                if len(_state.cache) >= CACHE_MAX_ENTRIES:
                    now = _clock()
                    for stale in [k for k, v in _state.cache.items() if v[0] <= now] or list(_state.cache)[:32]:
                        _state.cache.pop(stale, None)
                _state.cache[key] = (_clock() + CACHE_TTL_SECONDS, text, provider)
        return text, provider

    logger.error("LLM router: every provider failed for %s: %s", task, failures)
    raise AllProvidersFailedError(task, failures)


def call_llm(task: str, prompt: str, *, system: Optional[str] = None,
             json_mode: bool = False, max_tokens: int = 1024) -> str:
    """Answer ``prompt`` with the first provider on ``task``'s route that can.

    Raises LLMRequestError (400/401/403) or AllProvidersFailedError.
    """
    text, _ = call_llm_with_provider(task, prompt, system=system, json_mode=json_mode, max_tokens=max_tokens)
    return text


async def acall_llm(task: str, prompt: str, *, system: Optional[str] = None, json_mode: bool = False,
                    max_tokens: int = 1024, use_cache: bool = True) -> Tuple[str, str]:
    """``call_llm_with_provider`` on a worker thread, for async code."""
    return await asyncio.to_thread(
        call_llm_with_provider, task, prompt,
        system=system, json_mode=json_mode, max_tokens=max_tokens, use_cache=use_cache,
    )
