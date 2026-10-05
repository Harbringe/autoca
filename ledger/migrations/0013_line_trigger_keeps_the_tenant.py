"""A BEFORE trigger must not choose the tenant.

``app.assert_line_matches_entry_client`` (migration 0004) set the transaction's tenant context from the incoming row's
own ``firm_id`` before reading the entry and ledger. A BEFORE trigger runs before the row's policy check, so adopting the
row's firm as the tenant makes ``WITH CHECK (firm_id = app.current_firm_id())`` pass for whatever firm the row names:
a row for another firm, written by a session that belongs to this one, and every later statement in that transaction
running as the other firm. It needs an application bug to supply the wrong firm id, but row-level security exists to
survive exactly that bug.

The line is replaced here by the same check with the tenant switch removed. It is an immediate trigger, so the writing
transaction already has its context and both reads run under it. Deferred triggers that fire at commit still set it,
because by then the context is gone and their rows have long since passed the policy check.
"""

from django.db import migrations

FORWARD = """
CREATE OR REPLACE FUNCTION app.assert_line_matches_entry_client()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    entry_client  uuid;
    ledger_client uuid;
    ledger_name   text;
BEGIN
    SELECT client_id INTO entry_client
      FROM ledger_journal_entry WHERE id = NEW.entry_id;

    SELECT client_id, name INTO ledger_client, ledger_name
      FROM classify_ledger_account WHERE id = NEW.ledger_account_id;

    IF entry_client IS DISTINCT FROM ledger_client THEN
        RAISE EXCEPTION
            'journal line would post into %, a ledger of another client',
            ledger_name
            USING ERRCODE = '23514',
                  HINT = 'An entry and every ledger it touches belong to one '
                         'client. Two clients of the same firm keep separate '
                         'books.';
    END IF;

    RETURN NEW;
END;
$$;
"""


class Migration(migrations.Migration):
    dependencies = [("ledger", "0012_bills_security")]

    # Going back would restore the flaw, so the reverse is deliberately a no-op.
    operations = [migrations.RunSQL(sql=FORWARD, reverse_sql=migrations.RunSQL.noop)]
