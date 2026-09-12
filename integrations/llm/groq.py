"""Groq, over its OpenAI-compatible chat completions endpoint.

Plain HTTP from the standard library rather than a vendor SDK. The request is
one JSON document and the reply is one JSON document; a client library would
add a dependency, a background thread pool and a retry policy of its own, and
none of that is wanted behind an interface this small.

What is fixed here and not configurable, on purpose:

* ``temperature`` is 0. Classification has to be reproducible; the same row
  should get the same suggestion tomorrow.
* ``response_format`` is JSON. The caller parses the reply; prose is a failure.
* Retries are bounded (three attempts, exponential backoff) and only on the
  status codes that mean "try again" -- 429 and 5xx. A 400 is a bug in the
  prompt and retrying it is noise.
* The key is read once at construction and never logged. The request body is
  never logged either; it is already pseudonymised, but a log line is a copy
  and there is no reason to make one.

Data handling: Groq's default terms do not commit to zero retention. The
classifier sends nothing that identifies a person -- see
``classify/pseudonymise.py`` -- which is what makes a provider without a ZDR
agreement acceptable for the pilot. Moving to a provider with in-country
inference is a change to LLM_BACKEND and one new file here.

    LLM_BACKEND=integrations.llm.groq.GroqLLMAdapter
    GROQ_API_KEY=gsk_...
    GROQ_MODEL=llama-3.3-70b-versatile      # optional
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request

from .base import LLMAdapter, LLMError, LLMResponse

logger = logging.getLogger("autoca.llm")

DEFAULT_BASE_URL = "https://api.groq.com/openai/v1"
DEFAULT_MODEL = "llama-3.3-70b-versatile"
RETRY_STATUSES = {429, 500, 502, 503, 504}


class GroqLLMAdapter(LLMAdapter):
    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        timeout_seconds: float = 30.0,
        max_attempts: int = 3,
        **_ignored,
    ):
        if not api_key:
            raise ValueError("GROQ_API_KEY is not set; the Groq adapter cannot start without it.")
        self._api_key = api_key
        self.model = model or DEFAULT_MODEL
        self.base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self.timeout = float(timeout_seconds)
        self.max_attempts = max(1, int(max_attempts))

    def complete_json(self, system: str, user: str, *, max_tokens: int = 2048) -> LLMResponse:
        body = json.dumps(
            {
                "model": self.model,
                "temperature": 0,
                "max_tokens": max_tokens,
                "response_format": {"type": "json_object"},
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            }
        ).encode()

        payload = self._post(body)

        try:
            text = payload["choices"][0]["message"]["content"]
            usage = payload.get("usage") or {}
        except (KeyError, IndexError, TypeError) as exc:
            raise LLMError("Groq returned a reply with no message in it.") from exc

        try:
            json.loads(text)
        except (TypeError, ValueError) as exc:
            raise LLMError("Groq returned a reply that is not JSON.") from exc

        return LLMResponse(
            text=text,
            model=payload.get("model") or self.model,
            input_tokens=int(usage.get("prompt_tokens") or 0),
            output_tokens=int(usage.get("completion_tokens") or 0),
        )

    # -- transport -------------------------------------------------------------

    def _post(self, body: bytes) -> dict:
        request = urllib.request.Request(  # noqa: S310 -- fixed https base URL
            f"{self.base_url}/chat/completions",
            data=body,
            method="POST",
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
                "User-Agent": "autoca/1.0",
            },
        )
        delay = 1.0
        last_error: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:  # noqa: S310
                    return json.loads(response.read().decode())
            except urllib.error.HTTPError as exc:
                last_error = exc
                if exc.code not in RETRY_STATUSES or attempt == self.max_attempts:
                    raise LLMError(f"Groq answered HTTP {exc.code}.") from exc
                logger.warning("groq HTTP %s on attempt %d; retrying", exc.code, attempt)
            except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
                last_error = exc
                if attempt == self.max_attempts:
                    raise LLMError(f"Groq could not be reached: {type(exc).__name__}.") from exc
                logger.warning("groq %s on attempt %d; retrying", type(exc).__name__, attempt)
            time.sleep(delay)
            delay *= 2
        raise LLMError("Groq could not be reached.") from last_error
