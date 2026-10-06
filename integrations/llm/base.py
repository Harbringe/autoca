"""LLM interface.

The model performs one narrow task in this system: given a bank transaction
that no rule could place, suggest which of the client's own ledger heads it
belongs to. It is a fallback behind the rules, its answer is a suggestion a
person reviews, and it never sees an unmasked narration.

That last constraint is enforced *above* this adapter, in ``classify/``. An
adapter that quietly did its own masking would make the guarantee impossible
to audit -- the reviewer would have to read every adapter to know what left the
building. So this layer is deliberately dumb: it takes a system prompt and a
user message, asks for a JSON object back, and reports what it cost.

The interface is shaped for structured output because the caller needs a
parseable answer, not prose. Every adapter must honour ``temperature=0`` and
JSON-only responses; a provider that cannot is not a fit for this slot.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass


class LLMError(RuntimeError):
    """The provider could not be reached, refused, or returned nothing usable."""


class LLMUnavailable(LLMError):
    """No provider is configured. Callers degrade rather than fail."""


class LLMRateLimited(LLMError):
    """The provider's allowance is spent. Nothing was slept through to find that out.

    ``retry_after`` is seconds until it is worth asking again. ``daily`` is True
    when it is the day's allowance rather than this minute's, so the caller
    should stop asking for a long while instead of a few seconds.
    """

    def __init__(self, message: str, *, retry_after: float, daily: bool = False):
        super().__init__(message)
        self.retry_after = float(retry_after)
        self.daily = daily


@dataclass(frozen=True)
class LLMResponse:
    #: The model's reply. For :meth:`LLMAdapter.complete_json` this is a JSON
    #: document -- the adapter has already checked that it parses.
    text: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    #: Input tokens the provider served from its prompt cache (billed at a fraction). 0 when it does not say.
    cached_tokens: int = 0


class LLMAdapter(abc.ABC):
    #: False for the stub. Callers check this once rather than catching
    #: :class:`LLMUnavailable` on every row.
    is_available: bool = True
    #: True for a provider that takes ``shared=`` reference material as its own message ahead of the request, so
    #: its prompt cache can reuse it across calls. Others get one merged prompt, exactly as before.
    supports_shared_context: bool = False

    @abc.abstractmethod
    def complete_json(self, system: str, user: str, *, max_tokens: int = 2048) -> LLMResponse:
        """Ask for a single JSON object and return it, unparsed, in ``text``.

        Raises :class:`LLMError` on transport failure, a provider error, or a
        reply that is not JSON. Never raises anything else: the caller's job is
        to degrade gracefully, and it can only do that against one exception.
        """

    def complete_json_with_images(
        self, system: str, user: str, images: list[bytes], *, max_tokens: int = 4096
    ) -> LLMResponse:
        """As :meth:`complete_json`, with page images (PNG bytes) beside the text.

        Only a provider that can read images implements this. Everything else says so, and the
        caller falls back to refusing the document rather than guessing.
        """
        raise LLMUnavailable(f"{self.name} cannot read page images.")

    def without_waiting(self) -> LLMAdapter:
        """An adapter for a caller that must not sit in a backoff.

        One attempt, a short timeout, and :class:`LLMRateLimited` instead of
        sleeping. An adapter that never sleeps is its own answer.
        """
        return self

    @property
    def name(self) -> str:
        return type(self).__name__
