"""The reporting dashboards: the firm portfolio and one client's snapshot."""

from __future__ import annotations

import datetime

import pytest

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("fixture_adapters")]

V1 = "/api/v1"
PORTFOLIO = f"{V1}/firm/portfolio/"


def snapshot_url(client_record):
    return f"{V1}/clients/{client_record.pk}/dashboard/"


def test_a_new_client_has_a_portfolio_row_and_nothing_flagged(api, client_record):
    response = api.get(PORTFOLIO)

    assert response.status_code == 200, response.content
    body = response.json()
    (row,) = body["clients"]
    assert row["id"] == str(client_record.pk) and row["detail"] is True
    assert row["open_items"] == 0 and row["tds_overdue_paise"] == 0
    # A client with no entries owes no sealing, so the schedule must not flag it.
    assert row["seal_due"] is None
    assert body["attention"] == [] and body["detailed"] is True


def test_rows_waiting_in_review_are_flagged_for_the_client(api, client_record, statement):
    body = api.get(PORTFOLIO).json()

    kinds = {(a["kind"], a["client"]) for a in body["attention"]}
    assert ("review", str(client_record.pk)) in kinds
    # The row figures are the same ones the firm overview gives.
    overview = api.get(f"{V1}/firm/overview/").json()["clients"][0]
    assert body["clients"][0]["unresolved"] == overview["unresolved"]


def test_the_most_serious_attention_comes_first(api, client_record, statement):
    severities = [a["severity"] for a in api.get(PORTFOLIO).json()["attention"]]

    assert severities == sorted(severities, key={"critical": 0, "high": 1, "medium": 2}.get)


def test_the_snapshot_for_a_new_client_is_empty_but_complete(api, client_record):
    response = api.get(snapshot_url(client_record), {"fy": 2025})

    assert response.status_code == 200, response.content
    body = response.json()
    assert body["financial_year"] == 2025
    assert [m["month"] for m in body["trend"]][0] == "2025-04" and len(body["trend"]) == 12
    assert body["income_paise"] == 0 and body["profit_paise"] == 0 and body["top_expenses"] == []
    assert (
        body["owed"]["receivables"]["total_paise"] == 0
        and body["owed"]["payables"]["total_paise"] == 0
    )
    assert body["books"]["signed_off_through"] is None


def test_the_snapshot_lists_a_bank_account_with_its_ledger_balance(api, client_record, statement):
    body = api.get(snapshot_url(client_record), {"fy": 2025}).json()

    assert len(body["accounts"]) == 1
    assert body["accounts"][0]["balance_display"].startswith(("₹", "-₹"))


def test_a_bad_year_says_what_to_send(api, client_record):
    response = api.get(snapshot_url(client_record), {"fy": "abc"})

    assert response.status_code == 400 and "fy" in response.json()["fields"]
    assert api.get(snapshot_url(client_record), {"fy": 1850}).status_code == 400


def test_staff_can_read_both(client_record, staff_api):
    assert staff_api.get(PORTFOLIO).status_code == 200
    assert staff_api.get(snapshot_url(client_record)).status_code == 200


def test_another_firms_client_is_not_found(api, client_record):
    from core.provisioning import create_client, create_firm

    stranger = create_client(create_firm("Other Firm"), "Stranger Ltd", datetime.date(2025, 4, 1))

    assert api.get(snapshot_url(stranger)).status_code == 404


def test_amounts_are_left_out_for_a_caller_without_journal_view(api, client_record, monkeypatch):
    from api.views import dashboard as view

    monkeypatch.setattr(view, "has_permission", lambda membership, name: name != "journal.view")
    (row,) = api.get(PORTFOLIO).json()["clients"]

    assert (
        "receivables_paise" not in row
        and "payables_paise" not in row
        and "tds_overdue_paise" not in row
    )


# ---------------------------------------------------------------------------
# Health, readiness to seal, the money roll-up, prior year, reports ready
# ---------------------------------------------------------------------------


def _row(http):
    (row,) = http.get(PORTFOLIO).json()["clients"]
    return row


def test_a_new_client_is_on_track_with_nothing_to_seal_or_approve(api, client_record):
    row = _row(api)

    assert row["health"] == "on_track"
    assert row["ready_to_seal"] is False and row["oldest_pending_approval_days"] is None


def test_a_sealing_date_that_has_passed_makes_a_client_at_risk(api, senior, client_record):
    from api.tests.work_support import post_entry

    post_entry(client_record, by=senior)

    row = _row(api)

    assert row["seal_due"] is not None and row["health"] == "at_risk"


def test_ready_to_seal_needs_an_approval_that_still_stands(api, senior, client_record):
    from api.tests.work_support import post_entry
    from core.db.session import firm_context
    from ledger.models import BooksAction, BooksEvent

    post_entry(client_record, by=senior)
    assert _row(api)["ready_to_seal"] is False

    with firm_context(client_record.firm_id):
        BooksEvent.objects.create(
            firm=client_record.firm,
            client=client_record,
            action=BooksAction.APPROVED,
            through_date=datetime.date.today(),
            actor=senior.user,
        )
    assert _row(api)["ready_to_seal"] is True

    post_entry(client_record, by=senior)  # a change after the approval
    assert _row(api)["ready_to_seal"] is False


def test_the_age_of_an_open_request_is_in_days(api, senior, client_record):
    from django.utils import timezone

    from core.db.session import firm_context
    from ledger.models import BooksAction, BooksEvent

    asked = timezone.now() - datetime.timedelta(days=5)
    with firm_context(client_record.firm_id):
        BooksEvent.objects.create(
            firm=client_record.firm,
            client=client_record,
            action=BooksAction.REQUESTED,
            actor=senior.user,
            created_at=asked,
        )

    expected = (datetime.date.today() - timezone.localtime(asked).date()).days
    assert _row(api)["oldest_pending_approval_days"] == expected

    with firm_context(client_record.firm_id):
        BooksEvent.objects.create(
            firm=client_record.firm,
            client=client_record,
            action=BooksAction.RETURNED,
            actor=senior.user,
            note="fix this",
        )
    assert _row(api)["oldest_pending_approval_days"] is None


def _owed(api, firm, name, receivable, payable=0):
    from api.tests.test_bills import make_ledger, make_party, post_bill, voucher
    from core.provisioning import create_client

    client = create_client(firm, name, datetime.date(2025, 4, 1))
    for amount, kind, role, group, ledger_name, party_name in (
        (receivable, "SALES", "CUSTOMER", "SALES", "Sales", "Buyer"),
        (payable, "PURCHASE", "VENDOR", "PURCHASE", "Purchases", "Seller"),
    ):
        if not amount:
            continue
        party = make_party(api, client, party_name, role=role, gstin="")
        ledger = make_ledger(api, client, ledger_name, group)
        response = post_bill(
            api,
            client,
            voucher(
                party,
                ledger,
                kind=kind,
                reference=f"{name}-{kind}",
                bill_date="2025-04-01",
                cgst_paise=0,
                sgst_paise=0,
                heads=[{"ledger": ledger["id"], "amount_paise": amount}],
            ),
        )
        assert response.status_code == 201, response.content
    return client


def test_the_portfolio_adds_up_what_clients_are_owed_and_owe(api, firm):
    amounts = [100_00, 600_00, 300_00, 500_00, 200_00, 400_00]
    clients = [
        _owed(api, firm, f"Owed {n}", amount, payable=50_00) for n, amount in enumerate(amounts)
    ]

    body = api.get(PORTFOLIO).json()

    assert body["receivables_total_paise"] == sum(amounts)
    assert body["receivables_total_display"].startswith("₹")
    assert body["payables_total_paise"] == 50_00 * len(amounts)
    assert [b["bucket"] for b in body["aging"]["receivables"]] == [
        "0-30",
        "31-60",
        "61-90",
        "Over 90",
    ]
    # Bills from April 2025 are long past 90 days.
    over_90 = {b["bucket"]: b["amount_paise"] for b in body["aging"]["receivables"]}["Over 90"]
    assert over_90 == sum(amounts)
    assert sum(b["amount_paise"] for b in body["aging"]["payables"]) == 50_00 * len(amounts)
    top = body["top_receivables"]
    assert [t["amount_paise"] for t in top] == [600_00, 500_00, 400_00, 300_00, 200_00]
    assert top[0]["client"] == str(clients[1].pk) and top[0]["client_name"] == "Owed 1"


def test_the_money_roll_up_is_left_out_without_journal_view(api, client_record, monkeypatch):
    from api.views import dashboard as view

    monkeypatch.setattr(view, "has_permission", lambda membership, name: name != "journal.view")
    body = api.get(PORTFOLIO).json()

    for key in ("receivables_total_paise", "payables_total_paise", "aging", "top_receivables"):
        assert key not in body
    assert body["clients"][0]["health"] in ("on_track", "at_risk")  # not money, so still there


def test_prior_year_figures_are_null_until_the_year_before_has_postings(api, senior, client_record):
    from api.tests.work_support import post_entry

    post_entry(client_record, by=senior)  # 10 May 2025: financial year 2025, 100.00 of income

    this_year = api.get(snapshot_url(client_record), {"fy": 2026}).json()
    assert this_year["prior_income_paise"] == 100_00 and this_year["prior_expense_paise"] == 0
    assert this_year["prior_income_display"] == "₹100.00"
    first_year = api.get(snapshot_url(client_record), {"fy": 2025}).json()
    assert first_year["prior_income_paise"] is None and first_year["prior_expense_paise"] is None
    assert first_year["prior_income_display"] is None


REPORT_KEYS = ["pnl", "balance_sheet", "trial_balance", "receivables", "payables", "tds", "gst"]


def test_no_report_is_ready_before_anything_is_posted(api, client_record):
    reports = api.get(snapshot_url(client_record)).json()["reports_ready"]

    assert [r["key"] for r in reports] == REPORT_KEYS
    assert all(
        r["ready"] is False and r["reason"] == "Nothing has been posted yet." for r in reports
    )
    assert all(r["label"] for r in reports)


def test_reports_are_ready_once_posted_and_nothing_stands_in_the_way(api, senior, client_record):
    from api.tests.work_support import post_entry

    post_entry(client_record, by=senior)

    reports = api.get(snapshot_url(client_record)).json()["reports_ready"]

    assert all(r["ready"] is True and r["reason"] is None for r in reports)


def test_rows_still_waiting_make_the_reports_not_ready_and_say_so(
    api, senior, client_record, statement
):
    from api.tests.work_support import post_entry

    post_entry(client_record, by=senior)

    body = api.get(snapshot_url(client_record)).json()
    reports = {r["key"]: r for r in body["reports_ready"]}

    assert reports["pnl"]["ready"] is False and "need a decision" in reports["pnl"]["reason"]


def test_missing_statement_months_are_named_in_plain_words(client_record, senior):
    from api.tests.work_support import post_entry
    from core.db.session import firm_context
    from ledger import close, dashboard

    post_entry(client_record, by=senior)
    with firm_context(client_record.firm_id):
        report = close.close_report(client_record)
        two = dashboard.reports_ready(client_record, report, ["2025-06", "2025-07"])
        one = dashboard.reports_ready(client_record, report, ["2025-06"])

    assert {r["reason"] for r in two} == {"2 months of statements are missing."}
    assert {r["reason"] for r in one} == {"1 month of statements is missing."}
