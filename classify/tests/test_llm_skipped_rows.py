"""Rows the model skips are asked about again once; the archive can say which were skipped. No database needed."""

from types import SimpleNamespace

from classify import llm


def _rows(*pks):
    return [SimpleNamespace(pk=pk) for pk in pks]


def test_skipped_rows_are_asked_again_once_and_merged(monkeypatch):
    calls = []

    def fake(_llm, batch, *_a):
        calls.append([r.pk for r in batch])
        # the first ask answers only row 1; the second answers what it is asked
        return {str(r.pk): {"ledger": "L"} for r in batch if len(calls) > 1 or r.pk == 1}

    monkeypatch.setattr(llm, "_ask_halving", fake)
    replies = llm._ask_splitting(None, _rows(1, 2, 3), None, None, None)
    assert calls == [[1, 2, 3], [2, 3]]
    assert set(replies) == {"1", "2", "3"}


def test_nothing_is_asked_again_when_everything_was_answered(monkeypatch):
    calls = []

    def fake(_llm, batch, *_a):
        calls.append(1)
        return {str(r.pk): {} for r in batch}

    monkeypatch.setattr(llm, "_ask_halving", fake)
    llm._ask_splitting(None, _rows(1, 2), None, None, None)
    assert len(calls) == 1


def test_a_failed_second_ask_keeps_what_the_first_gave(monkeypatch):
    from integrations.llm.base import LLMError

    def fake(_llm, batch, *_a):
        if len(batch) == 1:
            raise LLMError("busy")
        return {"1": {"ledger": "L"}}

    monkeypatch.setattr(llm, "_ask_halving", fake)
    assert set(llm._ask_splitting(None, _rows(1, 2), None, None, None)) == {"1"}


def test_the_shape_report_names_skipped_rows_and_missing_fields():
    keys = {"r1": object(), "r2": object(), "r3": object()}
    items = [{"key": "r1", "ledger": "A"}, {"key": "r1", "ledger": "B"}, {"key": "r9"}]
    replies = {"r1": items[0]}
    report = llm._shape_of(keys, items, replies)
    assert report["skipped_by_model"] == ["r2", "r3"]
    assert report["keys_not_asked"] == ["r9"]
    assert report["duplicate_keys"] == ["r1"]
    assert "narration" in report["fields_missing_per_answer"]["r1"]
