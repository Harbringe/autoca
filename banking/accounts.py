"""Tidying a client's bank accounts: removing one that holds nothing, and merging a duplicate into the account it should have been.

A duplicate happens: a statement printed the number masked, or with no number, before the client's real account was recognised, and
a second account was opened. The journal is append-only, so neither action touches a posted entry. Removing is only for an account with
no statements and nothing posted to its ledger. Merging moves a duplicate's statements and rows onto the right account (each row
fingerprinted again for that account, so a later upload of the same statement is still recognised) and is refused while anything is
posted to the duplicate's ledger, while the two accounts' statements cover the same days, or while their opening balances disagree.

Both are logged in the masters' audit trail against the account's ledger.
"""

from __future__ import annotations

from django.db import transaction
from django.db.models import ProtectedError

from banking.models import BankAccount, Statement, StatementTransaction
from classify.models import LedgerAccount
from ledger.audit import record_master_change
from ledger.models import JournalLine, MasterAction, MasterKind


class AccountChangeError(RuntimeError):
    """The account cannot be removed or merged as things stand."""


def _ledger_of(account: BankAccount) -> LedgerAccount | None:
    return LedgerAccount.objects.filter(firm_id=account.firm_id, client_id=account.client_id, name=account.ledger_name).first()


def _posted_lines(ledger: LedgerAccount | None) -> int:
    if ledger is None:
        return 0
    return JournalLine.objects.filter(firm_id=ledger.firm_id, ledger_account=ledger).count()


def _shared(ledger: LedgerAccount | None, account: BankAccount) -> bool:
    """Another account posts to the same ledger, so it is not this account's to delete."""
    return ledger is not None and BankAccount.objects.filter(
        firm_id=account.firm_id, client_id=account.client_id, ledger_name=ledger.name
    ).exclude(pk=account.pk).exists()


def _describe(account: BankAccount) -> dict:
    return {
        "ledger_name": account.ledger_name,
        "bank_code": account.bank_code,
        "account_last4": account.account_last4,
        "kind": account.kind,
        "opening_balance_paise": account.opening_balance_paise,
        "opening_as_of": account.opening_as_of.isoformat() if account.opening_as_of else None,
    }


def _drop_empty_ledger(ledger: LedgerAccount | None, account: BankAccount) -> bool:
    """Delete the account's own ledger when nothing is posted to it and nothing else points at it. Returns whether it went."""
    if ledger is None or _posted_lines(ledger) or _shared(ledger, account):
        return False
    try:
        with transaction.atomic():
            ledger.delete()
    except ProtectedError:
        return False  # a rule, an opening or an asset still names it: the ledger stays, which is harmless
    return True


@transaction.atomic
def remove_account(account: BankAccount, *, actor) -> dict:
    """Remove an account that holds nothing: no statements, nothing posted to its ledger."""
    statements = account.statements.count()
    if statements:
        raise AccountChangeError(
            f"{account} still has {statements} statement{'s' if statements != 1 else ''}. Remove "
            f"{'them' if statements != 1 else 'it'} first, or merge this account into the one it should be."
        )
    ledger = _ledger_of(account)
    posted = _posted_lines(ledger)
    if posted:
        raise AccountChangeError(
            f"{posted} entr{'y is' if posted == 1 else 'ies are'} posted to {account.ledger_name}, so the account cannot be removed. "
            "Remove or move those entries first."
        )
    before = _describe(account)
    label = str(account)
    ledger_id = ledger.pk if ledger else account.pk
    account.delete()
    ledger_removed = _drop_empty_ledger(ledger, account)
    record_master_change(
        account.client, MasterKind.LEDGER, ledger_id, MasterAction.REMOVED, label=f"Bank account {label}",
        before=before, after={"ledger_removed": ledger_removed}, actor=actor,
    )
    return {"removed": label, "ledger_removed": ledger_removed}


@transaction.atomic
def merge_account(source: BankAccount, target: BankAccount, *, actor) -> dict:
    """Move ``source``'s statements and rows onto ``target`` and remove ``source``. All or nothing."""
    if source.pk == target.pk:
        raise AccountChangeError("Choose a different account to merge into.")
    if source.client_id != target.client_id:
        raise AccountChangeError("Both accounts must belong to the same client.")
    if source.kind != target.kind:
        raise AccountChangeError(
            f"{source} is a {source.get_kind_display().lower()} and {target} a {target.get_kind_display().lower()}; "
            "they cannot be one account."
        )
    source_ledger = _ledger_of(source)
    posted = _posted_lines(source_ledger)
    if posted:
        raise AccountChangeError(
            f"{posted} entr{'y is' if posted == 1 else 'ies are'} posted to {source.ledger_name}. Posted entries are never moved: "
            f"remove {source}'s statements (which takes their entries back) and upload them to {target} instead."
        )
    if source.has_opening_balance and target.has_opening_balance and (
        source.opening_balance_paise != target.opening_balance_paise or source.opening_as_of != target.opening_as_of
    ):
        raise AccountChangeError(
            "The two accounts have different confirmed opening balances. Correct the one that is wrong before merging."
        )

    moving = list(Statement.objects.filter(firm_id=source.firm_id, bank_account=source).order_by("period_start"))
    staying = list(Statement.objects.filter(firm_id=target.firm_id, bank_account=target))
    for s in moving:
        for t in staying:
            if s.period_start <= t.period_end and t.period_start <= s.period_end:
                raise AccountChangeError(
                    f"{source}'s statement {s.period_start:%d-%m-%Y} to {s.period_end:%d-%m-%Y} covers days {target} already has "
                    f"({t.period_start:%d-%m-%Y} to {t.period_end:%d-%m-%Y}). Remove one of them first, so no row is counted twice."
                )

    # Each row's fingerprint includes its account, so a moved row is fingerprinted again for the target, exactly as an upload there
    # would have done it; a later upload of the same statement to the target is then recognised as already on file.
    existing = set(
        StatementTransaction.objects.filter(firm_id=target.firm_id, bank_account=target).values_list("dedupe_hash", flat=True)
    )
    rows = 0
    for statement in moving:
        seen: dict[str, int] = {}
        for row in StatementTransaction.objects.filter(firm_id=statement.firm_id, statement=statement).order_by("row_number"):
            fields = {
                "account_hash": target.account_number_hash,
                "value_date": row.value_date,
                "narration": row.narration,
                "debit_paise": row.debit_paise,
                "credit_paise": row.credit_paise,
                "balance_paise": row.balance_paise,
            }
            digest = StatementTransaction.compute_dedupe_hash(**fields)
            repeat = seen.get(digest, 0)
            seen[digest] = repeat + 1
            if repeat:
                digest = StatementTransaction.compute_dedupe_hash(**fields, occurrence=repeat)
            if digest in existing:
                raise AccountChangeError(
                    f"The row of {row.value_date:%d-%m-%Y} ({row.narration[:40]!r}) is already on {target}. Remove the duplicate "
                    "statement instead of merging it."
                )
            existing.add(digest)
            row.bank_account = target
            row.dedupe_hash = digest
            row.save(update_fields=["bank_account", "dedupe_hash"])
            rows += 1
        statement.bank_account = target
        statement.save(update_fields=["bank_account"])

    if source.has_opening_balance and not target.has_opening_balance:
        target.opening_balance_paise, target.opening_as_of = source.opening_balance_paise, source.opening_as_of
        target.save(update_fields=["opening_balance_paise", "opening_as_of"])

    before = _describe(source)
    label = str(source)
    ledger_id = source_ledger.pk if source_ledger else source.pk
    source.delete()
    ledger_removed = _drop_empty_ledger(source_ledger, source)
    record_master_change(
        target.client, MasterKind.LEDGER, ledger_id, MasterAction.REMOVED, label=f"Bank account {label} merged into {target}",
        before=before, after={"merged_into": str(target.pk), "statements": len(moving), "rows": rows, "ledger_removed": ledger_removed},
        actor=actor,
    )
    return {"merged": label, "into": str(target), "statements": len(moving), "rows": rows, "ledger_removed": ledger_removed}
