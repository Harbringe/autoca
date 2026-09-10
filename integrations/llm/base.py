"""LLM interface -- declared, not wired.

Classification (embedding tier, LLM fallback, masking/pseudonymisation) is a
later phase. The interface exists now only so that nothing outside
integrations/llm/ has to change when it lands.

When it does land, note the constraint that shapes it: client financial data
must be masked or pseudonymised before it leaves the deployment. That belongs in
the classify/ app, above this adapter -- an adapter that quietly did its own
masking would make the guarantee impossible to audit.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass


@dataclass(frozen=True)
class LLMResponse:
    text: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0


class LLMAdapter(abc.ABC):
    @abc.abstractmethod
    def complete(self, prompt: str, *, max_tokens: int = 1024, **kwargs) -> LLMResponse:
        ...

    @property
    def name(self) -> str:
        return type(self).__name__
