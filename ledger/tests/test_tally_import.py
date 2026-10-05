"""Staging and applying a Tally import: classification, choices, idempotence, locks, isolation."""

from __future__ import annotations

import datetime

import pytest
from django.db import connection, transaction
from django.db.utils import IntegrityError

from banking.models import BankAccount
from classify.models import LedgerAccount, LedgerGroup, LedgerStatus
from core.db.session import firm_context
from core.models import Client, FirmMembership, Role, User
from core.provisioning import create_client, create_firm
from ledger.editing import EntryLockedError
from ledger.models import ImportStatus, JournalLine, LedgerImportRun, LedgerOpening
from ledger.reports import trial_balance
from ledger.tally_import import (
    TallyConflictsUnresolvedError,
    TallyRunStaleError,
    TallyYearMismatchError,
    confirm_run,
    stage_upload,
)
from ledger.tally_parse import TallyParseError
from ledger.tests.support import make_ledger, post
from ledger.tests.tally_xml import group, ledger, masters_xml

pytestmark = pytest.mark.django_db

FY = 2025
START = datetime.date(2025, 4, 1)


def member(firm, role, email):
    user = User.objects.create_user(email=email, password="correct-horse-battery")
    with firm_context(firm.pk):
        return FirmMembership.objects.create(firm=firm, user=user, role=role)


@pytest.fixture
def firm():
    return create_firm("Import Firm")


@pytest.fixture
def client(firm):
    return create_client(firm, "Import Client", START)


@pytest.fixture
def senior(firm, client):
    membership = member(firm, Role.SENIOR_CA, "lead@example.test")
    with firm_context(firm.pk):
        Client.objects.filter(pk=client.pk).update(lead=membership)
    client.lead = membership
    return membership


@pytest.fixture
def ctx(firm, client, senior):
    with firm_context(firm.pk):
        yield


def stage(client, senior, data, *, fy=FY, name="masters.xml", **kw):
    return stage_upload(client, senior, senior.user, data=data, filename=name, financial_year=fy, **kw)


def confirm(run, senior, resolutions=()):
    return confirm_run(run, senior, senior.user, list(resolutions))


def row(run, name):
    return next(r for r in run.rows if r["name"] == name)


def rich_file(**kw):
    return masters_xml(
        [
            ledger("Sharma Traders", "Sundry Debtors", "-5000.00"),
            ledger("Rent", "Indirect Expenses"),
            ledger("office supplies", "Indirect Expenses", "250.00"),
            ledger("Telephone", "Direct Expenses"),
            ledger("Cash-in-Hand", "Cash-in-Hand", "-1000.00"),
            ledger("Suspense A/c", "Suspense A/c"),
            ledger("Profit & Loss A/c", "Primary", "7000.00"),
            ledger("Machinery", "Plant", "-20000.00"),
            ledger("Odd", "Mine"),
            ledger("SHARMA  traders", "Sundry Debtors", "-1.00"),
            ledger("=2+2", "Indirect Expenses"),
        ],
        [group("Plant", "Fixed Assets"), group("Mine", "Primary")],
        **kw,
    )


@pytest.fixture
def chart(client, ctx):
    return {
        "Rent": make_ledger(client, "Rent", LedgerGroup.INDIRECT_EXPENSE),
        "Office Supplies": make_ledger(client, "Office Supplies", LedgerGroup.INDIRECT_EXPENSE),
        "Telephone": make_ledger(client, "Telephone", LedgerGroup.INDIRECT_EXPENSE),
        "Cash": make_ledger(client, "Cash-in-Hand", LedgerGroup.CASH),
    }


# ---------------------------------------------------------------------------
# The preview
# ---------------------------------------------------------------------------


def test_the_preview_classifies_every_line_and_writes_nothing_else(client, senior, chart):
    before = LedgerAccount.objects.filter(client=client).count()
    run, reused = stage(client, senior, rich_file())

    assert not reused
    assert run.status == ImportStatus.PREVIEW
    assert LedgerAccount.objects.filter(client=client).count() == before
    assert not LedgerOpening.objects.filter(client=client).exists()

    assert row(run, "Sharma Traders")["action"] == "create"
    assert row(run, "Sharma Traders")["our_group"] == LedgerGroup.DEBTOR
    assert row(run, "Sharma Traders")["opening_paise"] == 500_000
    assert row(run, "Rent")["action"] == "match"
    assert row(run, "Machinery")["action"] == "create"
    assert row(run, "Machinery")["our_group"] == LedgerGroup.FIXED_ASSET
    assert row(run, "Machinery")["tally_group_path"] == "Plant > Fixed Assets"

    variant = row(run, "office supplies")
    assert variant["action"] == "conflict" and variant["conflict"]["kind"] == "name_variant"
    assert variant["ledger_name"] == "Office Supplies"
    assert variant["conflict"]["default"] == "keep_ours"

    regroup = row(run, "Telephone")
    assert regroup["conflict"]["kind"] == "group_differs"
    assert regroup["conflict"]["choices"] == ["keep_ours", "take_tally", "skip"]

    cash = row(run, "Cash-in-Hand")
    assert cash["action"] == "match" and cash["opening_paise"] == 100_000

    assert row(run, "Suspense A/c")["action"] == "skipped"
    assert "keeps for itself" in row(run, "Suspense A/c")["reason"]
    assert row(run, "Profit & Loss A/c")["action"] == "skipped"

    unknown = row(run, "Odd")
    assert unknown["action"] == "needs_group" and unknown["our_group"] is None

    duplicate = row(run, "SHARMA traders")
    assert duplicate["action"] == "conflict" and duplicate["conflict"]["kind"] == "duplicate_in_file"
    assert duplicate["conflict"]["pair_row"] == row(run, "Sharma Traders")["row"]
    assert duplicate["conflict"]["choices"] == ["skip", "use_this_spelling"]

    skipped = [r for r in run.rows if r["action"] == "skipped" and "formula" in r["reason"]]
    assert len(skipped) == 1

    assert run.counts["create"] == 2 and run.counts["match"] == 2
    assert run.counts["conflict"] == 3 and run.counts["needs_group"] == 1
    assert run.counts["difference_paise"] == run.counts["debit_paise"] - run.counts["credit_paise"]


def test_only_names_groups_and_amounts_are_staged(client, senior, ctx):
    run, _ = stage(client, senior, rich_file())
    keys = set().union(*(r.keys() for r in run.rows))
    assert keys <= {
        "row", "ordinal", "name", "alias", "tally_group", "tally_group_path", "our_group", "opening_paise",
        "action", "reason", "ledger_id", "ledger_name", "ledger_group", "posted_lines", "conflict", "bank", "inner",
    }


def test_the_same_file_for_the_same_year_is_the_same_preview(client, senior, ctx):
    data = rich_file()
    first, _ = stage(client, senior, data)
    second, reused = stage(client, senior, data)

    assert reused and second.pk == first.pk
    assert LedgerImportRun.objects.filter(client=client).count() == 1
    other_year, reused = stage(client, senior, data, fy=2026)
    assert not reused and other_year.pk != first.pk


def test_a_file_whose_balances_are_not_at_the_year_start_is_refused_unless_chart_only(client, senior, ctx):
    data = rich_file(books_from="20230401")
    with pytest.raises(TallyYearMismatchError, match="01-04-2025"):
        stage(client, senior, data)
    run, _ = stage(client, senior, data, include_openings=False)
    assert run.counts["difference_paise"] == 0
    assert stage(client, senior, rich_file(books_from="20250401"))[0].books_from == START


def test_an_unreadable_file_is_refused_in_the_service(client, senior, ctx):
    with pytest.raises(TallyParseError):
        stage(client, senior, b"not a tally file at all", name="x.xml")


# ---------------------------------------------------------------------------
# Confirming
# ---------------------------------------------------------------------------


def resolve_all(run):
    out = []
    for r in run.rows:
        conflict = r["conflict"]
        if r["action"] == "needs_group":
            out.append({"row": r["row"], "choice": "group", "group": LedgerGroup.CURRENT_ASSET})
        elif r["action"] == "conflict":
            out.append({"row": r["row"], "choice": conflict["default"]})
    return out


def test_nothing_is_applied_while_a_conflict_is_unresolved(client, senior, chart):
    run, _ = stage(client, senior, rich_file())

    with pytest.raises(TallyConflictsUnresolvedError) as caught:
        confirm(run, senior)
    assert len(caught.value.rows) == 4

    assert not LedgerAccount.objects.filter(client=client, name="Machinery").exists()
    assert not LedgerOpening.objects.filter(client=client).exists()
    assert LedgerImportRun.objects.get(pk=run.pk).status == ImportStatus.PREVIEW


def test_confirm_applies_exactly_what_was_chosen(client, senior, chart):
    run, _ = stage(client, senior, rich_file())
    run = confirm(run, senior, resolve_all(run))

    assert run.status == ImportStatus.CONFIRMED and run.confirmed_by == senior.user
    names = set(LedgerAccount.objects.filter(client=client).values_list("name", flat=True))
    assert {"Sharma Traders", "Machinery", "Odd"} <= names
    assert "office supplies" not in names and "SHARMA traders" not in names
    assert LedgerAccount.objects.get(client=client, name="Machinery").group == LedgerGroup.FIXED_ASSET
    assert LedgerAccount.objects.get(client=client, name="Odd").group == LedgerGroup.CURRENT_ASSET
    assert LedgerAccount.objects.get(client=client, name="Telephone").group == LedgerGroup.INDIRECT_EXPENSE
    assert not LedgerAccount.objects.filter(client=client, name="Suspense A/c").exists()

    sharma = LedgerAccount.objects.get(client=client, name="Sharma Traders")
    assert sharma.tally_name == "Sharma Traders" and sharma.tally_group_path == "Sundry Debtors"

    openings = {o.ledger.name: o.signed_paise for o in LedgerOpening.objects.filter(client=client)}
    assert openings == {
        "Sharma Traders": 500_000,
        "Machinery": 2_000_000,
        "Cash-in-Hand": 100_000,
        "Office Supplies": -25_000,
    }
    assert run.result["created"] == 3 and run.result["matched"] == 4 and run.result["openings"] == 4
    assert run.result["skipped"] == 4
    assert run.result["debit_paise"] == 2_600_000 and run.result["credit_paise"] == 25_000
    assert run.result["difference_paise"] == 2_575_000


def test_confirming_again_changes_nothing(client, senior, chart):
    run, _ = stage(client, senior, rich_file())
    resolutions = resolve_all(run)
    first = confirm(run, senior, resolutions)
    ledgers, openings = LedgerAccount.objects.count(), LedgerOpening.objects.count()
    result = dict(first.result)

    again = confirm(run, senior, resolutions)

    assert again.pk == first.pk and again.result == result
    assert (LedgerAccount.objects.count(), LedgerOpening.objects.count()) == (ledgers, openings)
    # And uploading the file afresh afterwards still creates nothing new.
    fresh, _ = stage(client, senior, rich_file())
    fresh = confirm(fresh, senior, resolve_all(fresh))
    assert (LedgerAccount.objects.count(), LedgerOpening.objects.count()) == (ledgers, openings)
    assert fresh.result["created"] == 0


def test_a_second_import_replaces_the_openings_it_covers(client, senior, ctx):
    first, _ = stage(client, senior, masters_xml([ledger("Capital", "Capital Account", "10000.00")]))
    confirm(first, senior)
    second, _ = stage(client, senior, masters_xml([ledger("Capital", "Capital Account", "12000.00")]))
    confirm(second, senior)
    assert LedgerOpening.objects.get(client=client).signed_paise == -1_200_000

    third, _ = stage(client, senior, masters_xml([ledger("Capital", "Capital Account", "0")]))
    confirm(third, senior)
    assert not LedgerOpening.objects.filter(client=client).exists()


def test_chart_only_creates_ledgers_and_no_openings(client, senior, ctx):
    run, _ = stage(client, senior, rich_file(), include_openings=False)
    run = confirm(run, senior, resolve_all(run))
    assert LedgerAccount.objects.filter(client=client, name="Machinery").exists()
    assert not LedgerOpening.objects.filter(client=client).exists()
    assert run.result["openings"] == 0


def test_a_proposed_ledger_the_file_names_becomes_a_normal_one(client, senior, ctx):
    proposed = make_ledger(client, "Machinery", LedgerGroup.FIXED_ASSET)
    LedgerAccount.objects.filter(pk=proposed.pk).update(status=LedgerStatus.PROPOSED)
    run, _ = stage(client, senior, masters_xml([ledger("Machinery", "Fixed Assets")]))
    confirm(run, senior)
    assert LedgerAccount.objects.get(pk=proposed.pk).status == LedgerStatus.ACTIVE


def test_a_chart_changed_since_the_preview_makes_it_stale(client, senior, chart):
    run, _ = stage(client, senior, rich_file())
    make_ledger(client, "Added meanwhile", LedgerGroup.INDIRECT_EXPENSE)
    with pytest.raises(TallyRunStaleError):
        confirm(run, senior, resolve_all(run))


def test_an_expired_preview_cannot_be_confirmed(client, senior, ctx):
    run, _ = stage(client, senior, masters_xml([ledger("Capital", "Capital Account", "10.00")]))
    LedgerImportRun.objects.filter(pk=run.pk).update(expires_at=datetime.datetime(2020, 1, 1, tzinfo=datetime.UTC))
    with pytest.raises(TallyRunStaleError):
        confirm(run, senior)


# ---------------------------------------------------------------------------
# Choices on conflicts
# ---------------------------------------------------------------------------


def test_take_tallys_group_moves_a_ledger_with_no_postings(client, senior, chart):
    run, _ = stage(client, senior, masters_xml([ledger("Telephone", "Direct Expenses")]))
    confirm(run, senior, [{"row": 0, "choice": "take_tally"}])
    assert LedgerAccount.objects.get(client=client, name="Telephone").group == LedgerGroup.DIRECT_EXPENSE


def test_a_ledger_with_posted_lines_cannot_change_group(client, senior, chart):
    post(client, datetime.date(2025, 6, 1), chart["Telephone"], chart["Cash"], 100_00)
    run, _ = stage(client, senior, masters_xml([ledger("Telephone", "Direct Expenses")]))
    assert run.rows[0]["posted_lines"] == 1
    assert run.rows[0]["conflict"]["choices"] == ["keep_ours", "skip"]

    with pytest.raises(Exception, match="not an option"):
        confirm(run, senior, [{"row": 0, "choice": "take_tally"}])
    assert LedgerAccount.objects.get(client=client, name="Telephone").group == LedgerGroup.INDIRECT_EXPENSE


def test_a_choice_that_is_not_offered_is_refused(client, senior, chart):
    run, _ = stage(client, senior, masters_xml([ledger("Rent", "Indirect Expenses")]))
    with pytest.raises(Exception, match="not an option"):
        confirm(run, senior, [{"row": 0, "choice": "take_tally"}])
    with pytest.raises(Exception, match="no line"):
        confirm(run, senior, [{"row": 9, "choice": "skip"}])


def test_renaming_to_tallys_spelling_moves_the_entries_with_it(client, senior, chart):
    post(client, datetime.date(2025, 6, 1), chart["Office Supplies"], chart["Cash"], 100_00)
    run, _ = stage(client, senior, masters_xml([ledger("office supplies", "Indirect Expenses")]))
    confirm(run, senior, [{"row": 0, "choice": "use_tally_name"}])

    renamed = LedgerAccount.objects.get(pk=chart["Office Supplies"].pk)
    assert renamed.name == "office supplies"
    assert JournalLine.objects.filter(ledger_account=renamed).count() == 1


def test_an_exact_spelling_in_our_chart_wins_over_a_look_alike(client, senior, chart):
    make_ledger(client, "office supplies", LedgerGroup.INDIRECT_EXPENSE)
    run, _ = stage(client, senior, masters_xml([ledger("office supplies", "Indirect Expenses")]))
    assert run.rows[0]["action"] == "match" and run.rows[0]["ledger_name"] == "office supplies"


def test_a_bank_ledger_renamed_by_the_import_keeps_its_account(client, senior, ctx):
    account = BankAccount(firm_id=client.firm_id, client=client, bank_code="AXIS", ledger_name="HDFC bank")
    account.set_account_number("12345678901")
    account.save()
    make_ledger(client, "HDFC bank", LedgerGroup.BANK)
    run, _ = stage(client, senior, masters_xml([ledger("HDFC Bank", "Bank Accounts")]))
    confirm(run, senior, [{"row": 0, "choice": "use_tally_name"}])

    account.refresh_from_db()
    assert account.ledger_name == "HDFC Bank"
    assert account.opening_balance_paise is None
    assert LedgerAccount.objects.filter(client=client, name="HDFC Bank", group=LedgerGroup.BANK).count() == 1


def test_which_spelling_survives_when_the_file_has_two(client, senior, ctx):
    data = masters_xml([ledger("Rent A", "Indirect Expenses", "1.00"), ledger("rent  a", "Indirect Expenses", "2.00")])
    run, _ = stage(client, senior, data)
    assert [r["action"] for r in run.rows] == ["create", "conflict"]
    confirm(run, senior, [{"row": 1, "choice": "use_this_spelling"}])

    assert list(LedgerAccount.objects.filter(client=client).values_list("name", flat=True)) == ["rent a"]
    assert LedgerOpening.objects.get(client=client).signed_paise == -200

    again, _ = stage(client, senior, data)
    assert again.pk != run.pk
    confirm(again, senior, [{"row": 0, "choice": "keep_ours"}, {"row": 1, "choice": "skip"}])
    assert LedgerAccount.objects.filter(client=client).count() == 1


def test_a_group_of_the_firms_own_needs_one_of_ours(client, senior, ctx):
    run, _ = stage(client, senior, masters_xml([ledger("Odd", "Mine")], [group("Mine", "Primary")]))
    with pytest.raises(Exception, match="one of our groups"):
        confirm(run, senior, [{"row": 0, "choice": "group", "group": "NOT_A_GROUP"}])
    confirm(run, senior, [{"row": 0, "choice": "skip"}])
    assert not LedgerAccount.objects.filter(client=client, name="Odd").exists()


# ---------------------------------------------------------------------------
# The bank account is the source of its own opening
# ---------------------------------------------------------------------------


def bank(client, name="HDFC Bank", opening=None):
    account = BankAccount(firm_id=client.firm_id, client=client, bank_code="HDFC", ledger_name=name)
    account.set_account_number("98765432101")
    account.opening_balance_paise = opening
    account.opening_as_of = START if opening is not None else None
    account.save()
    make_ledger(client, name, LedgerGroup.BANK)
    return account


def test_a_bank_without_an_opening_is_given_tallys_and_the_ledger_stores_none(client, senior, ctx):
    account = bank(client)
    run, _ = stage(client, senior, masters_xml([ledger("HDFC Bank", "Bank Accounts", "-50000.00")]))
    assert run.rows[0]["bank"]["status"] == "propose"

    run = confirm(run, senior)

    account.refresh_from_db()
    assert account.opening_balance_paise == 5_000_000 and account.opening_as_of == START
    assert not LedgerOpening.objects.filter(client=client).exists()
    assert run.result["bank_openings"] == 1


def test_two_different_bank_openings_need_a_choice(client, senior, ctx):
    account = bank(client, opening=4_000_000)
    data = masters_xml([ledger("HDFC Bank", "Bank Accounts", "-50000.00")])
    run, _ = stage(client, senior, data)
    assert run.rows[0]["bank"]["status"] == "conflict"
    assert run.rows[0]["bank"]["ours_paise"] == 4_000_000 and run.rows[0]["bank"]["tally_paise"] == 5_000_000
    assert run.counts["bank_conflicts"] == 1

    with pytest.raises(TallyConflictsUnresolvedError):
        confirm(run, senior)
    confirm(run, senior, [{"row": 0, "bank": "keep_bank"}])
    account.refresh_from_db()
    assert account.opening_balance_paise == 4_000_000
    assert not LedgerOpening.objects.exists()

    again, _ = stage(client, senior, data)
    confirm(again, senior, [{"row": 0, "bank": "use_tally"}])
    account.refresh_from_db()
    assert account.opening_balance_paise == 5_000_000


def test_agreeing_bank_openings_need_nothing(client, senior, ctx):
    bank(client, opening=5_000_000)
    run, _ = stage(client, senior, masters_xml([ledger("HDFC Bank", "Bank Accounts", "-50000.00")]))
    assert run.rows[0]["bank"]["status"] == "agree"
    confirm(run, senior)
    assert not LedgerOpening.objects.exists()


# ---------------------------------------------------------------------------
# Locks and rights
# ---------------------------------------------------------------------------


def sign_off_through(client, date):
    Client.objects.filter(pk=client.pk).update(signed_off_through=date)


def test_a_client_signed_off_through_the_year_start_is_refused(client, senior, ctx):
    data = masters_xml([ledger("Capital", "Capital Account", "10.00")])
    run, _ = stage(client, senior, data)
    sign_off_through(client, START)

    with pytest.raises(EntryLockedError, match="signed off through 01-04-2025"):
        confirm(run, senior)
    with pytest.raises(EntryLockedError):
        stage(client, senior, masters_xml([ledger("Other", "Capital Account", "10.00")]))
    assert not LedgerOpening.objects.exists()


def test_signing_off_before_the_year_start_does_not_stop_the_import(client, senior, ctx):
    sign_off_through(client, datetime.date(2025, 3, 31))
    run, _ = stage(client, senior, masters_xml([ledger("Capital", "Capital Account", "10.00")]))
    assert confirm(run, senior).status == ImportStatus.CONFIRMED


def test_only_a_lead_or_an_administrator_may_import(firm, client, senior, ctx):
    from django.core.exceptions import PermissionDenied

    other_senior = member(firm, Role.SENIOR_CA, "other@example.test")
    staff = member(firm, Role.STAFF, "staff@example.test")
    admin = member(firm, Role.FIRM_ADMIN, "admin@example.test")
    data = masters_xml([ledger("Capital", "Capital Account", "10.00")])

    for denied in (other_senior, staff):
        with pytest.raises(PermissionDenied):
            stage_upload(client, denied, denied.user, data=data, filename="m.xml", financial_year=FY)
    run, _ = stage_upload(client, admin, admin.user, data=data, filename="m.xml", financial_year=FY)
    with pytest.raises(PermissionDenied):
        confirm_run(run, other_senior, other_senior.user, [])
    assert confirm_run(run, admin, admin.user, []).status == ImportStatus.CONFIRMED


# ---------------------------------------------------------------------------
# One client's books stay one client's: enforced by PostgreSQL
# ---------------------------------------------------------------------------


def test_an_opening_cannot_name_another_clients_ledger(firm, client, ctx):
    other = create_client(firm, "Other Client", START)
    with firm_context(firm.pk):
        foreign = make_ledger(other, "Foreign", LedgerGroup.CAPITAL)
        with connection.cursor() as cursor:
            cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
        with pytest.raises(IntegrityError, match="opening_ledger_same_client"):
            with transaction.atomic():
                LedgerOpening.objects.bulk_create(
                    [LedgerOpening(firm_id=firm.pk, client=client, ledger=foreign, financial_year=FY, signed_paise=100)]
                )


def test_an_opening_cannot_come_from_another_clients_run(firm, client, ctx):
    other = create_client(firm, "Other Client", START)
    with firm_context(firm.pk):
        mine = make_ledger(client, "Mine", LedgerGroup.CAPITAL)
        run = LedgerImportRun.objects.create(
            firm_id=firm.pk, client=other, financial_year=FY, file_sha256="a" * 64, source_format="xml",
            chart_stamp="x", expires_at=datetime.datetime(2030, 1, 1, tzinfo=datetime.UTC),
        )
        with connection.cursor() as cursor:
            cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")
        with pytest.raises(IntegrityError, match="opening_run_same_client"):
            with transaction.atomic():
                LedgerOpening.objects.bulk_create(
                    [LedgerOpening(firm_id=firm.pk, client=client, ledger=mine, financial_year=FY, signed_paise=1, run=run)]
                )


def test_another_firm_cannot_see_the_run_or_its_openings(client, senior):
    rival = create_firm("Rival Firm")
    with firm_context(client.firm_id):
        run, _ = stage(client, senior, masters_xml([ledger("Capital", "Capital Account", "10.00")]))
        confirm(run, senior)
        assert LedgerOpening.objects.exists()
    with firm_context(rival.pk):
        assert not LedgerImportRun.objects.exists()
        assert not LedgerOpening.objects.exists()


def test_the_trial_balance_balances_after_an_import(client, senior, chart):
    run, _ = stage(client, senior, rich_file())
    confirm(run, senior, resolve_all(run))
    report = trial_balance(client, FY)
    assert report.balances
    names = {r.name for r in report.rows}
    assert "Difference in opening balances" in names
