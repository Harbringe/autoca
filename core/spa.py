"""Serving the application shell.

The frontend is a static bundle built by Vite into ``frontend/dist``. Its
assets are hashed and served by WhiteNoise under ``/static/app/``; this view
serves the one file that is not an asset -- ``index.html`` -- for every route
under ``/app/``, and the router in the browser takes it from there.

The shell carries no data, which is why it is exempt from the MFA gate: a
session with only a password may load the page, and the page then drives the
second factor itself through the JSON endpoints. Everything the page *shows*
comes from ``/api/``, which is not exempt from anything.

The strict Content-Security-Policy applies here. The bundle is built to need
nothing it forbids: no inline scripts, no inline styles, no third-party origins.
"""

from __future__ import annotations

import functools
from pathlib import Path

from django.conf import settings
from django.http import HttpResponse, HttpResponseNotFound
from django.views.decorators.http import require_GET


@functools.lru_cache(maxsize=1)
def _index_html() -> str | None:
    path = Path(settings.FRONTEND_DIST) / "index.html"
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")


@require_GET
def index(request, path: str = ""):
    html = _index_html() if not settings.DEBUG else _read_fresh()
    if html is None:
        return HttpResponseNotFound(
            "The application has not been built. Run `npm ci && npm run build` in "
            "frontend/, then reload.",
            content_type="text/plain",
        )
    response = HttpResponse(html, content_type="text/html; charset=utf-8")
    # The shell is the same for everyone and changes only on deploy, but the
    # asset names inside it do change, so it must not be cached past a deploy.
    response["Cache-Control"] = "no-cache"
    return response


def _read_fresh() -> str | None:
    """In development, re-read on every request so a rebuild is picked up."""
    path = Path(settings.FRONTEND_DIST) / "index.html"
    return path.read_text(encoding="utf-8") if path.exists() else None
