"""The application shell: public HTML, strict policy, nothing in it."""

from __future__ import annotations

import pytest
from django.test import Client as HttpClient

from core.provisioning import add_member, create_firm, create_user

pytestmark = pytest.mark.django_db

PASSWORD = "correct-horse-battery-staple"


@pytest.fixture
def built(tmp_path, settings):
    (tmp_path / "index.html").write_text(
        '<!doctype html><html><head><title>AutoCA</title></head><body><div id="root"></div>'
        '<script type="module" src="/static/app/assets/index-abc123.js"></script></body></html>',
        encoding="utf-8",
    )
    settings.FRONTEND_DIST = tmp_path
    settings.DEBUG = True  # re-read per request; no lru_cache to invalidate
    return tmp_path


def test_root_sends_you_to_the_app():
    response = HttpClient().get("/")
    assert response.status_code == 302
    assert response["Location"] == "/app/"


def test_every_app_route_serves_the_shell(built):
    http = HttpClient()
    for path in ("/app/", "/app/clients", "/app/clients/abc/review"):
        response = http.get(path)
        assert response.status_code == 200, path
        assert b'id="root"' in response.content
        assert response["Cache-Control"] == "no-cache"


def test_the_shell_is_reachable_by_a_half_authenticated_session(built):
    """The page drives MFA itself; it must load before MFA is done."""
    firm = create_firm("Firm")
    user = create_user("shell@example.com", PASSWORD)
    add_member(firm, user)
    http = HttpClient()
    http.post(
        "/auth/login/",
        {"email": "shell@example.com", "password": PASSWORD},
        content_type="application/json",
    )
    assert http.get("/app/").status_code == 200
    # ...but the data behind it is not.
    assert http.get("/api/v1/me/").status_code == 403


def test_the_shell_ships_under_the_strict_policy(built):
    response = HttpClient().get("/app/")
    csp = response["Content-Security-Policy"]
    assert "script-src 'self'" in csp
    assert "unsafe-inline" not in csp


def test_an_unbuilt_frontend_explains_itself(settings, tmp_path):
    settings.FRONTEND_DIST = tmp_path / "nowhere"
    settings.DEBUG = True
    response = HttpClient().get("/app/")
    assert response.status_code == 404
    assert b"npm run build" in response.content
