"""Client visibility and sign-off, attacked from every route the API has.

The sweep walks the DRF router registries rather than a hand-written list, so
an endpoint added later without the visibility rule fails here.
"""

from __future__ import annotations

import pytest
from django.urls import NoReverseMatch, reverse

from api import urls as api_urls
from api.tests.conftest import member, sign_in
from banking.models import BankAccount, Statement, StatementTransaction
from classify.models import TransactionClassification
from classify.treatment import ReviewBand
from core.access import can_sign_off, visible_clients
from core.db.session import firm_context
from core.models import ClientAssignment, Role
from ledger.models import JournalEntry

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("fixture_adapters")]
V1 = "/api/v1"


def _outsider(firm, role=Role.STAFF, email="outsider@example.test"):
    m = member(firm, role, email)
    with firm_context(firm.pk):
        m.scope_all_clients = False
        m.save(update_fields=["scope_all_clients"])
    return m


def _assign(client, membership):
    with firm_context(client.firm_id):
        ClientAssignment.objects.create(firm_id=client.firm_id, client=client, membership=membership)


@pytest.fixture
def posted(api, client_record, statement):
    response = api.post(
        f"{V1}/clients/{client_record.pk}/approvals/", {"band": ReviewBand.HIGH}, format="json"
    )
    assert response.status_code == 201
    return client_record


def _list_urls(client_id):
    for prefix, _viewset, basename in api_urls.root.registry:
        try:
            yield prefix, reverse(f"api:{basename}-list")
        except NoReverseMatch:
            continue
    for prefix, _viewset, basename in api_urls.per_client.registry:
        try:
            yield prefix, reverse(f"api:{basename}-list", kwargs={"client_id": client_id})
        except NoReverseMatch:
            continue


def test_every_list_route_is_empty_or_404_for_an_unassigned_member(posted):
    firm = posted.firm
    for role in (Role.STAFF, Role.READ_ONLY, Role.SENIOR_CA):
        http = sign_in(_outsider(firm, role, f"out-{role.lower()}@example.test").user)
        checked = 0
        for prefix, url in _list_urls(posted.pk):
            response = http.get(url)
            checked += 1
            if response.status_code == 404:
                continue
            assert response.status_code == 200, (role, url, response.status_code)
            body = response.json()
            results = body.get("results", body) if isinstance(body, dict) else body
            assert results == [], (role, prefix, url, results[:1])
        assert checked >= 10


def test_every_object_route_is_404_for_an_unassigned_member(posted):
    firm = posted.firm
    http = sign_in(_outsider(firm).user)
    with firm_context(firm.pk):
        entry = JournalEntry.objects.filter(client=posted).first()
        statement = Statement.objects.filter(bank_account__client=posted).first()
        account = BankAccount.objects.filter(client=posted).first()
        row = StatementTransaction.objects.filter(bank_account__client=posted).first()
        classification = TransactionClassification.objects.filter(
            transaction__bank_account__client=posted
        ).first()

    c = posted.pk
    for url in (
        f"{V1}/clients/{c}/",
        f"{V1}/clients/{c}/review-queue/summary/",
        f"{V1}/clients/{c}/reports/trial-balance/",
        f"{V1}/clients/{c}/reports/profit-and-loss/",
        f"{V1}/clients/{c}/reports/balance-sheet/",
        f"{V1}/journal-entries/{entry.pk}/",
        f"{V1}/statements/{statement.pk}/tally-export/",
        f"{V1}/bank-accounts/{account.pk}/reconciliation/?as_of=2025-05-01",
        f"{V1}/transactions/{row.pk}/",
        f"{V1}/classifications/{classification.pk}/",
        f"{V1}/clients/{c}/bank-accounts/{account.pk}/",
        f"{V1}/clients/{c}/statements/{statement.pk}/transactions/",
    ):
        assert http.get(url).status_code == 404, url

    for url, body in (
        (f"{V1}/clients/{c}/approvals/", {"band": ReviewBand.HIGH}),
        (f"{V1}/clients/{c}/review-queue/suggest/", {}),
        (f"{V1}/classifications/{classification.pk}/review/", {"ledger": str(c)}),
        (f"{V1}/journal-entries/{entry.pk}/correct/", {}),
    ):
        assert http.post(url, body, format="json").status_code in {403, 404}, url


def test_assignment_makes_a_client_visible(posted):
    staff = _outsider(posted.firm)
    http = sign_in(staff.user)
    assert http.get(f"{V1}/clients/").json()["results"] == []

    _assign(posted, staff)

    names = [c["name"] for c in http.get(f"{V1}/clients/").json()["results"]]
    assert names == [posted.name]
    assert http.get(f"{V1}/journal-entries/?client={posted.pk}").json()["results"]


def test_a_senior_ca_sees_the_clients_they_lead(client_record):
    ca = _outsider(client_record.firm, Role.SENIOR_CA, "lead@example.test")
    with firm_context(client_record.firm_id):
        assert not visible_clients(ca).exists()
        client_record.lead = ca
        client_record.save(update_fields=["lead"])
        assert list(visible_clients(ca)) == [client_record]


def test_only_the_lead_or_a_firm_admin_signs_off(posted):
    firm = posted.firm
    lead = member(firm, Role.SENIOR_CA, "the-lead@example.test")
    other = member(firm, Role.SENIOR_CA, "other-ca@example.test")  # sees all clients
    admin = member(firm, Role.FIRM_ADMIN, "admin@example.test")
    staff = member(firm, Role.STAFF, "prep@example.test")

    with firm_context(firm.pk):
        assert can_sign_off(other, posted)  # no lead yet: any approver, as before
        posted.lead = lead
        posted.save(update_fields=["lead"])
        assert can_sign_off(lead, posted)
        assert can_sign_off(admin, posted)
        assert not can_sign_off(other, posted)
        assert not can_sign_off(staff, posted)

    # Posting is any assigned CA's; *signing the books off* is the lead's.
    refused = sign_in(other.user).post(f"{V1}/clients/{posted.pk}/books/sign-off/", {}, format="json")
    assert refused.status_code == 403
    assert "lead" in refused.json()["detail"]


def test_sign_off_is_enforced_below_the_view(posted):
    """ledger.approval checks again, for callers that never pass through a view."""
    from django.core.exceptions import PermissionDenied

    from ledger.approval import correct
    from ledger.editing import EntryLockedError

    firm = posted.firm
    lead = member(firm, Role.SENIOR_CA, "the-lead@example.test")
    other = member(firm, Role.SENIOR_CA, "other-ca@example.test")
    with firm_context(firm.pk):
        posted.lead = lead
        posted.save(update_fields=["lead"])
        entry = JournalEntry.objects.filter(client=posted).first()
        # Until sign-off the entry is a draft any CA may change; once signed, only
        # the lead (or a firm admin) may adjust it.
        type(posted).objects.filter(pk=posted.pk).update(signed_off_through=entry.entry_date)
        with pytest.raises(EntryLockedError):
            correct(entry, membership=other, treatment=None)


def test_jobs_are_private_to_whoever_started_them(senior, staff_api, client_record):
    from core.jobs import run_job

    with firm_context(client_record.firm_id):
        run_job(
            firm_id=client_record.firm_id,
            kind="test.job",
            user=senior.user,
            message=f"Work for {client_record.name}",
            work=lambda: {},
        )
    assert staff_api.get(f"{V1}/jobs/").json()["results"] == []
