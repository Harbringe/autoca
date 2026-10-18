"""A small HTTP client for Sandbox (sandbox.co.in), the provider behind the GSTIN check and the GSTR-2B fetch.

Two kinds of token: the *application* token, made from the API key and secret (valid 24 hours, kept in this process), and a
*taxpayer* token made from the taxpayer's own OTP (valid 6 hours, kept by the caller, never here). Neither is logged and neither
is a Bearer token -- Sandbox wants it bare in the ``authorization`` header.

The key and secret come from settings (the server's secrets store); test keys (``key_test_...``) go to the test host, live keys to the
live one, by ``base_url``. Standard library only, like the model adapters.
"""

from __future__ import annotations

import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

TEST_URL = "https://test-api.sandbox.co.in"
LIVE_URL = "https://api.sandbox.co.in"
APP_TOKEN_SECONDS = 23 * 3600  # the token lives 24 hours; renew an hour early


class SandboxError(RuntimeError):
    """Could not reach Sandbox, or it refused. ``status`` is the HTTP status (0 when not reached)."""

    def __init__(self, message: str, *, status: int = 0, payload: dict | None = None):
        super().__init__(message)
        self.status = status
        self.payload = payload or {}


class SandboxClient:
    def __init__(self, api_key: str = "", api_secret: str = "", base_url: str = "", timeout: float = 30.0):
        self.api_key = api_key or ""
        self.api_secret = api_secret or ""
        self.base_url = (base_url or TEST_URL).rstrip("/")
        self.timeout = timeout
        self._token = ""
        self._token_until = 0.0
        self._lock = threading.Lock()

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.api_secret)

    def app_token(self) -> str:
        with self._lock:
            if self._token and time.time() < self._token_until:
                return self._token
            reply = self._send("POST", "/authenticate", headers={"x-api-key": self.api_key, "x-api-secret": self.api_secret})
            token = (reply.get("data") or {}).get("access_token")
            if not token:
                raise SandboxError("Sandbox did not give an access token.", payload=reply)
            self._token, self._token_until = token, time.time() + APP_TOKEN_SECONDS
            return token

    def call(self, method: str, path: str, *, token: str | None = None, body: dict | None = None, params: dict | None = None) -> dict:
        """One call with ``token`` (the taxpayer's) or, by default, the application token."""
        headers = {"authorization": token or self.app_token(), "x-api-key": self.api_key}
        return self._send(method, path, headers=headers, body=body, params=params)

    def _send(self, method: str, path: str, *, headers: dict, body: dict | None = None, params: dict | None = None) -> dict:
        if not self.configured:
            raise SandboxError("The GST provider is not set up on this server.")
        url = self.base_url + path
        if not url.startswith("https://"):
            raise SandboxError("The GST provider address must be https.")
        if params:
            url += "?" + urllib.parse.urlencode(params)
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(  # noqa: S310 -- https only, checked above
            url, data=data, method=method, headers={"accept": "application/json", "content-type": "application/json", **headers}
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:  # noqa: S310 -- base_url is settings, https
                return json.loads(response.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as exc:
            try:
                payload = json.loads(exc.read().decode("utf-8") or "{}")
            except (ValueError, UnicodeDecodeError):
                payload = {}
            raise SandboxError(str(payload.get("message") or f"Sandbox answered {exc.code}."), status=exc.code, payload=payload) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise SandboxError(f"Could not reach Sandbox ({exc.__class__.__name__}).") from exc
        except ValueError as exc:
            raise SandboxError("Sandbox sent something that is not JSON.") from exc
