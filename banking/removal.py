"""Taking a wrongly uploaded statement back out.

A statement is evidence and a working draft at once: the rows are the bank's,
but until a senior signs the books off everything *derived* from them is still
being worked on. So removal follows the same line as everything else in the
review workflow -- a CA may undo their own work, and nobody may undo signed-off
books.

What goes: the entries posted from its rows (each one through
``ledger.editing.remove_entry``, so each is logged with its previous state), the
rows and their classifications, the parse, the document record and the stored
file. What stays: rules and party aliases learned along the way -- they describe
the payees, not the file -- and the bank account, which other statements may use.
"""

from __future__ import annotations

from django.db import transaction
from django.db.models import ProtectedError

from ledger import editing
from ledger.models import JournalEntry


class StatementRemovalError(RuntimeError):
    """The statement cannot be removed as things stand."""


def entries_from(statement) -> list[JournalEntry]:
    return list(
        JournalEntry.objects.filter(
            firm_id=statement.firm_id, source_transaction__statement=statement
        ).order_by("entry_date", "entry_no")
    )


@transaction.atomic
def remove_statement(statement, *, actor, note: str = "") -> dict:
    """Remove ``statement`` and everything derived from it, or nothing at all."""
    entries = entries_from(statement)

    locked = [e for e in entries if editing.is_locked(e)]
    if locked:
        latest = max(e.entry_date for e in locked)
        raise editing.EntryLockedError(
            f"{len(locked)} entr{'y' if len(locked) == 1 else 'ies'} from this statement "
            f"(up to {latest:%d-%m-%Y}) are inside books a senior has signed off, so the "
            f"statement can no longer be removed. Ask a senior to reopen the books first."
        )

    why = note or "Removed with the statement it came from."
    try:
        for entry in entries:
            editing.remove_entry(entry, actor=actor, note=why)
        document = statement.document
        storage_key = document.storage_key
        bank_account = statement.bank_account
        removed = {
            "statement": str(statement.pk),
            "filename": document.original_filename,
            "rows": statement.transaction_count,
            "entries": len(entries),
        }
        statement.delete()  # rows and their classifications cascade
        document.delete()
    except ProtectedError as exc:
        raise StatementRemovalError(
            "Something else still depends on an entry from this statement (a correction "
            "made to it earlier). Remove or reopen that first."
        ) from exc

    if storage_key:
        transaction.on_commit(lambda: _forget_file(storage_key))
    removed["account_now_empty"] = not bank_account.statements.exists()
    return removed


def _forget_file(key: str) -> None:
    from integrations.registry import get_storage

    try:
        get_storage().delete(key)
    except Exception:  # the record is gone; an orphaned file is a cleanup, not a failure
        import logging

        logging.getLogger("autoca.banking").warning("could not delete stored file %s", key)
