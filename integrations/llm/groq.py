"""Groq, over its OpenAI-compatible chat completions endpoint.

Plain HTTP from the standard library rather than a vendor SDK. The request is
one JSON document and the reply is one JSON document; a client library would
add a dependency, a background thread pool and a retry policy of its own, and
none of that is wanted behind an interface this small.

What is fixed here and not configurable, on purpose:

* ``temperature`` is 0. Classification has to be reproducible; the same row
  should get the same suggestion tomorrow.
* ``response_format`` is JSON. The caller parses the reply; prose is a failure.
* Retries are bounded and only on the status codes that mean "try again" --
  5xx gets three attempts with exponential backoff; a rate limit gets six, each
  waiting as long as Groq's ``Retry-After`` says (capped at a minute), because a
  free-tier token-per-minute limit resets on its clock. Groq reports a request
  that does not fit what is left of the minute as a 413 with the code
  ``rate_limit_exceeded``, not a 429; that is the same limit and is waited out
  the same way. The same code on a request whose own size is over the limit
  ("limit 8000, requested 8325") is not waited out -- it never fits -- and the
  error says ``request_too_large`` so the caller sends a smaller one. A 400 is
  a bug in the prompt or a reply cut off by ``max_tokens``, and retrying it
  unchanged is noise.
* Requests are paced. Every reply says how many tokens are left this minute
  and when the budget refills; when the next request plainly will not fit, the
  adapter waits for the refill first instead of spending an attempt to be told.
  On an 8,000 tokens-a-minute plan one classification batch is most of a
  minute, so without this every batch after the first meets a limit.
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
import re
import time
import urllib.error
import urllib.request

from .base import LLMAdapter, LLMError, LLMResponse

logger = logging.getLogger("autoca.llm")

DEFAULT_BASE_URL = "https://api.groq.com/openai/v1"
DEFAULT_MODEL = "llama-3.3-70b-versatile"
RETRY_STATUSES = {429, 500, 502, 503, 504}
RATE_LIMIT_ATTEMPTS = 6
MAX_RETRY_AFTER_SECONDS = 60.0
#: Groq's code on a 413 about the per-minute budget. It uses the same code whether the minute is
#: spent (wait, and it fits) or the request alone is more than a minute allows (it never will);
#: the token counts in the message tell the two apart.
RATE_LIMIT_CODE = "rate_limit_exceeded"
#: Said in the error when a request can never fit, so a caller knows to send a smaller one.
TOO_LARGE = "the request is larger than the plan allows in a minute (request_too_large)"
#: A JSON request runs about three characters to a token; erring high only means waiting sooner.
CHARS_PER_TOKEN = 3


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
        # What the last reply said about this minute's token budget; None until one has.
        self._tokens_left: int | None = None
        self._budget_refills_at = 0.0

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
        attempts = max(self.max_attempts, RATE_LIMIT_ATTEMPTS)
        for attempt in range(1, attempts + 1):
            wait = delay
            self._wait_for_budget(len(body) // CHARS_PER_TOKEN)
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:  # noqa: S310
                    self._note_budget(getattr(response, "headers", None))
                    return json.loads(response.read().decode())
            except urllib.error.HTTPError as exc:
                last_error = exc
                code = _error_code(exc)  # reads the body, which can be read only once
                if exc.code == 413 and _larger_than_the_limit(code):
                    # No amount of waiting fits this request into a minute; only a smaller one will.
                    raise LLMError(f"Groq answered HTTP 413{code}; {TOO_LARGE}.") from exc
                # A rate limit resets on Groq's clock, not ours: wait as long as it says,
                # and allow more attempts, since a busy minute is not a failure.
                rate_limited = exc.code == 429 or (exc.code == 413 and RATE_LIMIT_CODE in code)
                limit = RATE_LIMIT_ATTEMPTS if rate_limited else self.max_attempts
                if not (rate_limited or exc.code in RETRY_STATUSES) or attempt >= limit:
                    raise LLMError(f"Groq answered HTTP {exc.code}{code}.") from exc
                if rate_limited:
                    self._tokens_left = None  # whatever the last reply said, it is spent
                    wait = _retry_after(exc, default=MAX_RETRY_AFTER_SECONDS if exc.code == 413 else delay)
                logger.warning("groq HTTP %s%s on attempt %d; retrying in %.0fs", exc.code, code, attempt, wait)
            except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
                last_error = exc
                if attempt >= self.max_attempts:
                    raise LLMError(f"Groq could not be reached: {type(exc).__name__}.") from exc
                logger.warning("groq %s on attempt %d; retrying", type(exc).__name__, attempt)
            time.sleep(wait)
            delay *= 2
        raise LLMError("Groq could not be reached.") from last_error

    # -- pacing ----------------------------------------------------------------

    def _note_budget(self, headers) -> None:
        if headers is None:
            return
        try:
            left = int(headers.get("x-ratelimit-remaining-tokens", ""))
        except (TypeError, ValueError):
            return
        self._tokens_left = left
        refill = _duration(headers.get("x-ratelimit-reset-tokens", ""))
        self._budget_refills_at = time.monotonic() + min(refill, MAX_RETRY_AFTER_SECONDS)

    def _wait_for_budget(self, tokens_needed: int) -> None:
        if self._tokens_left is None or self._tokens_left >= tokens_needed:
            return
        wait = self._budget_refills_at - time.monotonic()
        if wait > 0:
            logger.info(
                "groq budget has %d tokens left this minute, about %d needed; waiting %.0fs",
                self._tokens_left, tokens_needed, wait,
            )
            time.sleep(wait)
        self._tokens_left = None


def _larger_than_the_limit(code: str) -> bool:
    """True when Groq's counts say the request alone exceeds the limit (``requested`` > ``limit``)."""
    counts = dict(re.findall(r"\b(limit|requested) (\d+)", code))
    return "limit" in counts and "requested" in counts and int(counts["requested"]) > int(counts["limit"])


def _duration(value: str) -> float:
    """Groq's reset headers, such as ``7.66s``, ``1m2.5s`` or ``450ms``, in seconds."""
    total = 0.0
    for number, unit in re.findall(r"(\d+(?:\.\d+)?)(ms|h|m|s)", value or ""):
        total += float(number) * {"ms": 0.001, "s": 1, "m": 60, "h": 3600}[unit]
    return total


def _retry_after(exc: urllib.error.HTTPError, *, default: float) -> float:
    try:
        seconds = float(exc.headers.get("retry-after", ""))
    except (TypeError, ValueError, AttributeError):
        return default
    return min(max(seconds, 1.0), MAX_RETRY_AFTER_SECONDS)


def _error_code(exc: urllib.error.HTTPError) -> str:
    """Groq's machine-readable error code, never its message: that can quote the request.

    The one exception is the token counts in a rate-limit message ("Limit 8000, Used 0,
    Requested 9120"), which are only numbers and are what tells a spent minute apart from
    a request that is bigger than the whole minute allows.
    """
    try:
        error = json.loads(exc.read().decode()).get("error", {})
        code = error.get("code")
        message = str(error.get("message") or "")
    except (ValueError, AttributeError, OSError):
        return ""
    if not (isinstance(code, str) and code.isidentifier()):
        return ""
    counts = re.findall(r"\b(Limit|Used|Requested)\s+(\d+)", message)
    return f" ({code}: {', '.join(f'{k.lower()} {v}' for k, v in counts)})" if counts else f" ({code})"
