"""Tally import, from the outside: the permission matrix, limits, isolation, the flow and its errors."""

from __future__ import annotations

import datetime

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from rest_framework.test import APIClient

from api.tests.conftest import member, sign_in
from classify.models import LedgerAccount, LedgerGroup
from core.db.session import firm_context
from core.models import AuditLog, Client, Role
from core.provisioning import create_client, create_firm
from ledger.models import LedgerImportRun, LedgerOpening
from ledger.tests.tally_xml import group, ledger, masters_xml

pytestmark = pytest.mark.django_db

V1 = "/api/v1"


def url(client, *tail):
    return f"{V1}/clients/{client.pk}/tally-imports/" + "".join(f"{t}/" for t in tail)


def upload(api, client, data=None, *, name="masters.xml", year=2025, **extra):
    data = data if data is not None else masters_xml(
        [
            ledger("Machinery", "Fixed Assets", "-20000.00"),
            ledger("Capital", "Capital Account", "20000.00"),
            ledger("Rent", "Indirect Expenses"),
        ]
    )
    body = {"file": SimpleUploadedFile(name, data, content_type="text/xml"), "financial_year": year, **extra}
    return api.post(url(client), body, format="multipart")


@pytest.fixture
def admin(firm):
    return member(firm, Role.FIRM_ADMIN, "admin@example.test")


@pytest.fixture
def lead(firm, client_record):
    membership = member(firm, Role.SENIOR_CA, "lead@example.test")
    with firm_context(firm.pk):
        Client.objects.filter(pk=client_record.pk).update(lead=membership)
    return membership


# ---------------------------------------------------------------------------
# The flow
# ---------------------------------------------------------------------------


def test_upload_returns_a_preview_and_changes_nothing(api, firm, client_record):
    response = upload(api, client_record)

    assert response.status_code == 201
    body = response.json()
    assert body["status"] == "PREVIEW" and body["financial_year"] == 2025 and body["result"] is None
    assert [r["action"] for r in body["rows"]] == ["create", "create", "create"]
    machinery = body["rows"][0]
    assert machinery["our_group"] == "FIXED_ASSET" and machinery["opening_paise"] == 2_000_000
    assert machinery["opening_display"] == "₹20,000.00"
    assert body["counts"]["difference_paise"] == 0 and body["counts"]["debit_display"] == "₹20,000.00"
    with firm_context(firm.pk):
        assert not LedgerAccount.objects.filter(client=client_record, name="Machinery").exists()


def test_the_same_upload_is_the_same_preview(api, client_record):
    first, second = upload(api, client_record), upload(api, client_record)
    assert (first.status_code, second.status_code) == (201, 200)
    assert first.json()["id"] == second.json()["id"]


def test_confirm_applies_the_choices_and_is_idempotent(api, firm, client_record):
    with firm_context(firm.pk):
        LedgerAccount.objects.create(firm=firm, client=client_record, name="Rent", group=LedgerGroup.DIRECT_EXPENSE)
    run = upload(api, client_record).json()
    rent = next(r for r in run["rows"] if r["name"] == "Rent")
    assert rent["action"] == "conflict" and rent["conflict"]["kind"] == "group_differs"

    unresolved = api.post(url(client_record, run["id"], "confirm"), {}, format="json")
    assert unresolved.status_code == 409 and unresolved.json()["code"] == "tally_conflicts_unresolved"

    done = api.post(
        url(client_record, run["id"], "confirm"),
        {"resolutions": [{"row": rent["row"], "choice": "take_tally"}]},
        format="json",
    )
    assert done.status_code == 200
    assert done.json()["status"] == "CONFIRMED"
    assert done.json()["result"]["created"] == 2 and done.json()["result"]["openings"] == 2
    assert done.json()["result"]["difference_display"] == "₹0.00"

    again = api.post(url(client_record, run["id"], "confirm"), {}, format="json")
    assert again.status_code == 200 and again.json()["result"] == done.json()["result"]

    with firm_context(firm.pk):
        assert LedgerAccount.objects.get(client=client_record, name="Rent").group == LedgerGroup.INDIRECT_EXPENSE
        assert LedgerOpening.objects.filter(client=client_record).count() == 2

    shown = api.get(url(client_record, run["id"]))
    assert shown.status_code == 200 and shown.json()["status"] == "CONFIRMED"
    listing = api.get(url(client_record)).json()
    assert [r["id"] for r in listing] == [run["id"]] and "rows" not in listing[0]


def test_the_balance_sheet_shows_an_imported_asset_on_the_assets_side(api, firm, client_record):
    run = upload(api, client_record).json()
    resolutions = [{"row": r["row"], "choice": r["conflict"]["default"]} for r in run["rows"] if r["conflict"]]
    api.post(url(client_record, run["id"], "confirm"), {"resolutions": resolutions}, format="json")

    sheet = api.get(f"{V1}/clients/{client_record.pk}/reports/balance-sheet/?fy=2025").json()

    assert [r["name"] for r in sheet["assets"]] == ["Machinery"]
    assert sheet["balances"] is True and sheet["unclassified"] == []


def test_a_confirm_is_in_the_audit_trail_without_the_contents(api, firm, client_record):
    run = upload(api, client_record).json()
    api.post(url(client_record, run["id"], "confirm"), {}, format="json")
    with firm_context(firm.pk):
        paths = list(AuditLog.objects.filter(path__contains="tally-imports").values_list("method", "path"))
    assert ("POST", url(client_record)) in paths
    assert ("POST", url(client_record, run["id"], "confirm")) in paths


# ---------------------------------------------------------------------------
# Who may
# ---------------------------------------------------------------------------


def test_the_permission_matrix(api, staff_api, firm, client_record, admin, lead, reader):
    run = upload(sign_in(admin.user), client_record).json()
    run_url, confirm_url = url(client_record, run["id"]), url(client_record, run["id"], "confirm")

    outcomes = {}
    for label, who in {
        "admin": sign_in(admin.user),
        "lead": sign_in(lead.user),
        "senior_not_lead": api,
        "staff": staff_api,
        "reader": sign_in(reader.user),
    }.items():
        outcomes[label] = (
            who.get(url(client_record)).status_code,
            who.get(run_url).status_code,
            upload(who, client_record).status_code,
            who.post(confirm_url, {"resolutions": []}, format="json").status_code,
        )

    assert outcomes["admin"][:3] == (200, 200, 200)
    # The admin's own confirm (the fourth call above) closed that preview, so the lead's upload of the
    # same file starts a fresh one: 201, not a reuse.
    assert outcomes["lead"][:3] == (200, 200, 201)
    # A senior who is not this client's lead may not change what its books start from.
    assert outcomes["senior_not_lead"][2] == 403 and outcomes["senior_not_lead"][3] == 403
    assert outcomes["staff"] == (403, 403, 403, 403)
    assert outcomes["reader"] == (403, 403, 403, 403)
    with firm_context(firm.pk):
        assert LedgerImportRun.objects.get(pk=run["id"]).status in {"PREVIEW", "CONFIRMED"}


def test_staff_is_told_which_permission_is_missing(staff_api, client_record):
    response = upload(staff_api, client_record)
    assert response.status_code == 403 and "ledger.import" in response.json()["detail"]


def test_a_senior_not_assigned_to_the_client_cannot_even_see_it(firm, client_record):
    scoped = member(firm, Role.SENIOR_CA, "scoped@example.test")
    with firm_context(firm.pk):
        type(scoped).objects.filter(pk=scoped.pk).update(scope_all_clients=False)
    response = upload(sign_in(scoped.user), client_record)
    assert response.status_code == 404 and response.json()["code"] == "not_found"


def test_another_firms_client_is_not_found(api):
    rival = create_firm("Rival Firm")
    theirs = create_client(rival, "Their Client", datetime.date(2025, 4, 1))
    assert upload(api, theirs).status_code == 404
    assert api.get(url(theirs)).status_code == 404


def test_a_run_is_only_reachable_through_its_own_client(api, firm, client_record):
    other = create_client(firm, "Other Client", datetime.date(2025, 4, 1))
    run = upload(api, client_record).json()
    assert api.get(url(other, run["id"])).status_code == 404
    assert api.post(url(other, run["id"], "confirm"), {}, format="json").status_code == 404
    assert api.get(url(other)).json() == []


def test_anonymous_is_refused(client_record):
    assert APIClient().post(url(client_record), {}).status_code in (401, 403)


def test_permissions_in_me_follow_the_role(api, staff_api):
    assert "ledger.import" in api.get(f"{V1}/me/").json()["permissions"]
    assert "ledger.import" not in staff_api.get(f"{V1}/me/").json()["permissions"]


# ---------------------------------------------------------------------------
# Limits and refusals
# ---------------------------------------------------------------------------


def test_a_file_over_the_limit_is_413(api, client_record, settings):
    settings.MAX_TALLY_IMPORT_BYTES = 1000
    response = upload(api, client_record, b"<ENVELOPE>" + b" " * 1500 + b"</ENVELOPE>")
    assert response.status_code == 413 and response.json()["code"] == "tally_file_too_large"


@pytest.mark.parametrize(
    "data, name",
    [
        (b"this is not xml", "masters.xml"),
        (b"%PDF-1.4 binary \x00\x01", "masters.xml"),
        (b"<ENVELOPE><BODY/></ENVELOPE>", "masters.xml"),
        (b'<!DOCTYPE x [<!ENTITY a "aaaa"><!ENTITY b "&a;&a;&a;">]><ENVELOPE>&b;</ENVELOPE>', "masters.xml"),
        (masters_xml([ledger("A", "Capital Account")]), "masters.csv"),
    ],
)
def test_an_unreadable_file_is_422_in_plain_words(api, client_record, data, name):
    response = upload(api, client_record, data, name=name)
    assert response.status_code == 422
    assert response.json()["code"] == "tally_file_unreadable"
    assert response.json()["detail"]


def test_malformed_requests_are_400(api, client_record):
    assert upload(api, client_record, name="masters.exe").status_code == 400
    assert upload(api, client_record, year=1999).status_code == 400
    assert upload(api, client_record, b"").status_code == 400
    assert api.post(url(client_record), {"financial_year": 2025}, format="multipart").status_code == 400


def test_a_file_whose_balances_are_not_at_the_year_start_is_422_unless_chart_only(api, client_record):
    data = masters_xml([ledger("Capital", "Capital Account", "10.00")], books_from="20230401")
    refused = upload(api, client_record, data)
    assert refused.status_code == 422 and refused.json()["code"] == "tally_year_mismatch"
    assert upload(api, client_record, data, include_openings="false").status_code == 201


def test_signed_off_books_refuse_an_import(api, firm, client_record):
    run = upload(api, client_record).json()
    with firm_context(firm.pk):
        Client.objects.filter(pk=client_record.pk).update(signed_off_through=datetime.date(2025, 4, 1))

    confirmed = api.post(url(client_record, run["id"], "confirm"), {}, format="json")
    fresh = upload(api, client_record, masters_xml([ledger("Other", "Capital Account")]))
    for response in (confirmed, fresh):
        assert response.status_code == 409 and response.json()["code"] == "entry_locked"


def test_a_changed_chart_makes_the_preview_stale(api, firm, client_record):
    run = upload(api, client_record).json()
    with firm_context(firm.pk):
        LedgerAccount.objects.create(firm=firm, client=client_record, name="Added", group=LedgerGroup.CAPITAL)
    response = api.post(url(client_record, run["id"], "confirm"), {}, format="json")
    assert response.status_code == 409 and response.json()["code"] == "tally_run_stale"


def test_a_resolution_for_a_line_that_does_not_exist_is_400(api, client_record):
    run = upload(api, client_record).json()
    response = api.post(
        url(client_record, run["id"], "confirm"), {"resolutions": [{"row": 99, "choice": "skip"}]}, format="json"
    )
    assert response.status_code == 400 and response.json()["code"] == "invalid"


def test_a_group_of_the_firms_own_is_resolved_with_one_of_ours(api, firm, client_record):
    data = masters_xml([ledger("Odd", "Mine", "-5.00")], [group("Mine", "Primary")])
    run = upload(api, client_record, data).json()
    assert run["rows"][0]["action"] == "needs_group" and run["rows"][0]["our_group"] is None

    done = api.post(
        url(client_record, run["id"], "confirm"),
        {"resolutions": [{"row": 0, "choice": "group", "group": "DEPOSIT"}]},
        format="json",
    )
    assert done.status_code == 200
    with firm_context(firm.pk):
        assert LedgerAccount.objects.get(client=client_record, name="Odd").group == LedgerGroup.DEPOSIT


def test_the_old_export_route_is_gone(api, client_record):
    assert api.get(f"{V1}/statements/{client_record.pk}/tally-export/").status_code == 404
