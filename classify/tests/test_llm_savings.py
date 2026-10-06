"""What keeps model cost down: rows that read alike are asked once, and shared reference goes ahead as its own message."""

from __future__ import annotations

import io
import json
from types import SimpleNamespace
from unittest import mock

from classify.llm import group_alike
from integrations.llm.groq import GroqLLMAdapter
from integrations.llm.openai import OpenAILLMAdapter


class FakeMasker:
    """Stands in for the pseudonymiser: a row's view is whatever its transaction says."""

    def row(self, transaction, key=None):
        return SimpleNamespace(
            as_prompt_dict=lambda: {"key": key, "date": transaction.date, **transaction.view}
        )


def row(date, **view):
    return SimpleNamespace(transaction=SimpleNamespace(date=date, view=view))


def test_rows_that_read_alike_are_grouped_whatever_their_date():
    a = row("01-04-2025", narration="NACH EMI", amount="5000.00", direction="debit")
    b = row("01-05-2025", narration="NACH EMI", amount="5000.00", direction="debit")
    c = row("01-06-2025", narration="NACH EMI", amount="5000.00", direction="debit")

    assert group_alike([a, b, c], FakeMasker()) == [[a, b, c]]


def test_a_different_amount_or_direction_or_narration_is_asked_separately():
    base = {"narration": "NACH EMI", "amount": "5000.00", "direction": "debit"}
    rows = [
        row("d", **base),
        row("d", **{**base, "amount": "5001.00"}),
        row("d", **{**base, "direction": "credit"}),
        row("d", **{**base, "narration": "NACH OTHER"}),
    ]

    assert [len(g) for g in group_alike(rows, FakeMasker())] == [1, 1, 1, 1]


def test_groups_keep_the_order_rows_first_appear():
    first = row("d", narration="A")
    second = row("d", narration="B")
    again = row("d", narration="A")

    groups = group_alike([first, second, again], FakeMasker())

    assert groups == [[first, again], [second]]


def _ok(payload, usage=None):
    class Reply(io.BytesIO):
        headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    body = {
        "model": "m",
        "choices": [{"message": {"content": json.dumps(payload)}}],
        "usage": usage or {},
    }
    return Reply(json.dumps(body).encode())


def test_openai_sends_the_shared_reference_as_its_own_message_before_the_request():
    adapter = OpenAILLMAdapter(api_key="k", model="m")
    with mock.patch("urllib.request.urlopen", return_value=_ok({"a": 1})) as opened:
        adapter.complete_json("sys", "the rows", shared="the chart")

    messages = json.loads(opened.call_args.args[0].data)["messages"]
    assert [m["content"] for m in messages] == ["sys", "the chart", "the rows"]
    assert adapter.supports_shared_context is True


def test_without_shared_material_the_request_is_the_two_messages_it_always_was():
    adapter = OpenAILLMAdapter(api_key="k", model="m")
    with mock.patch("urllib.request.urlopen", return_value=_ok({"a": 1})) as opened:
        adapter.complete_json("sys", "the rows")

    assert len(json.loads(opened.call_args.args[0].data)["messages"]) == 2


def test_the_cached_tokens_the_provider_reports_are_read():
    adapter = OpenAILLMAdapter(api_key="k", model="m")
    usage = {
        "prompt_tokens": 3000,
        "completion_tokens": 50,
        "prompt_tokens_details": {"cached_tokens": 2500},
    }
    with mock.patch("urllib.request.urlopen", return_value=_ok({"a": 1}, usage)):
        reply = adapter.complete_json("s", "u")

    assert (reply.input_tokens, reply.cached_tokens) == (3000, 2500)


def test_groq_keeps_one_merged_prompt_and_says_it_has_no_shared_context():
    assert GroqLLMAdapter(api_key="k").supports_shared_context is False
