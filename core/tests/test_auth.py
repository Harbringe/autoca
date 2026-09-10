"""Authentication, hashing, and the mandatory second factor."""

import pytest
from django.contrib.auth.hashers import identify_hasher
from django.test import Client as HttpClient

from core.provisioning import add_member, create_firm, create_user

pytestmark = pytest.mark.django_db

PASSWORD = "correct-horse-battery-staple"


def test_passwords_are_hashed_with_argon2id(settings):
    """The production hasher, exercised directly.

    The test settings swap in a fast hasher for speed, so without this test
    nothing would ever confirm that real passwords use argon2id.
    """
    settings.PASSWORD_HASHERS = ["django.contrib.auth.hashers.Argon2PasswordHasher"]
    user = create_user("hash@example.com", PASSWORD)

    assert user.password.startswith("argon2$argon2id$")
    assert identify_hasher(user.password).algorithm == "argon2"
    assert user.check_password(PASSWORD)


def test_login_is_not_a_user_enumeration_oracle():
    create_user("real@example.com", PASSWORD)
    http = HttpClient()

    wrong_password = http.post(
        "/auth/login/",
        {"email": "real@example.com", "password": "wrong"},
        content_type="application/json",
    )
    unknown_email = http.post(
        "/auth/login/",
        {"email": "nobody@example.com", "password": PASSWORD},
        content_type="application/json",
    )

    assert wrong_password.status_code == unknown_email.status_code == 401
    assert wrong_password.json() == unknown_email.json()


def test_password_alone_does_not_grant_access():
    """A session with one factor must not reach an authenticated endpoint."""
    firm = create_firm("Firm A")
    user = create_user("staff@example.com", PASSWORD)
    add_member(firm, user)

    http = HttpClient()
    login = http.post(
        "/auth/login/",
        {"email": "staff@example.com", "password": PASSWORD},
        content_type="application/json",
    )
    assert login.status_code == 200
    assert login.json()["mfa"] == "setup"

    response = http.get("/api/me/")
    assert response.status_code == 302
    assert "/auth/mfa/setup/" in response["Location"]


def test_inactive_user_cannot_authenticate():
    user = create_user("gone@example.com", PASSWORD)
    user.is_active = False
    user.save(update_fields=["is_active"])

    http = HttpClient()
    response = http.post(
        "/auth/login/",
        {"email": "gone@example.com", "password": PASSWORD},
        content_type="application/json",
    )
    assert response.status_code == 401


def test_email_is_normalised_to_lowercase():
    user = create_user("MixedCase@Example.COM", PASSWORD)
    assert user.email == "mixedcase@example.com"


def test_healthz_needs_no_auth_and_no_tenant_context():
    response = HttpClient().get("/healthz")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
