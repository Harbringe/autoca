"""Stub LLM adapter. Out of scope for this phase; raises if called."""

from .base import LLMAdapter


class StubLLMAdapter(LLMAdapter):
    def __init__(self, **_ignored):
        pass

    def complete(self, prompt, *, max_tokens=1024, **kwargs):
        raise NotImplementedError(
            "No LLM backend is wired. The classification engine is a later "
            "phase; this adapter exists so its call sites can be written "
            "against a stable interface."
        )
