"""A journal line's ledger must belong to the same client as its entry.

The entry says whose books it is. The line says which ledger it hits. Nothing
made the two agree, and in a database carrying real statements they came apart:
one client's transactions were posted into a ledger belonging to another client
of the same firm. Row-level security did not see it and could not -- it is
firm-scoped, and both clients belong to one firm.

A trigger rather than a foreign key. A composite key would need a ``client_id``
column on the line, and filling one in means an UPDATE against an append-only
table that Indian company law is the reason for. The table is insert-only, so a
BEFORE INSERT check is exactly as strong as a key would be, and it leaves the
existing record untouched.

Existing rows are left alone deliberately. A line already posted is part of the
permanent record; the remedy for a wrong one is a superseding entry made by a
person who can sign it, not a migration quietly rewriting history. This closes
the door for every line written from here on.
"""

from django.conf import settings
from django.db import migrations

TRIGGER_SQL = f"""
CREATE OR REPLACE FUNCTION app.assert_line_matches_entry_client()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    entry_client  uuid;
    ledger_client uuid;
    ledger_name   text;
BEGIN
    -- Deferred triggers fire at COMMIT, when the request's tenant context has
    -- already been cleared; this one is immediate, but it is set here anyway so
    -- the two reads below cannot depend on the caller's lifecycle. The only
    -- value it can set is the firm that owns the row being inserted, which the
    -- inserting transaction already had access to. See balanced_entry_trigger_sql.
    PERFORM set_config('{settings.TENANT_GUC}', NEW.firm_id::text, true);

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

DROP TRIGGER IF EXISTS journal_line_one_client ON ledger_journal_line;
CREATE TRIGGER journal_line_one_client
    BEFORE INSERT ON ledger_journal_line
    FOR EACH ROW EXECUTE FUNCTION app.assert_line_matches_entry_client();
"""

REVERSE_SQL = """
DROP TRIGGER IF EXISTS journal_line_one_client ON ledger_journal_line;
DROP FUNCTION IF EXISTS app.assert_line_matches_entry_client();
"""


class Migration(migrations.Migration):

    dependencies = [
        ("ledger", "0003_balance_trigger_tenant_context"),
        ("classify", "0009_rules_belong_to_one_client"),
    ]

    operations = [
        migrations.RunSQL(sql=TRIGGER_SQL, reverse_sql=REVERSE_SQL),
    ]
