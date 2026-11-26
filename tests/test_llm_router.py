"""LLM router: fallback order, cooldowns, no-fallback errors, JSON repair, caching.

Offline: the HTTP call (_create_completion) is replaced with a scripted fake, so
no provider is contacted and no API key is needed.

Run from the repo root:  python -m pytest tests/test_llm_router.py
"""

import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1] / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

import httpx  # noqa: E402
import openai  # noqa: E402
import pytest  # noqa: E402

from app.llm import llm_router as router  # noqa: E402
from app.llm.llm_router import AllProvidersFailedError, LLMRequestError, call_llm, call_llm_with_provider  # noqa: E402


def http_error(cls, status, message="error", headers=None):
    """An openai SDK exception like the one a real HTTP error would raise."""
    request = httpx.Request("POST", "https://example.test/v1/chat/completions")
    response = httpx.Response(status, headers=headers or {}, request=request)
    return cls(message, response=response, body=None)


class FakeProviders:
    """Scripted answers per provider. Each entry is a string to return or an exception to raise."""

    def __init__(self, script):
        self.script = {name: list(steps) for name, steps in script.items()}
        self.calls = []  # (provider, model, messages)

    def __call__(self, provider, model, messages, *, json_mode, max_tokens, timeout):
        self.calls.append((provider, model, messages))
        steps = self.script.get(provider)
        if not steps:
            raise AssertionError(f"{provider} was called but has nothing scripted")
        step = steps.pop(0)
        if isinstance(step, BaseException):
            raise step
        return step

    def called(self):
        return [provider for provider, _, _ in self.calls]


@pytest.fixture
def env(monkeypatch):
    for name in ("GEMINI_API_KEY", "GROQ_API_KEY", "OPENROUTER_API_KEY"):
        monkeypatch.setenv(name, f"test-key-for-{name.lower()}")
    router.reset_state()
    clock = {"now": 1000.0}
    monkeypatch.setattr(router, "_clock", lambda: clock["now"])
    clock["slept"] = 0.0

    def fake_sleep(seconds):  # waiting moves the fake clock forward
        clock["now"] += seconds
        clock["slept"] += seconds

    monkeypatch.setattr(router, "_sleep", fake_sleep)
    yield monkeypatch, clock
    router.reset_state()


def use(monkeypatch, script):
    fake = FakeProviders(script)
    monkeypatch.setattr(router, "_create_completion", fake)
    return fake


# --- route order ------------------------------------------------------------

def test_each_task_starts_with_its_first_provider(env):
    monkeypatch, _ = env
    fake = use(monkeypatch, {"gemini": ["script"], "groq": ["quiz", "label"]})
    assert call_llm("video_script", "p1") == "script"
    assert call_llm("quiz_generate", "p2") == "quiz"
    assert call_llm("mistake_analysis", "p3") == "label"
    assert fake.called() == ["gemini", "groq", "groq"]
    # The small model is used for the tiny mistake call.
    assert fake.calls[2][1] == router.PROVIDERS["groq"]["models"]["small"]


def test_unknown_task_is_a_programming_error(env):
    with pytest.raises(ValueError):
        call_llm("not_a_task", "p")


# --- 429 -----------------------------------------------------------------------

def test_429_switches_to_the_next_provider_immediately(env):
    monkeypatch, _ = env
    fake = use(monkeypatch, {
        "groq": [http_error(openai.RateLimitError, 429, "Rate limit reached", {"retry-after": "30"})],
        "gemini": ["from gemini"],
    })
    text, provider = call_llm_with_provider("quiz_generate", "p")
    assert (text, provider) == ("from gemini", "gemini")
    assert fake.called() == ["groq", "gemini"]  # no second try on groq
    assert router.cooldown_remaining("groq") == pytest.approx(30)  # Retry-After honoured


def test_429_without_retry_after_uses_the_default_cooldown(env):
    monkeypatch, _ = env
    use(monkeypatch, {"groq": [http_error(openai.RateLimitError, 429, "slow down")], "gemini": ["ok"]})
    call_llm("quiz_generate", "p")
    assert router.cooldown_remaining("groq") == pytest.approx(router.DEFAULT_COOLDOWN_SECONDS)


def test_daily_quota_gets_a_long_cooldown(env):
    monkeypatch, _ = env
    use(monkeypatch, {
        "groq": [http_error(openai.RateLimitError, 429, "Rate limit reached on tokens per day (TPD)")],
        "gemini": ["ok"],
    })
    call_llm("quiz_generate", "p")
    assert router.cooldown_remaining("groq") == pytest.approx(router.DAILY_QUOTA_COOLDOWN_SECONDS)


def test_a_provider_on_cooldown_is_skipped_until_it_expires(env):
    monkeypatch, clock = env
    fake = use(monkeypatch, {
        "groq": [http_error(openai.RateLimitError, 429, "busy", {"retry-after": "60"}), "groq is back"],
        "gemini": ["gemini 1", "gemini 2"],
    })
    assert call_llm("quiz_generate", "first") == "gemini 1"
    assert call_llm("quiz_generate", "second") == "gemini 2"  # groq not even tried
    assert fake.called() == ["groq", "gemini", "gemini"]

    clock["now"] += 61  # cooldown over
    assert call_llm("quiz_generate", "third") == "groq is back"
    assert fake.called()[-1] == "groq"


# --- errors that must not fall back -------------------------------------------

@pytest.mark.parametrize("cls,status", [
    (openai.AuthenticationError, 401),
    (openai.PermissionDeniedError, 403),
    (openai.BadRequestError, 400),
])
def test_400_401_403_raise_without_falling_back(env, cls, status):
    monkeypatch, _ = env
    fake = use(monkeypatch, {"groq": [http_error(cls, status, "bad key")], "gemini": ["should not be used"]})
    with pytest.raises(LLMRequestError) as info:
        call_llm("quiz_generate", "p")
    assert info.value.provider == "groq" and info.value.status == status
    assert fake.called() == ["groq"]


# --- timeouts and 5xx ---------------------------------------------------------

def test_timeout_gets_one_retry_on_the_same_provider(env):
    monkeypatch, _ = env
    request = httpx.Request("POST", "https://example.test")
    fake = use(monkeypatch, {"gemini": [openai.APITimeoutError(request=request), "second try worked"]})
    assert call_llm("video_script", "p") == "second try worked"
    assert fake.called() == ["gemini", "gemini"]


def test_repeated_5xx_moves_on_after_one_retry(env):
    monkeypatch, _ = env
    fake = use(monkeypatch, {
        "gemini": [http_error(openai.InternalServerError, 503, "overloaded"),
                   http_error(openai.InternalServerError, 503, "overloaded")],
        "groq": ["from groq"],
    })
    assert call_llm("video_script", "p") == "from groq"
    assert fake.called() == ["gemini", "gemini", "groq"]
    assert router.cooldown_remaining("gemini") == 0  # 5xx is not a quota problem


# --- JSON mode -----------------------------------------------------------------

def test_invalid_json_gets_one_repair_retry_on_the_same_provider(env):
    monkeypatch, _ = env
    fake = use(monkeypatch, {"groq": ['{"questions": [1, 2', '{"questions": [1, 2]}']})
    text = call_llm("quiz_generate", "p", json_mode=True)
    assert text == '{"questions": [1, 2]}'
    assert fake.called() == ["groq", "groq"]
    repair_messages = fake.calls[1][2]
    assert repair_messages[-1]["role"] == "user" and "valid JSON" in repair_messages[-1]["content"]


def test_json_still_invalid_after_repair_moves_to_the_next_provider(env):
    monkeypatch, _ = env
    fake = use(monkeypatch, {"groq": ["not json", "still not json"], "gemini": ['{"ok": true}']})
    assert call_llm("quiz_generate", "p", json_mode=True) == '{"ok": true}'
    assert fake.called() == ["groq", "groq", "gemini"]


def test_fenced_json_counts_as_valid(env):
    monkeypatch, _ = env
    use(monkeypatch, {"groq": ['```json\n{"type": "silly"}\n```']})
    assert "silly" in call_llm("mistake_analysis", "p", json_mode=True)


# --- everything fails -----------------------------------------------------------

def test_all_providers_failing_raises_with_each_reason(env):
    monkeypatch, _ = env
    use(monkeypatch, {
        # A daily quota is never waited out, so nothing here is queued for.
        "groq": [http_error(openai.RateLimitError, 429, "Rate limit reached on requests per day (RPD)")],
        "gemini": [http_error(openai.InternalServerError, 500, "boom"), http_error(openai.InternalServerError, 500, "boom")],
        "openrouter": [http_error(openai.APIStatusError, 402, "no credits")],
    })
    with pytest.raises(AllProvidersFailedError) as info:
        call_llm("quiz_generate", "p")
    names = [name for name, _ in info.value.failures]
    assert names == ["groq", "gemini", "openrouter"]
    assert "rate limited" in info.value.failures[0][1]
    assert "402" in info.value.failures[2][1]


def test_providers_without_a_key_are_skipped(env):
    monkeypatch, _ = env
    monkeypatch.delenv("GROQ_API_KEY")
    fake = use(monkeypatch, {"gemini": ["ok"]})
    assert call_llm("quiz_generate", "p") == "ok"
    assert fake.called() == ["gemini"]


def test_no_keys_at_all_raises_all_failed(env):
    monkeypatch, _ = env
    for name in ("GEMINI_API_KEY", "GROQ_API_KEY", "OPENROUTER_API_KEY"):
        monkeypatch.delenv(name)
    use(monkeypatch, {})
    with pytest.raises(AllProvidersFailedError):
        call_llm("doubt_answer", "p")


# --- cache and limits ------------------------------------------------------------

def test_repeated_prompt_is_served_from_cache_until_the_ttl(env):
    monkeypatch, clock = env
    fake = use(monkeypatch, {"groq": ["answer 1", "answer 2"]})
    assert call_llm("quiz_generate", "same prompt") == "answer 1"
    assert call_llm("quiz_generate", "same prompt") == "answer 1"
    assert len(fake.calls) == 1
    clock["now"] += router.CACHE_TTL_SECONDS + 1
    assert call_llm("quiz_generate", "same prompt") == "answer 2"


def test_max_tokens_is_capped(env):
    monkeypatch, _ = env
    seen = {}

    def fake(provider, model, messages, *, json_mode, max_tokens, timeout):
        seen["max_tokens"] = max_tokens
        return "ok"

    monkeypatch.setattr(router, "_create_completion", fake)
    call_llm("video_script", "p", max_tokens=10**6)
    assert seen["max_tokens"] == router.MAX_TOKENS_CAP


def test_groq_json_validate_failed_400_is_retried_then_falls_back(env):
    monkeypatch, _ = env
    bad_json = http_error(openai.BadRequestError, 400,
                          "Failed to generate JSON. Please adjust your prompt. code: json_validate_failed")
    fake = use(monkeypatch, {"groq": [bad_json, bad_json], "gemini": ['{"ok": true}']})
    assert call_llm("quiz_generate", "p", json_mode=True) == '{"ok": true}'
    assert fake.called() == ["groq", "groq", "gemini"]


def test_plain_400_still_does_not_fall_back(env):
    monkeypatch, _ = env
    fake = use(monkeypatch, {"groq": [http_error(openai.BadRequestError, 400, "invalid model parameter")],
                             "gemini": ["unused"]})
    with pytest.raises(LLMRequestError):
        call_llm("quiz_generate", "p", json_mode=True)
    assert fake.called() == ["groq"]



# --- request queue: bursts wait instead of failing ------------------------------

def test_short_rate_limit_everywhere_waits_then_succeeds(env):
    monkeypatch, clock = env
    fake = use(monkeypatch, {
        "groq": [http_error(openai.RateLimitError, 429, "busy", {"retry-after": "5"}), "after waiting"],
        "openrouter": [http_error(openai.RateLimitError, 429, "busy", {"retry-after": "10"})],
        "gemini": [http_error(openai.RateLimitError, 429, "busy", {"retry-after": "20"})],
    })
    assert call_llm("mistake_analysis", "p") == "after waiting"
    assert fake.called() == ["groq", "openrouter", "gemini", "groq"]
    assert 5 <= clock["slept"] < 6  # waited for the soonest provider, not the longest


def test_daily_quota_is_never_waited_out(env):
    monkeypatch, clock = env
    daily = lambda: http_error(openai.RateLimitError, 429, "Rate limit reached on requests per day (RPD)")
    use(monkeypatch, {"groq": [daily()], "openrouter": [daily()], "gemini": [daily()]})
    with pytest.raises(AllProvidersFailedError):
        call_llm("mistake_analysis", "p")
    assert clock["slept"] == 0


def test_queue_gives_up_after_the_task_max_wait(env):
    monkeypatch, clock = env
    for name in ("GEMINI_API_KEY", "OPENROUTER_API_KEY"):
        monkeypatch.delenv(name)
    limited = lambda: http_error(openai.RateLimitError, 429, "busy", {"retry-after": "30"})
    use(monkeypatch, {"groq": [limited(), limited()]})
    with pytest.raises(AllProvidersFailedError) as info:
        call_llm("quiz_generate", "p")  # MAX_WAIT 40 s: one 30 s wait, then a 30 s wait won't fit
    assert clock["slept"] < router.MAX_WAIT["quiz_generate"]
    assert any(name == "queue" for name, _ in info.value.failures)


def test_tokens_per_minute_budget_spills_to_the_next_provider(env):
    monkeypatch, _ = env
    monkeypatch.setitem(router.LIMITS, "groq", {"concurrency": 4, "tpm": 1500})
    fake = use(monkeypatch, {"groq": ["first"], "gemini": ["second"]})
    assert call_llm("quiz_generate", "x" * 2000) == "first"        # ~1,800 tokens: allowed into an empty window
    assert call_llm("quiz_generate", "y" * 2000) == "second"       # groq's minute is spent: next provider
    assert fake.called() == ["groq", "gemini"]


def test_only_provider_out_of_tokens_waits_for_the_window(env):
    monkeypatch, clock = env
    for name in ("GEMINI_API_KEY", "OPENROUTER_API_KEY"):
        monkeypatch.delenv(name)
    monkeypatch.setitem(router.LIMITS, "groq", {"concurrency": 4, "tpm": 1000})
    fake = use(monkeypatch, {"groq": ["one", "two"]})
    assert call_llm("mistake_analysis", "a" * 3000) == "one"
    assert call_llm("mistake_analysis", "b" * 3000) == "two"       # queued until the first minute aged out
    assert fake.called() == ["groq", "groq"]
    assert 59 <= clock["slept"] <= 62


def test_hard_failures_are_not_retried_while_queuing(env):
    monkeypatch, clock = env
    request = httpx.Request("POST", "https://example.test")
    fake = use(monkeypatch, {
        "groq": [http_error(openai.RateLimitError, 429, "busy", {"retry-after": "3"}), "groq ok"],
        "gemini": [openai.APITimeoutError(request=request), openai.APITimeoutError(request=request)],
        "openrouter": [http_error(openai.InternalServerError, 500, "x"), http_error(openai.InternalServerError, 500, "x")],
    })
    assert call_llm("quiz_generate", "p") == "groq ok"
    # gemini and openrouter each got their one retry in round 1 and were not tried again.
    assert fake.called() == ["groq", "gemini", "gemini", "openrouter", "openrouter", "groq"]


def test_concurrency_limit_queues_simultaneous_calls(monkeypatch):
    """Real threads and a real clock: with room for one request, a burst runs one at a time."""
    import threading
    import time as real_time

    for name in ("GEMINI_API_KEY", "OPENROUTER_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("GROQ_API_KEY", "test-key-for-groq_api_key")
    router.reset_state()
    monkeypatch.setattr(router, "_clock", real_time.monotonic)
    monkeypatch.setattr(router, "_sleep", real_time.sleep)
    monkeypatch.setattr(router, "QUEUE_POLL_SECONDS", 0.02)
    monkeypatch.setitem(router.LIMITS, "groq", {"concurrency": 1, "tpm": None})

    in_flight = {"now": 0, "peak": 0}
    lock = threading.Lock()

    def slow_provider(provider, model, messages, *, json_mode, max_tokens, timeout):
        with lock:
            in_flight["now"] += 1
            in_flight["peak"] = max(in_flight["peak"], in_flight["now"])
        real_time.sleep(0.05)
        with lock:
            in_flight["now"] -= 1
        return "ok"

    monkeypatch.setattr(router, "_create_completion", slow_provider)
    results = []
    threads = [threading.Thread(target=lambda i=i: results.append(call_llm("quiz_generate", f"q{i}")))
               for i in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)
    router.reset_state()
    assert results == ["ok"] * 5   # nobody failed
    assert in_flight["peak"] == 1  # but they went through one at a time
