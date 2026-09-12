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

    # A JSON endpoint answers in JSON. A 302 to the HTML enrolment page is
    # unreadable to a fetch(), and an HTTP client that follows redirects by
    # default would report the refusal as a success.
    response = http.get("/api/me/")
    assert response.status_code == 403
    assert response.json()["code"] == "mfa_enrolment_required"
    assert response.json()["verify_at"] == "/auth/mfa/setup/"


def test_a_browser_is_still_redirected_to_enrol():
    """The HTML flow is unchanged: a person gets taken to the page they need."""
    firm = create_firm("Firm B")
    user = create_user("browser@example.com", PASSWORD)
    add_member(firm, user)

    http = HttpClient()
    http.post(
        "/auth/login/",
        {"email": "browser@example.com", "password": PASSWORD},
        content_type="application/json",
    )

    response = http.get("/admin/", HTTP_ACCEPT="text/html")
    assert response.status_code == 302
    assert response["Location"].startswith("/auth/mfa/setup/")
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


def test_the_docs_page_is_a_browser_page_not_an_api_caller():
    """/api/docs/ sits under /api/ but a person reads it, so redirect them.

    Without the exemption a half-verified session opening the Swagger page gets
    a JSON 403 rendered as text in the browser, with no way forward.
    """
    firm = create_firm("Firm C")
    user = create_user("reader@example.com", PASSWORD)
    add_member(firm, user)

    http = HttpClient()
    http.post(
        "/auth/login/",
        {"email": "reader@example.com", "password": PASSWORD},
        content_type="application/json",
    )

    docs = http.get("/api/docs/", HTTP_ACCEPT="text/html")
    assert docs.status_code == 302
    assert docs["Location"] == "/auth/mfa/setup/?next=/api/docs/"

    # The API itself still answers in JSON.
    assert http.get("/api/v1/me/").status_code == 403
    assert http.get("/api/v1/me/").json()["code"] == "mfa_enrolment_required"
