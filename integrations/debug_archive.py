"""A short-lived debug archive of what was read and what the model said, for the developer and nobody else.

When something comes out of a reading wrong, the only way to see why is to see what went in and what came back. This keeps,
for a few days, exactly that, in a bucket of its own:

    <prefix>/<YYYY-MM-DD>/<client>-<id8>/<purpose>/<HHMMSS>-<document>/
        meta.json              who, what, when, how long, how it ended
        extracted.txt          the text read out of the file (before the model, unmasked)
        call-1.request.json    what was sent to the model (the masked version: this is what left the building)
        call-1.response.txt    the model's reply, exactly as it came, before anything parsed it
        call-1.response.json   the same, parsed and indented, when it parses
        call-1.meta.json       model, tokens, time, whether it parsed
        kept.json / outcome.json   what the app did with it

This is a deliberate exception to "nothing sent to the model is kept": it holds client data, so it is OFF unless
``DEBUG_ARCHIVE_ENABLED`` is set, goes to its own bucket (``DEBUG_ARCHIVE_BUCKET``) that the server may only write to, expires
by a lifecycle rule (docs/DEBUG_ARCHIVE.md), and never raises into the work it is watching: if the archive cannot be written,
that is logged (without content) and the upload or classification goes on.

Page images are not kept, only their count.
"""

from __future__ import annotations

import contextvars
import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, datetime

from django.conf import settings

from .llm.base import LLMAdapter, LLMError, LLMResponse

logger = logging.getLogger("autoca.debug_archive")

_current: contextvars.ContextVar = contextvars.ContextVar("debug_archive_trace", default=None)
_pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="debug-archive")
#: Where bytes go. Replaced in tests; by default an S3 adapter on the archive bucket.
_sink = None


def enabled() -> bool:
    return bool(getattr(settings, "DEBUG_ARCHIVE_ENABLED", False)) and bool(getattr(settings, "DEBUG_ARCHIVE_BUCKET", ""))


def _put(key: str, data: bytes, content_type: str) -> None:
    global _sink
    if _sink is None:
        from .storage.s3 import S3StorageAdapter

        _sink = S3StorageAdapter(
            bucket=settings.DEBUG_ARCHIVE_BUCKET,
            region=getattr(settings, "DEBUG_ARCHIVE_REGION", "") or "ap-south-1",
        )
    _sink.put(key, data, content_type=content_type)


def _slug(text: str, limit: int = 40) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(text or "").lower()).strip("-")[:limit] or "unnamed"


def _client_label(client) -> str:
    if client is None:
        return "no-client"
    return f"{_slug(getattr(client, 'name', ''))}-{str(getattr(client, 'pk', ''))[:8]}"


class Trace:
    """One thing being read: a file, or one batch of statement rows. Collects files and writes them out in the background."""

    def __init__(self, purpose: str, client, name: str):
        started = datetime.now(UTC)
        self.purpose = purpose
        self.client = client
        self.name = name
        self.started = started
        self._t0 = time.monotonic()
        self.calls = 0
        prefix = (getattr(settings, "DEBUG_ARCHIVE_PREFIX", "dev") or "dev").strip("/")
        self.folder = (
            f"{prefix}/{started:%Y-%m-%d}/{_client_label(client)}/{_slug(purpose)}/"
            f"{started:%H%M%S}-{_slug(name, 50)}"
        )

    def text(self, filename: str, text: str) -> None:
        self._write(filename, (text or "").encode("utf-8"), "text/plain; charset=utf-8")

    def json(self, filename: str, value) -> None:
        body = json.dumps(value, ensure_ascii=False, indent=2, default=str)
        self._write(filename, body.encode("utf-8"), "application/json")

    def next_call(self) -> str:
        self.calls += 1
        return f"call-{self.calls}"

    def _write(self, filename: str, data: bytes, content_type: str) -> None:
        key = f"{self.folder}/{filename}"
        _pool.submit(self._safe_put, key, data, content_type)

    @staticmethod
    def _safe_put(key: str, data: bytes, content_type: str) -> None:
        try:
            _put(key, data, content_type)
        except Exception as exc:  # the archive must never be the reason work fails
            logger.warning("debug archive write failed (%s): %s", type(exc).__name__, str(exc)[:120])

    def finish(self, error: BaseException | None = None) -> None:
        self.json(
            "meta.json",
            {
                "purpose": self.purpose,
                "document": self.name,
                "client_id": str(getattr(self.client, "pk", "") or ""),
                "firm_id": str(getattr(self.client, "firm_id", "") or ""),
                "started_utc": self.started.isoformat(),
                "seconds": round(time.monotonic() - self._t0, 2),
                "model_calls": self.calls,
                "ended_with_error": f"{type(error).__name__}: {str(error)[:300]}" if error else None,
            },
        )


class _NullTrace:
    """Archive off: every call is a no-op, so call sites need no ``if``."""

    calls = 0
    folder = ""

    def text(self, *_a, **_k) -> None: ...
    def json(self, *_a, **_k) -> None: ...
    def next_call(self) -> str:
        return "call-0"
    def finish(self, *_a, **_k) -> None: ...


@contextmanager
def trace(purpose: str, *, client=None, name: str = ""):
    """Everything the model is asked inside this block is filed together. Yields something with ``.text`` and ``.json``."""
    if not enabled():
        yield _NullTrace()
        return
    current = Trace(purpose, client, name)
    token = _current.set(current)
    error = None
    try:
        yield current
    except BaseException as exc:
        error = exc
        raise
    finally:
        _current.reset(token)
        try:
            current.finish(error)
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("debug archive close failed: %s", type(exc).__name__)


def current():
    """The trace in progress, or a no-op one."""
    return _current.get() or _NullTrace()


class ArchivingLLM(LLMAdapter):
    """Wraps the real adapter: asks it exactly what was asked, files what went out and what came back."""

    def __init__(self, inner: LLMAdapter):
        self._inner = inner
        self.is_available = inner.is_available
        self.supports_shared_context = inner.supports_shared_context

    @property
    def name(self) -> str:
        return self._inner.name

    def without_waiting(self) -> LLMAdapter:
        return ArchivingLLM(self._inner.without_waiting())

    def complete_json(self, system, user, *, max_tokens=2048, **extra):
        request = {"system": system, "shared": extra.get("shared"), "user": user, "max_tokens": max_tokens}
        return self._call(lambda: self._inner.complete_json(system, user, max_tokens=max_tokens, **extra), request)

    def complete_json_with_images(self, system, user, images, *, max_tokens=4096):
        request = {"system": system, "user": user, "max_tokens": max_tokens, "page_images": len(images)}
        return self._call(lambda: self._inner.complete_json_with_images(system, user, images, max_tokens=max_tokens), request)

    def _call(self, ask, request: dict) -> LLMResponse:
        active = _current.get()
        ad_hoc = active is None
        if ad_hoc:  # a model call outside any traced block is still filed, under "other"
            active = Trace("other", None, "untraced")
        label = active.next_call()
        started = time.monotonic()
        try:
            response = ask()
        except LLMError as exc:
            active.json(f"{label}.request.json", request)
            active.json(f"{label}.meta.json", {"outcome": type(exc).__name__, "error": str(exc)[:500], "seconds": round(time.monotonic() - started, 2)})
            if ad_hoc:
                active.finish(exc)
            raise
        parsed = None
        try:
            parsed = json.loads(response.text)
        except ValueError:
            pass
        active.json(f"{label}.request.json", request)
        active.text(f"{label}.response.txt", response.text)
        if parsed is not None:
            active.json(f"{label}.response.json", parsed)
        active.json(
            f"{label}.meta.json",
            {
                "outcome": "ok",
                "model": response.model,
                "input_tokens": response.input_tokens,
                "output_tokens": response.output_tokens,
                "cached_tokens": response.cached_tokens,
                "seconds": round(time.monotonic() - started, 2),
                "reply_parses_as_json": parsed is not None,
            },
        )
        if ad_hoc:
            active.finish()
        return response


def wrap(llm: LLMAdapter) -> LLMAdapter:
    """The adapter to hand out: the real one, or the real one inside the archive when the archive is on."""
    if not enabled() or isinstance(llm, ArchivingLLM) or not llm.is_available:
        return llm
    return ArchivingLLM(llm)
