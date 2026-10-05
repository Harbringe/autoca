"""Tenant isolation and the books' own rules for bills and their allocations, enforced by the database.

A bill is part of the books, so it follows the same rules as a journal entry, and for the same reason: a rule the
application enforces is a rule an application bug can lose.

* **Row-level security** on both tables (``rls_operations``), so one firm never sees another's bills.
* **Signed-off books are closed.** A bill dated on or before ``core_client.signed_off_through`` cannot be written or
  removed, and neither can an allocation against a line of such an entry. Read from the client's own row, as the
  journal's guards do, so the only way to unlock a period is the one that already has a guard.
* **Never edited.** Neither table accepts an UPDATE. Re-booking a bill is a delete and a new insert, before sign-off
  only. That keeps "a bill is a fact" true in the database, not just in the code.
* **One client's books.** A bill's party and entry, and an allocation's line and bill, must all belong to the same
  client. Row-level security is per firm and cannot see two clients of one firm.
* **A settlement settles that party.** An allocation's line must be on the bill's party's own ledger, on the opposite
  side to the bill, and an allocation with no bill must still sit on a party's ledger.
* **Allocations cannot exceed what they allocate.** At commit, the allocations on a bill never total more than the
  bill, and those on a line never total more than the line. Deferred, so a settlement can be written in steps.

Additive only: constraints and triggers on two tables this release creates.
"""

from django.conf import settings
from django.db import migrations

from core.db.rls import ddl_tenant_context_operations, rls_operations

GUC = settings.TENANT_GUC

BILL_GUARD = """
CREATE OR REPLACE FUNCTION app.ledger_bill_guard()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    locked_through date;
    party_client   uuid;
    entry_client   uuid;
BEGIN
    IF TG_OP = 'UPDATE' THEN
        RAISE EXCEPTION 'a bill is never edited'
            USING ERRCODE = '42501',
                  HINT = 'Remove it and book it again, before the books are signed off.';
    END IF;

    IF TG_OP = 'DELETE' THEN
        SELECT signed_off_through INTO locked_through FROM core_client WHERE id = OLD.client_id;
        IF locked_through IS NOT NULL AND OLD.booked_on <= locked_through THEN
            RAISE EXCEPTION
                'this bill is dated %, inside books signed off through %; it can no longer be removed',
                OLD.booked_on, locked_through
                USING ERRCODE = '42501',
                      HINT = 'Record a credit or debit note dated after the sign-off, or reopen the books.';
        END IF;
        RETURN OLD;
    END IF;

    -- Deliberately does NOT set the tenant context from NEW.firm_id. A BEFORE trigger runs before the row's policy
    -- check, so a trigger that adopted the incoming row's firm would make that check pass for any firm. The
    -- transaction already has its context, and every read below runs under it.

    SELECT signed_off_through INTO locked_through FROM core_client WHERE id = NEW.client_id;
    IF locked_through IS NOT NULL AND NEW.booked_on <= locked_through THEN
        RAISE EXCEPTION
            'the books are signed off through %; no bill can be dated %',
            locked_through, NEW.booked_on
            USING ERRCODE = '42501',
                  HINT = 'Date the bill after the sign-off, or reopen the books.';
    END IF;

    SELECT client_id INTO party_client FROM classify_party WHERE id = NEW.party_id;
    IF party_client IS DISTINCT FROM NEW.client_id THEN
        RAISE EXCEPTION 'a bill and its party must belong to the same client'
            USING ERRCODE = '23514';
    END IF;

    IF NEW.entry_id IS NOT NULL THEN
        SELECT client_id INTO entry_client FROM ledger_journal_entry WHERE id = NEW.entry_id;
        IF entry_client IS DISTINCT FROM NEW.client_id THEN
            RAISE EXCEPTION 'a bill and the entry that booked it must belong to the same client'
                USING ERRCODE = '23514';
        END IF;
    END IF;

    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS ledger_bill_guard ON ledger_bill;
CREATE TRIGGER ledger_bill_guard
    BEFORE INSERT OR UPDATE OR DELETE ON ledger_bill
    FOR EACH ROW EXECUTE FUNCTION app.ledger_bill_guard();
"""

ALLOCATION_GUARD = """
CREATE OR REPLACE FUNCTION app.ledger_bill_allocation_guard()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    subject_line   uuid;
    line_entry     uuid;
    line_ledger    uuid;
    line_party     uuid;
    line_direction text;
    entry_day      date;
    entry_client   uuid;
    locked_through date;
    bill_client    uuid;
    bill_party     uuid;
    bill_direction text;
    party_ledger   uuid;
BEGIN
    IF TG_OP = 'UPDATE' THEN
        RAISE EXCEPTION 'an allocation is never edited'
            USING ERRCODE = '42501',
                  HINT = 'Remove it and allocate again, before the books are signed off.';
    END IF;

    IF TG_OP = 'DELETE' THEN
        subject_line := OLD.line_id;
    ELSE
        -- No set_config from NEW.firm_id here either; see ledger_bill_guard.
        subject_line := NEW.line_id;
    END IF;

    SELECT l.entry_id, l.ledger_account_id, l.party_id, l.direction, e.entry_date, e.client_id
      INTO line_entry, line_ledger, line_party, line_direction, entry_day, entry_client
      FROM ledger_journal_line l
      JOIN ledger_journal_entry e ON e.id = l.entry_id
     WHERE l.id = subject_line;

    -- A line deleted in the same transaction as its allocations has already gone; there is nothing left to guard.
    IF TG_OP = 'DELETE' THEN
        IF entry_day IS NOT NULL THEN
            SELECT signed_off_through INTO locked_through FROM core_client WHERE id = entry_client;
            IF locked_through IS NOT NULL AND entry_day <= locked_through THEN
                RAISE EXCEPTION
                    'this settlement belongs to an entry dated %, inside books signed off through %',
                    entry_day, locked_through
                    USING ERRCODE = '42501',
                          HINT = 'Record a correcting entry dated after the sign-off, or reopen the books.';
            END IF;
        END IF;
        RETURN OLD;
    END IF;

    IF line_entry IS NULL THEN
        RAISE EXCEPTION 'an allocation must name an existing journal line' USING ERRCODE = '23514';
    END IF;

    SELECT signed_off_through INTO locked_through FROM core_client WHERE id = entry_client;
    IF locked_through IS NOT NULL AND entry_day <= locked_through THEN
        RAISE EXCEPTION
            'the books are signed off through %; nothing can be allocated against an entry dated %',
            locked_through, entry_day
            USING ERRCODE = '42501',
                  HINT = 'Date the settlement after the sign-off, or reopen the books.';
    END IF;

    IF entry_client IS DISTINCT FROM NEW.client_id THEN
        RAISE EXCEPTION 'an allocation and its journal line must belong to the same client'
            USING ERRCODE = '23514';
    END IF;

    IF line_party IS NULL THEN
        RAISE EXCEPTION 'only a line that names a party can be allocated'
            USING ERRCODE = '23514',
                  HINT = 'Settle a bill from a line on the party''s own ledger.';
    END IF;

    SELECT ledger_id INTO party_ledger FROM classify_party WHERE id = line_party;
    IF party_ledger IS DISTINCT FROM line_ledger THEN
        RAISE EXCEPTION 'an allocation must sit on a line of the party''s own ledger'
            USING ERRCODE = '23514';
    END IF;

    IF NEW.bill_id IS NOT NULL THEN
        SELECT client_id, party_id, direction INTO bill_client, bill_party, bill_direction
          FROM ledger_bill WHERE id = NEW.bill_id;
        IF bill_client IS DISTINCT FROM NEW.client_id THEN
            RAISE EXCEPTION 'an allocation and its bill must belong to the same client'
                USING ERRCODE = '23514';
        END IF;
        IF bill_party IS DISTINCT FROM line_party THEN
            RAISE EXCEPTION 'a payment can only settle a bill of the same party'
                USING ERRCODE = '23514';
        END IF;
        IF bill_direction = line_direction THEN
            RAISE EXCEPTION 'a bill is settled by a line on the opposite side of the party''s ledger'
                USING ERRCODE = '23514';
        END IF;
    END IF;

    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS ledger_bill_allocation_guard ON ledger_bill_allocation;
CREATE TRIGGER ledger_bill_allocation_guard
    BEFORE INSERT OR UPDATE OR DELETE ON ledger_bill_allocation
    FOR EACH ROW EXECUTE FUNCTION app.ledger_bill_allocation_guard();
"""

ALLOCATION_SUMS = f"""
CREATE OR REPLACE FUNCTION app.assert_allocation_sums()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    line_amount bigint;
    line_used   bigint;
    bill_total  bigint;
    bill_used   bigint;
BEGIN
    -- Runs at COMMIT, when the request's tenant context is already gone; scoped to the row's own firm, as the
    -- journal's balance check is.
    PERFORM set_config('{GUC}', NEW.firm_id::text, true);

    SELECT amount_paise INTO line_amount FROM ledger_journal_line WHERE id = NEW.line_id;
    IF line_amount IS NOT NULL THEN
        SELECT COALESCE(SUM(amount_paise), 0) INTO line_used
          FROM ledger_bill_allocation WHERE line_id = NEW.line_id AND firm_id = NEW.firm_id;
        IF line_used > line_amount THEN
            RAISE EXCEPTION
                'allocations of % paise exceed the % paise of the journal line they settle',
                line_used, line_amount
                USING ERRCODE = '23514';
        END IF;
    END IF;

    IF NEW.bill_id IS NOT NULL THEN
        SELECT total_paise INTO bill_total FROM ledger_bill WHERE id = NEW.bill_id;
        IF bill_total IS NOT NULL THEN
            SELECT COALESCE(SUM(amount_paise), 0) INTO bill_used
              FROM ledger_bill_allocation WHERE bill_id = NEW.bill_id AND firm_id = NEW.firm_id;
            IF bill_used > bill_total THEN
                RAISE EXCEPTION
                    'allocations of % paise exceed the % paise of the bill they settle',
                    bill_used, bill_total
                    USING ERRCODE = '23514';
            END IF;
        END IF;
    END IF;

    RETURN NULL;
END;
$$;

DROP TRIGGER IF EXISTS assert_allocation_sums ON ledger_bill_allocation;
CREATE CONSTRAINT TRIGGER assert_allocation_sums
    AFTER INSERT ON ledger_bill_allocation
    DEFERRABLE INITIALLY DEFERRED
    FOR EACH ROW EXECUTE FUNCTION app.assert_allocation_sums();
"""

REVERSE = """
DROP TRIGGER IF EXISTS assert_allocation_sums ON ledger_bill_allocation;
DROP TRIGGER IF EXISTS ledger_bill_allocation_guard ON ledger_bill_allocation;
DROP TRIGGER IF EXISTS ledger_bill_guard ON ledger_bill;
DROP FUNCTION IF EXISTS app.assert_allocation_sums();
DROP FUNCTION IF EXISTS app.ledger_bill_allocation_guard();
DROP FUNCTION IF EXISTS app.ledger_bill_guard();
"""


class Migration(migrations.Migration):
    dependencies = [("ledger", "0011_bills_and_voucher_types")]

    operations = [
        *ddl_tenant_context_operations(),
        migrations.RunSQL(sql=BILL_GUARD + ALLOCATION_GUARD + ALLOCATION_SUMS, reverse_sql=REVERSE),
        *rls_operations("ledger_bill"),
        *rls_operations("ledger_bill_allocation"),
    ]
