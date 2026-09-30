"""The Groq adapter's contract with the wire: what it sends, and what it tolerates."""

from __future__ import annotations

import io
import json
import urllib.error
from unittest import mock

import pytest

from integrations.llm.base import LLMError
from integrations.llm.groq import GroqLLMAdapter


class _Response(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _ok(content: dict) -> _Response:
    return _Response(
        json.dumps(
            {
                "model": "llama-3.3-70b-versatile",
                "choices": [{"message": {"content": json.dumps(content)}}],
                "usage": {"prompt_tokens": 120, "completion_tokens": 30},
            }
        ).encode()
    )


def test_it_refuses_to_start_without_a_key():
    with pytest.raises(ValueError):
        GroqLLMAdapter(api_key="")


def test_the_request_is_deterministic_json_mode_and_bears_the_key():
    adapter = GroqLLMAdapter(api_key="gsk_test", model="m")
    with mock.patch("urllib.request.urlopen", return_value=_ok({"suggestions": []})) as opened:
        response = adapter.complete_json("sys", "usr")

    request = opened.call_args.args[0]
    body = json.loads(request.data)
    assert request.full_url == "https://api.groq.com/openai/v1/chat/completions"
    assert request.get_header("Authorization") == "Bearer gsk_test"
    assert body["temperature"] == 0
    assert body["response_format"] == {"type": "json_object"}
    assert body["model"] == "m"
    assert [m["role"] for m in body["messages"]] == ["system", "user"]
    assert json.loads(response.text) == {"suggestions": []}
    assert response.input_tokens == 120 and response.output_tokens == 30


def test_a_non_json_reply_is_an_llm_error():
    adapter = GroqLLMAdapter(api_key="k")
    reply = _Response(json.dumps({"choices": [{"message": {"content": "sure thing!"}}]}).encode())
    with mock.patch("urllib.request.urlopen", return_value=reply), pytest.raises(LLMError):
        adapter.complete_json("s", "u")


def test_retries_on_429_then_succeeds():
    adapter = GroqLLMAdapter(api_key="k", max_attempts=3)
    too_many = urllib.error.HTTPError("u", 429, "rate", {}, None)
    with (
        mock.patch("urllib.request.urlopen", side_effect=[too_many, _ok({"a": 1})]),
        mock.patch("time.sleep") as slept,
    ):
        assert json.loads(adapter.complete_json("s", "u").text) == {"a": 1}
    assert slept.call_count == 1


def test_a_400_is_not_retried():
    adapter = GroqLLMAdapter(api_key="k", max_attempts=3)
    bad = urllib.error.HTTPError("u", 400, "bad", {}, None)
    with (
        mock.patch("urllib.request.urlopen", side_effect=[bad]) as opened,
        mock.patch("time.sleep"),
        pytest.raises(LLMError),
    ):
        adapter.complete_json("s", "u")
    assert opened.call_count == 1


def test_a_dead_network_gives_up_after_the_attempts():
    adapter = GroqLLMAdapter(api_key="k", max_attempts=2)
    with (
        mock.patch("urllib.request.urlopen", side_effect=urllib.error.URLError("down")) as opened,
        mock.patch("time.sleep"),
        pytest.raises(LLMError),
    ):
        adapter.complete_json("s", "u")
    assert opened.call_count == 2


def test_a_rate_limit_waits_as_long_as_groq_says():
    adapter = GroqLLMAdapter(api_key="k", max_attempts=3)
    too_many = urllib.error.HTTPError("u", 429, "rate", {"retry-after": "7"}, None)
    with (
        mock.patch("urllib.request.urlopen", side_effect=[too_many, _ok({"a": 1})]),
        mock.patch("time.sleep") as slept,
    ):
        adapter.complete_json("s", "u")
    slept.assert_called_once_with(7.0)


def test_a_rate_limit_gets_more_attempts_than_a_server_error():
    adapter = GroqLLMAdapter(api_key="k", max_attempts=3)
    limits = [urllib.error.HTTPError("u", 429, "rate", {"retry-after": "1"}, None) for _ in range(5)]
    with (
        mock.patch("urllib.request.urlopen", side_effect=[*limits, _ok({"a": 1})]) as opened,
        mock.patch("time.sleep"),
    ):
        adapter.complete_json("s", "u")
    assert opened.call_count == 6


def test_the_error_names_groqs_code_without_its_message():
    adapter = GroqLLMAdapter(api_key="k")
    body = io.BytesIO(json.dumps({"error": {"code": "json_validate_failed", "message": "quoted text"}}).encode())
    bad = urllib.error.HTTPError("u", 400, "bad", {}, body)
    with mock.patch("urllib.request.urlopen", side_effect=[bad]), pytest.raises(LLMError) as raised:
        adapter.complete_json("s", "u")
    assert "json_validate_failed" in str(raised.value)
    assert "quoted text" not in str(raised.value)


def _rate_limited_413() -> urllib.error.HTTPError:
    body = io.BytesIO(json.dumps({"error": {"code": "rate_limit_exceeded", "message": "quoted"}}).encode())
    return urllib.error.HTTPError("u", 413, "too large", {}, body)


def test_a_413_that_is_the_minute_budget_is_waited_out_like_a_429():
    """Groq reports a request that does not fit what is left of the minute as 413, not 429."""
    adapter = GroqLLMAdapter(api_key="k", max_attempts=3)
    with (
        mock.patch("urllib.request.urlopen", side_effect=[_rate_limited_413(), _ok({"a": 1})]) as opened,
        mock.patch("time.sleep") as slept,
    ):
        assert json.loads(adapter.complete_json("s", "u").text) == {"a": 1}
    assert opened.call_count == 2
    slept.assert_called_once_with(60.0)  # no Retry-After on a 413: wait for the minute to turn


def test_a_413_for_any_other_reason_is_not_retried():
    adapter = GroqLLMAdapter(api_key="k", max_attempts=3)
    body = io.BytesIO(json.dumps({"error": {"code": "request_too_large"}}).encode())
    too_big = urllib.error.HTTPError("u", 413, "too large", {}, body)
    with (
        mock.patch("urllib.request.urlopen", side_effect=[too_big]) as opened,
        mock.patch("time.sleep"),
        pytest.raises(LLMError) as raised,
    ):
        adapter.complete_json("s", "u")
    assert opened.call_count == 1
    assert "request_too_large" in str(raised.value)


def test_the_next_request_waits_when_the_last_reply_said_the_budget_is_spent():
    adapter = GroqLLMAdapter(api_key="k")
    first = _ok({"a": 1})
    first.headers = {"x-ratelimit-remaining-tokens": "40", "x-ratelimit-reset-tokens": "12.5s"}
    with (
        mock.patch("urllib.request.urlopen", side_effect=[first, _ok({"b": 2})]),
        mock.patch("time.sleep") as slept,
        mock.patch("time.monotonic", return_value=100.0),
    ):
        adapter.complete_json("s", "u")
        slept.assert_not_called()  # nothing was known about the budget before the first reply
        adapter.complete_json("s", "u" * 600)
    slept.assert_called_once_with(12.5)


def test_a_request_that_fits_the_budget_does_not_wait():
    adapter = GroqLLMAdapter(api_key="k")
    first = _ok({"a": 1})
    first.headers = {"x-ratelimit-remaining-tokens": "7000", "x-ratelimit-reset-tokens": "3s"}
    with (
        mock.patch("urllib.request.urlopen", side_effect=[first, _ok({"b": 2})]),
        mock.patch("time.sleep") as slept,
    ):
        adapter.complete_json("s", "u")
        adapter.complete_json("s", "u")
    slept.assert_not_called()


@pytest.mark.parametrize(
    ("value", "seconds"),
    [("7.66s", 7.66), ("1m2.5s", 62.5), ("450ms", 0.45), ("", 0.0), ("2h", 7200.0)],
)
def test_groqs_reset_durations_are_read_in_seconds(value, seconds):
    from integrations.llm.groq import _duration

    assert _duration(value) == pytest.approx(seconds)


def _413(message: str) -> urllib.error.HTTPError:
    body = io.BytesIO(json.dumps({"error": {"code": "rate_limit_exceeded", "message": message}}).encode())
    return urllib.error.HTTPError("u", 413, "too large", {"retry-after": "3"}, body)


def test_a_request_bigger_than_the_whole_minute_is_not_waited_for():
    """Seen on the free plan: "Limit 8000, Requested 8325". It will never fit, so fail at once."""
    adapter = GroqLLMAdapter(api_key="k", max_attempts=3)
    too_big = _413("Request too large for model on tokens per minute (TPM): Limit 8000, Requested 8325, please reduce")
    with (
        mock.patch("urllib.request.urlopen", side_effect=[too_big]) as opened,
        mock.patch("time.sleep") as slept,
        pytest.raises(LLMError) as raised,
    ):
        adapter.complete_json("s", "u")
    assert opened.call_count == 1
    slept.assert_not_called()
    assert "request_too_large" in str(raised.value)
    assert "limit 8000, requested 8325" in str(raised.value)
    assert "please reduce" not in str(raised.value), "only the counts, never Groq's prose"


def test_a_spent_minute_that_the_request_would_fit_is_waited_for():
    adapter = GroqLLMAdapter(api_key="k", max_attempts=3)
    spent = _413("Rate limit reached on tokens per minute (TPM): Limit 8000, Used 6100, Requested 5200.")
    with (
        mock.patch("urllib.request.urlopen", side_effect=[spent, _ok({"a": 1})]) as opened,
        mock.patch("time.sleep") as slept,
    ):
        adapter.complete_json("s", "u")
    assert opened.call_count == 2
    slept.assert_called_once_with(3.0)


# ---------------------------------------------------------------------------
# No-wait mode (the queue's call): one attempt, never a sleep, a typed rate-limit error
# ---------------------------------------------------------------------------


def _limit(code: int, message: str, retry_after: str | None = None) -> urllib.error.HTTPError:
    headers = {"retry-after": retry_after} if retry_after else {}
    body = io.BytesIO(json.dumps({"error": {"code": "rate_limit_exceeded", "message": message}}).encode())
    return urllib.error.HTTPError("u", code, "limit", headers, body)


def test_no_wait_mode_is_a_cached_twin_with_one_attempt_and_a_short_timeout():
    adapter = GroqLLMAdapter(api_key="k", timeout_seconds=30)
    twin = adapter.without_waiting()
    assert twin is adapter.without_waiting() and twin is not adapter
    assert twin.max_attempts == 1 and twin.timeout == 15.0
    assert adapter.max_attempts == 3 and adapter.timeout == 30.0


def test_a_minute_limit_raises_at_once_with_groqs_retry_after():
    from integrations.llm.base import LLMRateLimited

    adapter = GroqLLMAdapter(api_key="k").without_waiting()
    with (
        mock.patch("urllib.request.urlopen", side_effect=[_limit(429, "Rate limit reached (TPM)", "23")]) as opened,
        mock.patch("time.sleep") as slept,
        pytest.raises(LLMRateLimited) as raised,
    ):
        adapter.complete_json("s", "u")
    assert opened.call_count == 1
    slept.assert_not_called()
    assert (raised.value.retry_after, raised.value.daily) == (23.0, False)


def test_a_413_about_the_minute_budget_is_the_same_typed_error():
    from integrations.llm.base import LLMRateLimited

    adapter = GroqLLMAdapter(api_key="k").without_waiting()
    spent = _limit(413, "Rate limit reached on tokens per minute (TPM): Limit 8000, Used 6100, Requested 5200.", "3")
    with mock.patch("urllib.request.urlopen", side_effect=[spent]), mock.patch("time.sleep"), pytest.raises(LLMRateLimited) as raised:
        adapter.complete_json("s", "u")
    assert raised.value.retry_after == 3.0 and not raised.value.daily


def test_the_days_allowance_is_told_from_the_minutes():
    from integrations.llm.base import LLMRateLimited

    adapter = GroqLLMAdapter(api_key="k").without_waiting()
    per_day = _limit(429, "Rate limit reached for model on tokens per day (TPD): Limit 100000, Used 99990. Please try again in 12m3.4s.")
    with mock.patch("urllib.request.urlopen", side_effect=[per_day]), pytest.raises(LLMRateLimited) as raised:
        adapter.complete_json("s", "u")
    assert raised.value.daily is True
    assert raised.value.retry_after == pytest.approx(723.4)

    long_wait = _limit(429, "Rate limit reached.", "5400")
    with mock.patch("urllib.request.urlopen", side_effect=[long_wait]), pytest.raises(LLMRateLimited) as raised:
        adapter.complete_json("s", "u")
    assert raised.value.daily is True and raised.value.retry_after == 5400.0


def test_the_error_still_never_quotes_the_message():
    from integrations.llm.base import LLMRateLimited

    adapter = GroqLLMAdapter(api_key="k").without_waiting()
    quoting = _limit(429, "Rate limit reached for the request 'Being paid to RAMESH KUMAR'.", "5")
    with mock.patch("urllib.request.urlopen", side_effect=[quoting]), pytest.raises(LLMRateLimited) as raised:
        adapter.complete_json("s", "u")
    assert "RAMESH" not in str(raised.value)


def test_no_wait_mode_does_not_retry_a_server_error():
    adapter = GroqLLMAdapter(api_key="k").without_waiting()
    down = urllib.error.HTTPError("u", 503, "down", {}, None)
    with (
        mock.patch("urllib.request.urlopen", side_effect=[down, _ok({"a": 1})]) as opened,
        mock.patch("time.sleep") as slept,
        pytest.raises(LLMError),
    ):
        adapter.complete_json("s", "u")
    assert opened.call_count == 1
    slept.assert_not_called()


def test_no_wait_mode_raises_instead_of_waiting_for_the_budget_to_refill():
    from integrations.llm.base import LLMRateLimited

    adapter = GroqLLMAdapter(api_key="k").without_waiting()
    headers = {"x-ratelimit-remaining-tokens": "50", "x-ratelimit-reset-tokens": "20s"}
    first = _ok({"a": 1})
    first.headers = headers
    with mock.patch("urllib.request.urlopen", return_value=first):
        adapter.complete_json("s", "u")
    with (
        mock.patch("urllib.request.urlopen") as opened,
        mock.patch("time.sleep") as slept,
        pytest.raises(LLMRateLimited) as raised,
    ):
        adapter.complete_json("s", "u" * 3000)
    opened.assert_not_called()
    slept.assert_not_called()
    assert 0 < raised.value.retry_after <= 20


def test_the_waiting_adapter_is_unchanged():
    adapter = GroqLLMAdapter(api_key="k", max_attempts=3)
    adapter.without_waiting()
    limits = [urllib.error.HTTPError("u", 429, "rate", {"retry-after": "1"}, None) for _ in range(2)]
    with mock.patch("urllib.request.urlopen", side_effect=[*limits, _ok({"a": 1})]) as opened, mock.patch("time.sleep"):
        adapter.complete_json("s", "u")
    assert opened.call_count == 3
