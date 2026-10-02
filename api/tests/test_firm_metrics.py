"""``GET /api/v1/firm/metrics/``: measured figures from stored data (B9)."""

from __future__ import annotations

import datetime

import pytest
from django.utils import timezone

from api.tests.conftest import member, sign_in
from classify.treatment import ReviewBand
from core.db.session import firm_context
from core.models import Client, ClientAssignment, Role
from core.provisioning import create_client, create_firm
from ledger.models import (
    BooksAction,
    BooksEvent,
    ChangeAction,
    EntryChange,
    EntryMarker,
    JournalEntry,
)

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("fixture_adapters")]

V1 = "/api/v1"
URL = f"{V1}/firm/metrics/"


def _get(http, **params):
    return http.get(URL, params)


def _row(body, client):
    return next(c for c in body["clients"] if c["id"] == str(client.pk))


def _post_all(api, client_record):
    posted = api.post(f"{V1}/clients/{client_record.pk}/approvals/", {"band": ReviewBand.HIGH}, format="json")
    assert posted.status_code == 201
    with firm_context(client_record.firm_id):
        return list(JournalEntry.objects.filter(client=client_record, source_transaction__isnull=False))


def _automate(client_record, entries, how_many):
    chosen = [e.pk for e in entries[:how_many]]
    with firm_context(client_record.firm_id):
        JournalEntry.objects.filter(pk__in=chosen).update(approved_by=None, marker=EntryMarker.AI_POSTED)
    return chosen


def test_an_empty_period_gives_null_ratios_and_zero_counts(api, client_record):
    body = _get(api, **{"from": "2020-01-01", "to": "2020-01-31"}).json()
    assert body["period"] == {"from": "2020-01-01", "to": "2020-01-31"}
    assert body["is_estimate"] is True and body["assumed_minutes_per_row"] == 2
    for figures in (body["firm"], _row(body, client_record)):
        assert figures["rows_posted"] == 0 and figures["rows_automated"] == 0
        assert figures["automation_share"] is None and figures["accuracy"] is None
        assert figures["estimated_minutes_saved"] == 0
    assert body["turnaround"] == []


def test_the_default_period_is_this_month_and_a_reversed_one_is_refused(api, client_record):
    today = timezone.localdate()
    body = _get(api).json()
    assert body["period"] == {"from": str(today.replace(day=1)), "to": str(today)}
    assert _get(api, **{"from": "2026-02-01", "to": "2026-01-01"}).status_code == 400
    assert _get(api, **{"from": "yesterday"}).status_code == 400


def test_automation_share_and_estimated_minutes(api, client_record, statement, settings):
    settings.ASSUMED_MINUTES_PER_ROW = 3
    entries = _post_all(api, client_record)
    assert len(entries) >= 3
    _automate(client_record, entries, 2)

    body = _get(api).json()
    row = _row(body, client_record)
    assert row["rows_posted"] == len(entries)
    assert row["rows_automated"] == 2
    assert row["automation_share"] == round(2 / len(entries), 4)
    assert row["estimated_minutes_saved"] == 6 and body["assumed_minutes_per_row"] == 3
    assert body["firm"]["rows_automated"] == 2 and body["firm"]["clients"] == 1

    outside = _get(api, **{"from": "2020-01-01", "to": "2020-01-31"}).json()
    assert _row(outside, client_record)["rows_posted"] == 0


def test_an_automatic_post_a_person_edited_is_no_longer_automatic(api, client_record, statement, senior):
    entries = _post_all(api, client_record)
    chosen = _automate(client_record, entries, 2)
    with firm_context(client_record.firm_id):
        entry = JournalEntry.objects.get(pk=chosen[0])
        EntryChange.objects.create(
            firm_id=entry.firm_id, client=entry.client, entry_id=entry.pk, voucher_type=entry.voucher_type,
            entry_no=entry.entry_no, entry_date=entry.entry_date, action=ChangeAction.EDITED,
            before={"lines": []}, after={"lines": [{"ledger_id": "x"}]}, actor=senior.user,
        )
    assert _row(_get(api).json(), client_record)["rows_automated"] == 1


def test_accuracy_counts_changed_placements_against(api, client_record, statement):
    entries = _post_all(api, client_record)
    chosen = _automate(client_record, entries, 4)
    first = _row(_get(api).json(), client_record)
    assert first["placements_changed"] == 0
    assert first["placements_stayed"] >= 4
    assert first["accuracy"] == 1.0

    with firm_context(client_record.firm_id):
        entry = JournalEntry.objects.get(pk=chosen[0])
        line = {"ledger_id": "a", "party_id": None, "direction": "DR", "amount_paise": 100}
        EntryChange.objects.create(
            firm_id=entry.firm_id, client=entry.client, entry_id=entry.pk, voucher_type=entry.voucher_type,
            entry_no=entry.entry_no, entry_date=entry.entry_date, action=ChangeAction.AI_REVISED,
            before={"lines": [line]}, after={"lines": [{**line, "ledger_id": "b"}]}, actor=None,
        )
        # Rewording alone leaves the placement standing.
        EntryChange.objects.create(
            firm_id=entry.firm_id, client=entry.client, entry_id=entry.pk, voucher_type=entry.voucher_type,
            entry_no=entry.entry_no, entry_date=entry.entry_date, action=ChangeAction.AI_REVISED,
            before={"lines": [line], "marker": EntryMarker.AI_POSTED.value},
            after={"lines": [line]}, actor=None,
        )
    second = _row(_get(api).json(), client_record)
    assert second["placements_changed"] == 1
    assert second["accuracy"] == round(
        second["placements_stayed"] / (second["placements_stayed"] + 1), 4
    )
    assert second["accuracy"] < 1.0


def test_needs_attention_gives_a_code_and_a_sentence(api, client_record, statement):
    body = _get(api).json()
    codes = {r["code"] for r in _row(body, client_record)["needs_attention"]}
    assert "opening_balance_unconfirmed" in codes

    entries = _post_all(api, client_record)
    _automate(client_record, entries, 1)
    with firm_context(client_record.firm_id):
        latest = max(e.entry_date for e in JournalEntry.objects.filter(client=client_record))
    old = timezone.localdate() - latest
    row = _row(_get(api).json(), client_record)
    reasons = {r["code"]: r["message"] for r in row["needs_attention"]}
    assert "assistant_entries_unchecked" in reasons
    if old.days > 45:
        assert "unsigned_too_long" in reasons
    assert all(isinstance(m, str) and m for m in reasons.values())
    assert _get(api).json()["firm"]["clients_needing_attention"] == 1


def test_a_signed_off_client_with_nothing_wrong_has_no_reasons_for_the_books_it_signed(api, client_record):
    with firm_context(client_record.firm_id):
        Client.objects.filter(pk=client_record.pk).update(signed_off_through=datetime.date(2025, 6, 30))
    assert _row(_get(api).json(), client_record)["needs_attention"] == []


def test_turnaround_is_per_person_and_a_median(api, client_record, senior, staff, firm):
    with firm_context(firm.pk):
        for actor, action in ((staff.user, BooksAction.REQUESTED), (senior.user, BooksAction.SIGNED_OFF)):
            BooksEvent.objects.create(firm=firm, client=client_record, action=action, actor=actor)
    body = _get(api).json()
    assert len(body["turnaround"]) == 1
    person = body["turnaround"][0]
    assert person["member"] == {"id": str(senior.pk), "name": senior.user.email}
    assert person["books_signed_off"] == 1
    assert person["median_days_request_to_sign_off"] == 0.0
    assert person["statements_completed"] == 0 and person["median_days_upload_to_posted"] is None
    assert set(person) == {
        "member", "statements_completed", "median_days_upload_to_posted",
        "books_signed_off", "median_days_request_to_sign_off",
    }

    empty = _get(api, **{"from": "2020-01-01", "to": "2020-01-31"}).json()
    assert empty["turnaround"] == []


def test_a_sign_off_with_no_request_is_not_timed(api, client_record, senior, firm):
    with firm_context(firm.pk):
        BooksEvent.objects.create(firm=firm, client=client_record, action=BooksAction.SIGNED_OFF, actor=senior.user)
    assert _get(api).json()["turnaround"] == []


def test_upload_to_posted_turnaround(api, client_record, statement, senior):
    from classify.models import TransactionClassification
    from documents.models import Document

    with firm_context(client_record.firm_id):
        Document.objects.filter(pk=statement.document_id).update(uploaded_by=senior.user)
    entries = _post_all(api, client_record)
    body = _get(api).json()
    mine = [t for t in body["turnaround"] if t["member"]["id"] == str(senior.pk)]
    assert not mine or mine[0]["statements_completed"] == 0  # rows are still waiting

    with firm_context(client_record.firm_id):
        posted = JournalEntry.objects.filter(source_transaction__isnull=False).values("source_transaction")
        TransactionClassification.objects.filter(transaction__statement=statement).exclude(
            transaction__in=posted
        ).update(mirrored_entry_id=entries[0].pk)
    mine = [t for t in _get(api).json()["turnaround"] if t["member"]["id"] == str(senior.pk)]
    assert mine[0]["statements_completed"] == 1
    assert mine[0]["median_days_upload_to_posted"] is not None


def test_only_firm_admins_and_seniors_may_look(firm, client_record, staff, reader, api):
    assert sign_in(staff.user).get(URL).status_code == 403
    assert sign_in(reader.user).get(URL).status_code == 403
    assert api.get(URL).status_code == 200
    admin = member(firm, Role.FIRM_ADMIN, "mx-admin@example.test")
    assert sign_in(admin.user).get(URL).status_code == 200
    from rest_framework.test import APIClient

    assert APIClient().get(URL).status_code in {401, 403}


def test_a_senior_sees_their_team_and_no_other_firm_appears(firm, client_record, senior):
    theirs = create_client(firm, "Not On My Team", datetime.date(2025, 4, 1))
    with firm_context(firm.pk):
        senior.scope_all_clients = False
        senior.save(update_fields=["scope_all_clients"])
        ClientAssignment.objects.create(firm=firm, client=client_record, membership=senior)
    other_firm = create_firm("Somebody Else")
    outsider_client = create_client(other_firm, "Other Firm Client", datetime.date(2025, 4, 1))
    outsider = member(other_firm, Role.FIRM_ADMIN, "mx-out@example.test")
    admin = member(firm, Role.FIRM_ADMIN, "mx-admin@example.test")

    mine = _get(sign_in(senior.user)).json()
    assert [c["id"] for c in mine["clients"]] == [str(client_record.pk)]
    assert mine["firm"]["clients"] == 1

    everyone = {c["id"] for c in _get(sign_in(admin.user)).json()["clients"]}
    assert everyone == {str(client_record.pk), str(theirs.pk)}
    assert str(outsider_client.pk) not in everyone
    assert [c["id"] for c in _get(sign_in(outsider.user)).json()["clients"]] == [str(outsider_client.pk)]


def test_the_schema_describes_every_figure():
    from drf_spectacular.generators import SchemaGenerator

    schema = SchemaGenerator().get_schema(request=None, public=True)
    operation = schema["paths"]["/api/v1/firm/metrics/"]["get"]
    assert operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith("/FirmMetrics")
    figures = schema["components"]["schemas"]["MetricsClient"]["properties"]
    for name in ("automation_share", "accuracy", "estimated_minutes_saved", "rows_posted", "placements_stayed"):
        assert figures[name]["description"]
    assert "from" in schema["components"]["schemas"]["MetricsPeriod"]["properties"]
