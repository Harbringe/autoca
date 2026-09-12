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
