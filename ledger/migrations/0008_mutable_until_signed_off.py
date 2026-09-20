"""The journal is a working draft until a senior signs it off, and permanent after.

Until now an entry was immutable the moment it was written: the application role
held no UPDATE or DELETE grant and a trigger refused both. That is the right rule
for a *finished* book and the wrong one for a book being prepared, where the
normal work of a CA is to look at what the AI posted, remove what is wrong and
correct it. Forcing each fix to be a reversal plus a new entry leaves the books
full of the scaffolding of getting them right.

So the moment of permanence moves, from "when posted" to "when signed off":

* **Before sign-off** an entry and its lines may be updated or deleted, and every
  such change is written to ``ledger_entry_change`` by ``ledger.editing`` with
  who, when and the complete previous state.
* **After sign-off** nothing dated on or before ``core_client.signed_off_through``
  can be inserted, updated or deleted -- in the database, not just in code, and
  in both directions: an entry cannot be edited into the locked period either.
  A later fix is a visible correcting entry dated in the open period, as
  before.

What the database still guarantees, unchanged: tenant isolation, and that every
entry balances. The balance check now also fires on UPDATE and DELETE, because an
entry that can be edited can be edited into imbalance.

What it no longer guarantees is that an unsigned entry is immutable, and that is
the point. The audit record that used to be "the row cannot change" is now "the
row changed, and here is exactly how", which is what an auditor asks for of a
draft.

**Why the guards read ``core_client`` rather than being told the date.** A trigger
that trusted a value from the caller would be a lock the caller holds the key
to. Reading the client's own row means the only way to unlock a period is to
move ``signed_off_through`` -- which has its own guard (``core.0011``).

**Renumbering at sign-off** (``ledger.books``) needs to UPDATE ``entry_no``, which
this permits precisely because it runs *before* the lock date is advanced.
"""

from django.db import migrations

from core.db.rls import (
    APP_ROLE,
    append_only_sql,
    balanced_entry_trigger_sql,
)
from django.conf import settings

GUC = settings.TENANT_GUC

ENTRY_GUARD = f"""
CREATE OR REPLACE FUNCTION app.ledger_journal_entry_immutable()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    subject_client uuid;
    subject_date   date;
    locked_through date;
BEGIN
    IF TG_OP = 'DELETE' THEN
        subject_client := OLD.client_id;
        subject_date   := OLD.entry_date;
    ELSE
        subject_client := NEW.client_id;
        subject_date   := NEW.entry_date;
    END IF;

    SELECT signed_off_through INTO locked_through
      FROM core_client WHERE id = subject_client;

    IF TG_OP = 'UPDATE' AND (NEW.client_id <> OLD.client_id OR NEW.firm_id <> OLD.firm_id) THEN
        RAISE EXCEPTION 'a journal entry cannot be moved to another client'
            USING ERRCODE = '42501';
    END IF;

    -- The entry's current date, and (for an UPDATE) the date it is being
    -- given: an entry may be neither changed while locked nor changed *into*
    -- the locked period.
    IF locked_through IS NOT NULL THEN
        IF TG_OP IN ('UPDATE', 'DELETE') AND OLD.entry_date <= locked_through THEN
            RAISE EXCEPTION
                'this entry is dated %, inside books signed off through %; it can no longer be %',
                OLD.entry_date, locked_through,
                CASE TG_OP WHEN 'DELETE' THEN 'removed' ELSE 'changed' END
                USING ERRCODE = '42501',
                      HINT = 'Record a correcting entry dated after the sign-off, '
                             'or reopen the books.';
        END IF;
        IF TG_OP IN ('INSERT', 'UPDATE') AND NEW.entry_date <= locked_through THEN
            RAISE EXCEPTION
                'the books are signed off through %; nothing can be posted dated %',
                locked_through, NEW.entry_date
                USING ERRCODE = '42501',
                      HINT = 'Date the entry after the sign-off, or reopen the books.';
        END IF;
    END IF;

    IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS ledger_journal_entry_immutable ON ledger_journal_entry;
CREATE TRIGGER ledger_journal_entry_immutable
    BEFORE INSERT OR UPDATE OR DELETE ON ledger_journal_entry
    FOR EACH ROW EXECUTE FUNCTION app.ledger_journal_entry_immutable();
"""

LINE_GUARD = f"""
CREATE OR REPLACE FUNCTION app.ledger_journal_line_immutable()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    target_entry   uuid;
    entry_day      date;
    entry_client   uuid;
    locked_through date;
BEGIN
    IF TG_OP = 'DELETE' THEN
        target_entry := OLD.entry_id;
    ELSE
        target_entry := NEW.entry_id;
    END IF;

    IF TG_OP = 'UPDATE' AND NEW.entry_id <> OLD.entry_id THEN
        RAISE EXCEPTION 'a journal line cannot be moved to another entry'
            USING ERRCODE = '42501';
    END IF;

    SELECT entry_date, client_id INTO entry_day, entry_client
      FROM ledger_journal_entry WHERE id = target_entry;

    -- An entry deleted in the same transaction as its lines has already gone by
    -- the time its last line is; there is nothing left to be locked.
    IF entry_day IS NOT NULL THEN
        SELECT signed_off_through INTO locked_through
          FROM core_client WHERE id = entry_client;
        IF locked_through IS NOT NULL AND entry_day <= locked_through THEN
            RAISE EXCEPTION
                'this line belongs to an entry dated %, inside books signed off through %',
                entry_day, locked_through
                USING ERRCODE = '42501',
                      HINT = 'Record a correcting entry dated after the sign-off, '
                             'or reopen the books.';
        END IF;
    END IF;

    IF TG_OP = 'DELETE' THEN RETURN OLD; END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS ledger_journal_line_immutable ON ledger_journal_line;
CREATE TRIGGER ledger_journal_line_immutable
    BEFORE INSERT OR UPDATE OR DELETE ON ledger_journal_line
    FOR EACH ROW EXECUTE FUNCTION app.ledger_journal_line_immutable();
"""

BALANCE = f"""
CREATE OR REPLACE FUNCTION app.assert_entry_balances()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    imbalance     bigint;
    subject_entry uuid;
    subject_firm  uuid;
BEGIN
    IF TG_OP = 'DELETE' THEN
        subject_entry := OLD.entry_id;
        subject_firm  := OLD.firm_id;
    ELSE
        subject_entry := NEW.entry_id;
        subject_firm  := NEW.firm_id;
    END IF;

    -- Runs at COMMIT, when the request's tenant context is already gone; see
    -- core.db.rls.balanced_entry_trigger_sql for why this is scoped to the
    -- row's own firm and can never be wider than the transaction's access.
    PERFORM set_config('{GUC}', subject_firm::text, true);

    SELECT COALESCE(SUM(signed_paise), 0) INTO imbalance
      FROM ledger_journal_line
     WHERE entry_id = subject_entry AND firm_id = subject_firm;

    IF imbalance <> 0 THEN
        RAISE EXCEPTION
            'journal entry % does not balance: debits and credits differ by % paise',
            subject_entry, imbalance
            USING ERRCODE = '23514',
                  HINT = 'Every entry needs equal debits and credits. This is '
                         'checked at commit, so the offending entry is the one '
                         'named, not necessarily the last one written.';
    END IF;
    RETURN NULL;
END;
$$;

DROP TRIGGER IF EXISTS assert_entry_balances ON ledger_journal_line;
CREATE CONSTRAINT TRIGGER assert_entry_balances
    AFTER INSERT OR UPDATE OR DELETE ON ledger_journal_line
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION app.assert_entry_balances();
"""

GRANTS = f"""
GRANT UPDATE, DELETE ON ledger_journal_entry TO {APP_ROLE};
GRANT UPDATE, DELETE ON ledger_journal_line  TO {APP_ROLE};
"""

REVOKE = f"""
REVOKE UPDATE, DELETE ON ledger_journal_entry FROM {APP_ROLE};
REVOKE UPDATE, DELETE ON ledger_journal_line  FROM {APP_ROLE};
"""


class Migration(migrations.Migration):

    dependencies = [
        ("ledger", "0007_review_records_security"),
        ("core", "0011_client_signed_off_through"),
    ]

    operations = [
        migrations.RunSQL(
            sql=GRANTS + ENTRY_GUARD + LINE_GUARD + BALANCE,
            reverse_sql=(
                REVOKE
                + append_only_sql("ledger_journal_entry")
                + append_only_sql("ledger_journal_line")
                + balanced_entry_trigger_sql("ledger_journal_line")
            ),
        ),
    ]
