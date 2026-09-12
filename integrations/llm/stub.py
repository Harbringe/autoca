"""No model. The default until a provider is configured.

``is_available`` is False, so the classifier skips the model tier entirely and
every unplaced row goes to a person. A firm that never configures a provider
gets the rules-plus-review product, which is complete in itself.
"""

from .base import LLMAdapter, LLMUnavailable


class StubLLMAdapter(LLMAdapter):
    is_available = False

    def __init__(self, **_ignored):
        pass

    def complete_json(self, system, user, *, max_tokens=2048):
        raise LLMUnavailable(
            "No LLM backend is configured. Set LLM_BACKEND to a provider adapter "
            "(e.g. integrations.llm.groq.GroqLLMAdapter) and its key."
        )
