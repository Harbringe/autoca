"""The web application is a separate deployment; the backend only points at it."""

from __future__ import annotations

import pytest
from django.test import Client as HttpClient

pytestmark = pytest.mark.django_db


def test_root_sends_you_to_the_web_application(settings):
    settings.FRONTEND_URL = "https://app.example.test"
    response = HttpClient().get("/")
    assert response.status_code == 302
    assert response["Location"] == "https://app.example.test"


def test_the_backend_no_longer_serves_an_app_shell():
    assert HttpClient().get("/app/").status_code == 404


def test_a_local_frontend_url_is_flagged_in_production(settings):
    from core.checks import check_frontend_url_is_not_local_in_production as check

    settings.IS_PRODUCTION = True
    settings.FRONTEND_URL = "http://localhost:5173"
    assert [w.id for w in check(None)] == ["core.W016"]
    settings.FRONTEND_URL = "https://app.example.test"
    assert check(None) == []


def test_development_may_use_a_local_frontend_url(settings):
    from core.checks import check_frontend_url_is_not_local_in_production as check

    settings.IS_PRODUCTION = False
    settings.FRONTEND_URL = "http://localhost:5173"
    assert check(None) == []
