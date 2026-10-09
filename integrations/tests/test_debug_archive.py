"""The debug archive: filed in the right place and shape, off by default, and never the reason work fails."""

import json
from types import SimpleNamespace

import pytest

from integrations import debug_archive
from integrations.llm.base import LLMAdapter, LLMError, LLMRateLimited, LLMResponse


class _Inline:
    """A stand-in for the background pool: runs the write at once."""

    def submit(self, fn, *args):
        fn(*args)


class _Fake(LLMAdapter):
    def __init__(self, reply="{\"ok\": true}", error=None):
        self.reply, self.error = reply, error

    def complete_json(self, system, user, *, max_tokens=2048, **extra):
        if self.error:
            raise self.error
        return LLMResponse(text=self.reply, model="m", input_tokens=10, output_tokens=5)

    def complete_json_with_images(self, system, user, images, *, max_tokens=4096, schema=None):
        return self.complete_json(system, user, max_tokens=max_tokens)


@pytest.fixture
def archive(settings, monkeypatch):
    settings.DEBUG_ARCHIVE_ENABLED = True
    settings.DEBUG_ARCHIVE_BUCKET = "debug-bucket"
    settings.DEBUG_ARCHIVE_PREFIX = "dev"
    written = {}
    monkeypatch.setattr(debug_archive, "_put", lambda key, data, content_type: written.__setitem__(key, data))
    monkeypatch.setattr(debug_archive, "_pool", _Inline())
    return written


CLIENT = SimpleNamespace(pk="1234abcd-0000", name="Shri Narayan Trading Co.", firm_id="f1")


def test_off_by_default_writes_nothing(settings, monkeypatch):
    settings.DEBUG_ARCHIVE_ENABLED = False
    called = []
    monkeypatch.setattr(debug_archive, "_put", lambda *a: called.append(a))
    with debug_archive.trace("invoice", client=CLIENT, name="x.pdf") as t:
        t.text("extracted.txt", "hello")
    assert called == []
    assert debug_archive.wrap(_Fake()).__class__ is _Fake


def test_needs_a_bucket_as_well_as_the_flag(settings):
    settings.DEBUG_ARCHIVE_ENABLED = True
    settings.DEBUG_ARCHIVE_BUCKET = ""
    assert not debug_archive.enabled()


def test_folder_has_date_client_purpose_time_and_document(archive):
    with debug_archive.trace("invoice", client=CLIENT, name="Invoice 3938.pdf") as t:
        t.text("extracted.txt", "GSTIN 27CBQPK2746E1ZG")
    keys = sorted(archive)
    folder = t.folder
    parts = folder.split("/")
    assert parts[0] == "dev" and len(parts[1]) == 10 and parts[1][4] == "-"
    assert parts[2] == "shri-narayan-trading-co-1234abcd"
    assert parts[3] == "invoice" and parts[4].endswith("-invoice-3938-pdf")
    assert f"{folder}/extracted.txt" in keys and f"{folder}/meta.json" in keys
    assert archive[f"{folder}/extracted.txt"] == b"GSTIN 27CBQPK2746E1ZG"
    assert "27CBQPK2746E1ZG" not in folder  # identifiers never go in the key


def test_model_call_is_filed_with_request_raw_reply_and_meta(archive):
    llm = debug_archive.wrap(_Fake("{\"total\": 10}"))
    assert isinstance(llm, debug_archive.ArchivingLLM)
    with debug_archive.trace("classify", client=CLIENT, name="batch") as t:
        out = llm.complete_json("sys", "usr", max_tokens=50, shared="ref")
    assert out.text == "{\"total\": 10}"
    request = json.loads(archive[f"{t.folder}/call-1.request.json"])
    assert request == {"system": "sys", "shared": "ref", "user": "usr", "max_tokens": 50}
    assert archive[f"{t.folder}/call-1.response.txt"] == b"{\"total\": 10}"
    assert json.loads(archive[f"{t.folder}/call-1.response.json"]) == {"total": 10}
    meta = json.loads(archive[f"{t.folder}/call-1.meta.json"])
    assert meta["outcome"] == "ok" and meta["reply_parses_as_json"] is True and meta["output_tokens"] == 5


def test_a_reply_that_is_not_json_is_kept_raw(archive):
    llm = debug_archive.wrap(_Fake("{\"a\": 1, \"cut off"))
    with debug_archive.trace("classify", client=CLIENT, name="b") as t:
        llm.complete_json("s", "u")
    assert archive[f"{t.folder}/call-1.response.txt"] == b"{\"a\": 1, \"cut off"
    assert f"{t.folder}/call-1.response.json" not in archive
    assert json.loads(archive[f"{t.folder}/call-1.meta.json"])["reply_parses_as_json"] is False


def test_failures_are_filed_and_still_raised(archive):
    llm = debug_archive.wrap(_Fake(error=LLMRateLimited("slow down", retry_after=5)))
    with pytest.raises(LLMError):
        with debug_archive.trace("classify", client=CLIENT, name="b") as t:
            llm.complete_json("s", "u")
    assert json.loads(archive[f"{t.folder}/call-1.meta.json"])["outcome"] == "LLMRateLimited"
    meta = json.loads(archive[f"{t.folder}/meta.json"])
    assert meta["ended_with_error"].startswith("LLMRateLimited")


def test_images_are_counted_never_kept(archive):
    llm = debug_archive.wrap(_Fake("{}"))
    with debug_archive.trace("invoice", client=CLIENT, name="scan.pdf") as t:
        llm.complete_json_with_images("s", "u", [b"\x89PNG-one", b"\x89PNG-two"])
    request = json.loads(archive[f"{t.folder}/call-1.request.json"])
    assert request["page_images"] == 2
    assert not any(b"PNG" in data for data in archive.values())


def test_a_call_outside_any_trace_is_still_filed(archive):
    llm = debug_archive.wrap(_Fake("{}"))
    llm.complete_json("s", "u")
    assert any("/other/" in key and key.endswith("call-1.response.txt") for key in archive)


def test_a_broken_archive_never_breaks_the_work(settings, monkeypatch):
    settings.DEBUG_ARCHIVE_ENABLED = True
    settings.DEBUG_ARCHIVE_BUCKET = "b"

    def boom(*_a):
        raise OSError("bucket unreachable")

    monkeypatch.setattr(debug_archive, "_put", boom)
    monkeypatch.setattr(debug_archive, "_pool", _Inline())
    llm = debug_archive.wrap(_Fake("{\"x\": 1}"))
    with debug_archive.trace("invoice", client=CLIENT, name="a.pdf") as t:
        t.text("extracted.txt", "text")
        assert llm.complete_json("s", "u").text == "{\"x\": 1}"


def test_without_waiting_stays_inside_the_archive(archive):
    inner = _Fake("{}")
    inner.without_waiting = lambda: inner
    assert isinstance(debug_archive.wrap(inner).without_waiting(), debug_archive.ArchivingLLM)


def test_stub_is_not_wrapped(archive):
    from integrations.llm.stub import StubLLMAdapter

    stub = StubLLMAdapter()
    assert debug_archive.wrap(stub) is stub
