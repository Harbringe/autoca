"""The OpenAI adapter: the same transport as Groq, with the request shape a newer model needs."""

from __future__ import annotations

import base64
import io
import json
import urllib.error
from unittest import mock

import pytest

from integrations.llm.base import LLMError, LLMUnavailable
from integrations.llm.groq import GroqLLMAdapter
from integrations.llm.openai import OpenAILLMAdapter
from integrations.llm.stub import StubLLMAdapter


def _ok(payload):
    class Reply(io.BytesIO):
        headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    body = {"model": "m", "choices": [{"message": {"content": json.dumps(payload)}}], "usage": {}}
    return Reply(json.dumps(body).encode())


def _sent(opened):
    request = opened.call_args.args[0]
    return request.full_url, json.loads(request.data)


def test_it_needs_a_key_and_a_model():
    with pytest.raises(ValueError, match="LLM_API_KEY"):
        OpenAILLMAdapter(model="m")
    with pytest.raises(ValueError, match="LLM_MODEL"):
        OpenAILLMAdapter(api_key="k")


def test_the_request_uses_the_newer_token_field_and_omits_temperature_by_default():
    adapter = OpenAILLMAdapter(api_key="k", model="m")
    with mock.patch("urllib.request.urlopen", return_value=_ok({"a": 1})) as opened:
        adapter.complete_json("sys", "user", max_tokens=100)

    url, body = _sent(opened)
    assert url == "https://api.openai.com/v1/chat/completions"
    assert (
        body["max_completion_tokens"] == 100
        and "max_tokens" not in body
        and "temperature" not in body
    )
    assert body["response_format"] == {"type": "json_object"}


def test_temperature_and_the_older_token_field_can_be_set():
    adapter = OpenAILLMAdapter(
        api_key="k",
        model="m",
        temperature=0,
        token_param="max_tokens",
        base_url="https://in.example/v1/",
    )
    with mock.patch("urllib.request.urlopen", return_value=_ok({"a": 1})) as opened:
        adapter.complete_json("sys", "user", max_tokens=50)

    url, body = _sent(opened)
    assert url == "https://in.example/v1/chat/completions"
    assert body["max_tokens"] == 50 and body["temperature"] == 0


def test_images_travel_as_data_urls_beside_the_text():
    adapter = OpenAILLMAdapter(api_key="k", model="m")
    with mock.patch("urllib.request.urlopen", return_value=_ok({"a": 1})) as opened:
        adapter.complete_json_with_images("sys", "read these", [b"\x89PNG-one", b"\x89PNG-two"])

    _, body = _sent(opened)
    parts = body["messages"][1]["content"]
    assert parts[0] == {"type": "text", "text": "read these"}
    assert [p["type"] for p in parts[1:]] == ["image_url", "image_url"]
    assert (
        parts[1]["image_url"]["url"]
        == "data:image/png;base64," + base64.b64encode(b"\x89PNG-one").decode()
    )


def test_errors_name_openai_not_groq_and_never_quote_the_request():
    adapter = OpenAILLMAdapter(api_key="k", model="m")
    body = io.BytesIO(
        json.dumps(
            {"error": {"code": "invalid_request_error", "message": "quoted page text"}}
        ).encode()
    )
    bad = urllib.error.HTTPError("u", 400, "bad", {}, body)
    with mock.patch("urllib.request.urlopen", side_effect=[bad]), pytest.raises(LLMError) as raised:
        adapter.complete_json("s", "u")

    assert "OpenAI answered HTTP 400" in str(raised.value) and "Groq" not in str(raised.value)
    assert "quoted page text" not in str(raised.value)


def test_groq_is_unchanged_by_the_shared_request_builder():
    adapter = GroqLLMAdapter(api_key="k")
    with mock.patch("urllib.request.urlopen", return_value=_ok({"a": 1})) as opened:
        adapter.complete_json("s", "u", max_tokens=7)

    _, body = _sent(opened)
    assert (
        body["temperature"] == 0 and body["max_tokens"] == 7 and "max_completion_tokens" not in body
    )


def test_a_provider_without_image_support_says_so():
    with pytest.raises(LLMUnavailable):
        StubLLMAdapter().complete_json_with_images("s", "u", [b"x"])
