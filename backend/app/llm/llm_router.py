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
  - all busy         -> the call queues and retries until MAX_WAIT for the task
                        (bursts wait instead of failing); daily quotas are not waited out
  - all failed       -> AllProvidersFailedError listing each provider's reason

``call_llm`` is synchronous (and thread-safe) on purpose: async code calls it
through ``acall_llm``, which runs it on a worker thread so a slow provider never
blocks the event loop.
"""

from __future__ import annotations

import asyncio
import functools
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
            # Fast, non-reasoning free models. Nemotron answered but took 40-100 s
            # per quiz under load and often ran out of tokens, so it is a last resort.
            "large": "inclusionai/ling-3.2-flash:free",
            "small": "baidu/ernie-5.5-flash-preview:free",
        },
        # OpenRouter tries these, in order, when the main free model is
        # rate-limited upstream (free models often are). Sent as "models";
        # OpenRouter accepts at most 3 there (the main model + 2 backups).
        "alt_models": {
            "large": ["baidu/ernie-5.5-flash-preview:free", "google/gemma-4-31b-it:free"],
            "small": ["inclusionai/ling-3.2-flash:free", "particle-ai/particle-1:free"],
        },
        # Reasoning models (e.g. Nemotron) otherwise spend the whole max_tokens
        # thinking and return a cut-off answer.
        "extra_body": {"reasoning": {"effort": "low", "exclude": True}},
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
    "flashcards": [("groq", "small"), ("gemini", "small"), ("openrouter", "small")],
}

# Request queue. Each provider admits a few requests at a time and, where the
# provider publishes one, keeps under its tokens-per-minute budget. When every
# provider on a route is busy or briefly rate-limited, the call WAITS (up to
# MAX_WAIT for its task) instead of failing; a daily-quota cooldown is never
# waited out. Groq's free tier allows 8,000 tokens/minute per model (checked
# from its x-ratelimit headers on 2026-11-25); one quiz uses ~2,700 and one
# video script ~3,700, so without this a burst of quizzes failed outright.
LIMITS: Dict[str, dict] = {
    "groq": {"concurrency": 4, "tpm": 8000},
    "gemini": {"concurrency": 2, "tpm": None},
    "openrouter": {"concurrency": 2, "tpm": None},
}
# Longest a call will queue before giving up (background work can wait longer).
MAX_WAIT: Dict[str, float] = {
    "video_script": 180.0,     # runs inside a background video job
    "quiz_generate": 180.0,    # a student watches a spinner; Groq's free tier fits ~3 quizzes/min
    "mistake_analysis": 120.0, # background task after an answer
    "doubt_answer": 30.0,
    "flashcards": 60.0,
}
# Rough answer size per task, for the tokens-per-minute estimate.
EXPECTED_OUTPUT_TOKENS: Dict[str, int] = {
    "video_script": 2000, "quiz_generate": 1300, "mistake_analysis": 250, "doubt_answer": 700,
    "flashcards": 900,
}
QUEUE_POLL_SECONDS = 0.5
LLM_THREADS = 32  # worker threads for acall_llm, separate from asyncio's default pool

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

_JSON_FAILED = re.compile(r"json_validate_failed|Failed to generate JSON", re.I)
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


class _Limiter:
    """Admission control for one provider+model: concurrency and a 60 s token window."""

    def __init__(self, concurrency: int, tpm: Optional[int]) -> None:
        self.concurrency = concurrency
        self.tpm = tpm
        self.active = 0
        self.window: List[List[float]] = []  # [timestamp, tokens]

    def _used(self, now: float) -> int:
        self.window = [entry for entry in self.window if entry[0] > now - 60.0]
        return int(sum(tokens for _, tokens in self.window))

    def try_acquire(self, tokens: int, now: float) -> Tuple[Optional[list], float]:
        """``(ticket, 0)`` when admitted, else ``(None, seconds until it might be)``."""
        used = self._used(now)
        if self.active >= self.concurrency:
            return None, QUEUE_POLL_SECONDS
        if self.tpm and self.window and used + tokens > self.tpm:
            # Wait until enough of the window has aged out to fit this request.
            need, freed = used + tokens - self.tpm, 0
            for stamp, spent in self.window:
                freed += spent
                if freed >= need:
                    return None, max(QUEUE_POLL_SECONDS, stamp + 60.0 - now)
            return None, 60.0
        self.active += 1
        ticket = [now, float(tokens)]
        self.window.append(ticket)
        return ticket, 0.0

    def release(self, ticket: list, actual_tokens: Optional[int]) -> None:
        self.active = max(0, self.active - 1)
        if actual_tokens:  # replace the estimate with what the provider reported
            ticket[1] = float(actual_tokens)


_state = _State()
_limiters: Dict[Tuple[str, str], _Limiter] = {}
_usage = threading.local()  # total_tokens of the last completion on this thread


def _limiter(provider: str, model: str) -> _Limiter:
    key = (provider, model)
    if key not in _limiters:
        cfg = LIMITS.get(provider, {})
        _limiters[key] = _Limiter(cfg.get("concurrency", 2), cfg.get("tpm"))
    return _limiters[key]


def _estimate_tokens(task: str, prompt: str, system: Optional[str], max_tokens: int) -> int:
    return (len(prompt) + len(system or "")) // 4 + min(max_tokens, EXPECTED_OUTPUT_TOKENS.get(task, 800))
_clock: Callable[[], float] = time.monotonic
_sleep: Callable[[float], None] = time.sleep


def reset_state() -> None:
    """Forget cooldowns, cache and clients (used by tests and after key changes)."""
    with _state.lock:
        _state.cooldown_until.clear()
        _state.cache.clear()
        _state.clients.clear()
        _limiters.clear()


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
            extra["models"] = [model, *alternates][:3]  # OpenRouter's maximum
    if extra:
        kwargs["extra_body"] = extra
    response = _client(provider).chat.completions.create(**kwargs)
    usage = getattr(response, "usage", None)
    _usage.total = getattr(usage, "total_tokens", None) if usage else None
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
            if status == 400 and json_mode and _JSON_FAILED.search(str(exc)):
                # Groq checks JSON mode server-side and answers 400 when the model's
                # output was not valid JSON. That is bad output, not a bad request.
                if repair_used:
                    raise _Skip("could not produce valid JSON (400 json_validate_failed)")
                repair_used = True
                logger.warning("LLM router: %s could not produce valid JSON for %s, retrying once", provider, task)
                continue
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

    started = time.perf_counter()
    deadline = _clock() + MAX_WAIT.get(task, 30.0)
    estimate = _estimate_tokens(task, prompt, system, max_tokens)
    dead: Dict[str, str] = {}  # providers that failed for real: not retried this call
    waited = 0.0

    while True:
        failures: List[Tuple[str, str]] = []
        retry_in: List[float] = []  # seconds until a busy / briefly limited provider frees up

        for provider, size in ROUTES[task]:
            if provider in dead:
                failures.append((provider, dead[provider]))
                continue
            if not is_configured(provider):
                failures.append((provider, "no API key"))
                continue
            cooling = cooldown_remaining(provider)
            if cooling > 0:
                failures.append((provider, f"cooling down ({cooling:.0f}s left)"))
                retry_in.append(cooling)
                continue
            model = PROVIDERS[provider]["models"][size]
            limiter = _limiter(provider, model)
            with _state.lock:
                ticket, busy_for = limiter.try_acquire(estimate, _clock())
            if ticket is None:
                failures.append((provider, "busy (request queue full)"))
                retry_in.append(busy_for)
                continue

            _usage.total = None
            try:
                text = _try_provider(task, provider, model, prompt, system, json_mode, max_tokens)
            except _Skip as skip:
                logger.warning("LLM router: %s via %s (%s) failed: %s", task, provider, model, skip.reason)
                failures.append((provider, skip.reason))
                if cooldown_remaining(provider) > 0:
                    retry_in.append(cooldown_remaining(provider))  # rate-limited: may free up soon
                else:
                    dead[provider] = skip.reason  # a real failure: don't try it again
                continue
            except LLMRequestError:
                logger.error("LLM router: %s via %s (%s) was rejected; not falling back", task, provider, model)
                raise
            finally:
                with _state.lock:
                    limiter.release(ticket, getattr(_usage, "total", None))

            skipped = f" after {', '.join(name for name, _ in failures)} failed" if failures else ""
            queued = f", queued {waited:.1f}s" if waited else ""
            logger.info("LLM router: %s answered by %s (%s) in %.1fs%s%s",
                        task, provider, model, time.perf_counter() - started, queued, skipped)
            if use_cache:
                with _state.lock:
                    if len(_state.cache) >= CACHE_MAX_ENTRIES:
                        now = _clock()
                        for stale in [k for k, v in _state.cache.items() if v[0] <= now] or list(_state.cache)[:32]:
                            _state.cache.pop(stale, None)
                    _state.cache[key] = (_clock() + CACHE_TTL_SECONDS, text, provider)
            return text, provider

        # Nobody could answer right now. Wait for the soonest provider to free
        # up, unless that is past this task's MAX_WAIT (e.g. a daily quota).
        left = deadline - _clock()
        soonest = min(retry_in) if retry_in else None
        if soonest is None or soonest > left:
            logger.error("LLM router: every provider failed for %s: %s", task, failures)
            if waited:
                failures.append(("queue", f"gave up after waiting {waited:.0f}s"))
            raise AllProvidersFailedError(task, failures)
        pause = min(left, soonest + random.uniform(0.05, 0.4))
        if not waited:
            logger.info("LLM router: %s queued; all providers busy, waiting %.1fs", task, pause)
        _sleep(pause)
        waited += pause


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
    # A dedicated pool: calls may sit queued for a while, and they must not
    # use up asyncio's default threads, which the textbook search also needs.
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(_executor(), functools.partial(
        call_llm_with_provider, task, prompt,
        system=system, json_mode=json_mode, max_tokens=max_tokens, use_cache=use_cache,
    ))


_pool = None
_pool_lock = threading.Lock()


def _executor():
    global _pool
    with _pool_lock:
        if _pool is None:
            from concurrent.futures import ThreadPoolExecutor

            _pool = ThreadPoolExecutor(max_workers=LLM_THREADS, thread_name_prefix="llm")
        return _pool
