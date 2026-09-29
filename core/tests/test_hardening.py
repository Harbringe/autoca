"""The guard rails around the edges: lockouts, headers, masking, trust boundaries."""

from __future__ import annotations

import logging

import pytest
from django.core.cache import cache
from django.test import Client as HttpClient
from django.test import RequestFactory

from core import throttle
from core.http import client_ip, request_id
from core.identifiers import gstin_check_character, is_valid_gstin, is_valid_pan
from core.logging import MaskingFilter
from core.masking import mask, mask_text
from core.provisioning import add_member, create_firm, create_user

pytestmark = pytest.mark.django_db

PASSWORD = "correct-horse-battery-staple"


@pytest.fixture(autouse=True)
def _clean_cache():
    cache.clear()
    yield
    cache.clear()


# ---------------------------------------------------------------------------
# Login lockout
# ---------------------------------------------------------------------------


def _login(http, email, password):
    return http.post(
        "/auth/login/",
        {"email": email, "password": password},
        content_type="application/json",
    )


def test_repeated_failures_lock_the_account_out(settings):
    settings.THROTTLE_LIMITS = {
        **settings.THROTTLE_LIMITS,
        "login": {"attempts": 3, "window_seconds": 600, "lockout_seconds": 600},
    }
    create_user("target@example.com", PASSWORD)
    http = HttpClient()

    for _ in range(3):
        assert _login(http, "target@example.com", "wrong").status_code == 401

    locked = _login(http, "target@example.com", PASSWORD)  # even the right password
    assert locked.status_code == 429
    assert locked.json()["code"] == "too_many_attempts"
    assert locked["Retry-After"] == "600"


def test_the_lockout_follows_the_account_across_addresses(settings):
    settings.THROTTLE_LIMITS = {
        **settings.THROTTLE_LIMITS,
        "login": {"attempts": 2, "window_seconds": 600, "lockout_seconds": 600},
    }
    create_user("target@example.com", PASSWORD)

    _login(HttpClient(REMOTE_ADDR="10.0.0.1"), "target@example.com", "wrong")
    _login(HttpClient(REMOTE_ADDR="10.0.0.2"), "target@example.com", "wrong")

    response = _login(HttpClient(REMOTE_ADDR="10.0.0.3"), "target@example.com", PASSWORD)
    assert response.status_code == 429


def test_one_address_failing_on_many_accounts_is_not_locked_out_for_now(settings):
    """Interim (R1-40): the address is not trustworthy behind the shared proxy, so it must
    not refuse on its own; one address would otherwise lock every user behind it."""
    settings.THROTTLE_LIMITS = {
        **settings.THROTTLE_LIMITS,
        "login": {"attempts": 2, "window_seconds": 600, "lockout_seconds": 600},
    }
    create_user("c@example.com", PASSWORD)
    http = HttpClient(REMOTE_ADDR="10.9.9.9")
    for name in ("a", "b", "d", "e"):
        assert _login(http, f"{name}@example.com", "wrong").status_code == 401

    assert _login(http, "c@example.com", PASSWORD).status_code == 200


def test_the_account_lock_lasts_five_minutes_after_ten_failures(settings):
    limit = settings.THROTTLE_LIMITS["login"]
    assert limit["attempts"] == 10
    assert limit["lockout_seconds"] == 5 * 60


def test_a_locked_out_caller_is_not_told_whether_the_account_exists(settings):
    settings.THROTTLE_LIMITS = {
        **settings.THROTTLE_LIMITS,
        "login": {"attempts": 1, "window_seconds": 600, "lockout_seconds": 600},
    }
    create_user("real@example.com", PASSWORD)
    http = HttpClient()
    _login(http, "real@example.com", "wrong")
    _login(http, "nobody@example.com", "wrong")
    real = _login(http, "real@example.com", "wrong")
    unknown = _login(http, "nobody@example.com", "wrong")
    assert real.status_code == unknown.status_code == 429
    assert real.json() == unknown.json()


def test_mfa_codes_are_throttled_too(settings):
    settings.THROTTLE_LIMITS = {
        **settings.THROTTLE_LIMITS,
        "mfa": {"attempts": 2, "window_seconds": 600, "lockout_seconds": 600},
    }
    firm = create_firm("Firm")
    user = create_user("mfa@example.com", PASSWORD)
    add_member(firm, user)
    http = HttpClient()
    _login(http, "mfa@example.com", PASSWORD)
    http.post("/auth/mfa/setup/", {}, content_type="application/json")  # provision a device

    for _ in range(2):
        response = http.post(
            "/auth/mfa/verify/", {"token": "000000"}, content_type="application/json"
        )
        assert response.status_code == 401
    response = http.post("/auth/mfa/verify/", {"token": "000000"}, content_type="application/json")
    assert response.status_code == 429


def test_clear_unlocks(settings):
    settings.THROTTLE_LIMITS = {
        **settings.THROTTLE_LIMITS,
        "login": {"attempts": 1, "window_seconds": 600, "lockout_seconds": 600},
    }
    throttle.record_failure("login", "1.2.3.4")
    with pytest.raises(throttle.Throttled):
        throttle.check("login", "1.2.3.4")
    throttle.clear("login", "1.2.3.4")
    throttle.check("login", "1.2.3.4")


# ---------------------------------------------------------------------------
# Trust boundaries on request metadata
# ---------------------------------------------------------------------------


def test_forwarded_for_is_ignored_with_no_trusted_proxy(settings):
    settings.TRUSTED_PROXY_COUNT = 0
    request = RequestFactory().get(
        "/", REMOTE_ADDR="10.0.0.5", HTTP_X_FORWARDED_FOR="1.1.1.1, 2.2.2.2"
    )
    assert client_ip(request) == "10.0.0.5"


def test_forwarded_for_is_read_from_the_right_with_one_proxy(settings):
    """The client may prepend anything it likes; the proxy appends the truth."""
    settings.TRUSTED_PROXY_COUNT = 1
    request = RequestFactory().get(
        "/", REMOTE_ADDR="10.0.0.5", HTTP_X_FORWARDED_FOR="6.6.6.6, 203.0.113.9"
    )
    assert client_ip(request) == "203.0.113.9"


def test_a_hostile_request_id_is_replaced():
    request = RequestFactory().get("/", HTTP_X_REQUEST_ID="abc\ninjected line\x00" + "x" * 500)
    fresh = request_id(request)
    assert "\n" not in fresh and len(fresh) == 32

    request = RequestFactory().get("/", HTTP_X_REQUEST_ID="req-2026-09-13.0042")
    assert request_id(request) == "req-2026-09-13.0042"


def test_audit_row_records_the_sanitised_request_id(settings):
    settings.TRUSTED_PROXY_COUNT = 0
    from core.db.session import firm_context
    from core.middleware.audit import AuditMiddleware
    from core.models import AuditLog

    firm = create_firm("Firm")
    user = create_user("audit@example.com", PASSWORD)
    membership = add_member(firm, user)
    request = RequestFactory().post(
        "/x/", REMOTE_ADDR="10.0.0.7", HTTP_X_FORWARDED_FOR="1.1.1.1", HTTP_X_REQUEST_ID="bad id!"
    )
    request.user, request.firm, request.membership = user, firm, membership

    from django.http import HttpResponse

    with firm_context(firm.pk):
        AuditMiddleware(lambda r: HttpResponse(status=201))(request)
        row = AuditLog.objects.get()

    assert row.ip_address == "10.0.0.7"
    assert row.request_id != "bad id!"


# ---------------------------------------------------------------------------
# Security headers
# ---------------------------------------------------------------------------


def test_every_response_carries_a_strict_csp():
    response = HttpClient().get("/healthz")
    csp = response["Content-Security-Policy"]
    assert "default-src 'self'" in csp
    assert "frame-ancestors 'none'" in csp
    assert "unsafe-inline" not in csp
    assert response["Permissions-Policy"].startswith("camera=()")
    assert response["X-Content-Type-Options"] == "nosniff"


def test_the_docs_page_gets_the_relaxed_policy_but_still_cannot_be_framed():
    response = HttpClient().get("/api/docs/")  # a redirect to login; the header is still set
    csp = response["Content-Security-Policy"]
    assert "cdn.jsdelivr.net" in csp
    assert "frame-ancestors 'none'" in csp


# ---------------------------------------------------------------------------
# Masking
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "placeholder"),
    [
        ("PAN ABCPD1234E quoted", "<PAN>"),
        ("GSTIN 27ABCPD1234E1Z5 on invoice", "<GSTIN>"),
        ("to a/c 900000000000001 via NEFT", "<ACCT>"),
        ("IFSC UTIB0000123 branch", "<IFSC>"),
        ("call 9876543210 now", "<PHONE>"),
        ("call +91 98765 43210".replace(" ", ""), "<PHONE>"),
        ("aadhaar 2345 6789 0123", "<AADHAAR>"),
        ("CreditCard Payment XX 0000 Ref#GFYPDNWLV474ZO", "<CARD>"),
        ("CRD-PMNT-400000****0000", "<CARD>"),
        ("mail arjun@example.com", "<EMAIL>"),
    ],
)
def test_identifiers_are_replaced_with_typed_placeholders(text, placeholder):
    result = mask(text)
    assert placeholder in result.text
    assert result.removed[placeholder] >= 1


def test_a_gstin_is_masked_whole_not_as_a_pan_with_debris():
    assert mask_text("27ABCPD1234E1Z5") == "<GSTIN>"


def test_what_a_classifier_needs_survives_masking():
    """Channel, payee and remark stay; the reference number goes."""
    narration = "UPI/P2A/100000000003/SURESH KIRAN MENON/Meter/HDFC BANK LTD"
    assert mask_text(narration) == "UPI/P2A/<ACCT>/SURESH KIRAN MENON/Meter/HDFC BANK LTD"


def test_short_numbers_are_left_alone():
    assert mask_text("row 30, Rs 2,500.00 on 26-07-2025") == "row 30, Rs 2,500.00 on 26-07-2025"


def test_log_records_are_masked_before_they_are_written():
    record = logging.LogRecord(
        "autoca.test", logging.INFO, __file__, 1,
        "failed for account %s of %s", ("900000000000001", "ABCPD1234E"), None,
    )
    assert MaskingFilter().filter(record)
    assert record.getMessage() == "failed for account <ACCT> of <PAN>"


def test_the_configured_logging_masks_too(caplog, settings):
    """Not just the class -- the settings actually install it."""
    from logging.config import dictConfig

    dictConfig(settings.LOGGING)
    handler = logging.getLogger().handlers[0]
    assert any(isinstance(f, MaskingFilter) for f in handler.filters)


# ---------------------------------------------------------------------------
# Identifiers
# ---------------------------------------------------------------------------


def test_pan_shape():
    assert is_valid_pan("ABCPD1234E")
    assert not is_valid_pan("ABCXD1234E")  # X is not a holder type
    assert not is_valid_pan("ABCPD1234")


def test_gstin_check_character_matches_gstns_published_example():
    # A widely published worked example of the GSTIN checksum algorithm.
    assert gstin_check_character("27AAPFU0939F1Z") == "V"
    assert is_valid_gstin("27AAPFU0939F1ZV")
    assert not is_valid_gstin("27AAPFU0939F1ZW")  # one character off
    assert not is_valid_gstin("00AAPFU0939F1ZV")  # no such state
