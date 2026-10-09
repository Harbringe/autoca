"""OpenAI, over its chat completions endpoint, for classification and for reading page images.

It is the Groq adapter with the differences a newer OpenAI model needs, so the transport, the retry and
rate-limit handling, and the pacing are shared and tested once:

* the output limit goes in ``max_completion_tokens`` (set ``LLM_TOKEN_PARAM=max_tokens`` for an older model);
* ``temperature`` is sent only when ``LLM_TEMPERATURE`` is set, because some current models accept only their
  default and refuse any other value;
* page images travel as ``image_url`` parts holding a base64 data URL, which is how a vision-capable model is
  asked to read a scanned statement. The images are never written to a log, an error or the database.

Where the data is processed is decided by the OpenAI project and the base URL, not by this code. For in-country
processing create the project with the region OpenAI offers, and set ``LLM_BASE_URL`` to the regional endpoint its
data-residency settings name. The key and the base URL are read from the environment and never logged.

    LLM_BACKEND=integrations.llm.openai.OpenAILLMAdapter
    LLM_API_KEY=sk-...                 # set on the server with deploy/set-env.sh, never typed into chat or a file in git
    LLM_MODEL=<the model id>
    LLM_BASE_URL=https://api.openai.com/v1      # or the regional endpoint
"""

from __future__ import annotations

import base64

from .base import LLMResponse
from .groq import GroqLLMAdapter

DEFAULT_BASE_URL = "https://api.openai.com/v1"


class OpenAILLMAdapter(GroqLLMAdapter):
    LABEL = "OpenAI"
    supports_shared_context = True

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        timeout_seconds: float = 30.0,
        max_attempts: int = 3,
        temperature: float | None = None,
        token_param: str = "max_completion_tokens",  # noqa: S107 -- a request field name, not a secret
        image_detail: str = "high",
        strict_schema: bool = False,
        **_ignored,
    ):
        if not api_key:
            raise ValueError("LLM_API_KEY is not set; the OpenAI adapter cannot start without it.")
        if not model:
            raise ValueError("LLM_MODEL is not set; name the model to use.")
        super().__init__(
            api_key=api_key,
            model=model,
            base_url=base_url or DEFAULT_BASE_URL,
            timeout_seconds=timeout_seconds,
            max_attempts=max_attempts,
        )
        self.temperature = temperature
        self.token_param = token_param
        self.image_detail = image_detail
        #: Ask the provider to enforce a JSON schema (every key present, right types) where the caller supplies one.
        #: Off until a real call has shown the model accepts it: LLM_STRICT_SCHEMA=1.
        self.strict_schema = bool(strict_schema)

    def _request(self, system: str, user, max_tokens: int, shared: str | None = None, schema: dict | None = None) -> dict:
        # Reference material that is the same from call to call goes in its own message, ahead of what changes.
        # The provider caches a prompt up to a message boundary, so the second and later calls for a client pay
        # a fraction for it.
        messages = [{"role": "system", "content": system}]
        if shared:
            messages.append({"role": "user", "content": shared})
        messages.append({"role": "user", "content": user})
        body = {
            "model": self.model,
            self.token_param: max_tokens,
            "response_format": {"type": "json_object"},
            "messages": messages,
        }
        if schema is not None and self.strict_schema:
            body["response_format"] = {"type": "json_schema", "json_schema": {"name": "reading", "strict": True, "schema": schema}}
        if self.temperature is not None:
            body["temperature"] = self.temperature
        return body

    def complete_json_with_images(
        self, system: str, user: str, images: list[bytes], *, max_tokens: int = 4096, schema: dict | None = None
    ) -> LLMResponse:
        parts: list[dict] = [{"type": "text", "text": user}]
        for image in images:
            encoded = base64.b64encode(image).decode()
            parts.append(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/png;base64,{encoded}",
                        "detail": self.image_detail,
                    },
                }
            )
        return self._complete(system, parts, max_tokens, None, schema)
