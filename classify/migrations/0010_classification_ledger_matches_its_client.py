"""A classification's ledger must belong to the client whose transaction it is.

This is the table the leak actually landed in. A firm-wide rule put 263 of one
client's transactions into another client's ledger, and nothing in the schema
objected, because the two clients belong to one firm and row-level security is
firm-scoped by design.

``classify/migrations/0009`` removed the mechanism. This removes the
possibility. Every route that sets a ledger -- a rule, a language model, a
reviewer, a management command, whatever is written next year -- passes through
an INSERT or UPDATE here, so a check here covers all of them at once, including
the ones that do not exist yet.

A trigger rather than a composite foreign key, because the client is not a
column on this table: it is reached through the transaction's bank account. A
key cannot express that hop; a trigger can.
"""

from django.conf import settings
from django.db import migrations

TRIGGER_SQL = f"""
CREATE OR REPLACE FUNCTION app.assert_classification_client_matches()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    txn_client    uuid;
    ledger_client uuid;
BEGIN
    IF NEW.ledger_id IS NULL THEN
        -- An unresolved row names no ledger and so cannot cross anything.
        RETURN NEW;
    END IF;

    -- Both reads are firm-scoped tables under FORCE row-level security. The
    -- only context this can set is the firm that owns the row being written,
    -- which the writing transaction already had. See balanced_entry_trigger_sql.
    PERFORM set_config('{settings.TENANT_GUC}', NEW.firm_id::text, true);

    SELECT ba.client_id INTO txn_client
      FROM banking_statement_transaction st
      JOIN banking_bank_account ba ON ba.id = st.bank_account_id
     WHERE st.id = NEW.transaction_id;

    SELECT client_id INTO ledger_client
      FROM classify_ledger_account WHERE id = NEW.ledger_id;

    IF txn_client IS DISTINCT FROM ledger_client THEN
        RAISE EXCEPTION
            'classification would place this transaction in another client''s ledger'
            USING ERRCODE = '23514',
                  HINT = 'A ledger belongs to one client. Two clients of the '
                         'same firm keep separate books, so a transaction can '
                         'only be placed in a ledger of its own client.';
    END IF;

    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS classification_one_client ON classify_transaction_classification;
CREATE TRIGGER classification_one_client
    BEFORE INSERT OR UPDATE OF ledger_id, transaction_id
    ON classify_transaction_classification
    FOR EACH ROW EXECUTE FUNCTION app.assert_classification_client_matches();
"""

REVERSE_SQL = """
DROP TRIGGER IF EXISTS classification_one_client ON classify_transaction_classification;
DROP FUNCTION IF EXISTS app.assert_classification_client_matches();
"""


class Migration(migrations.Migration):

    dependencies = [
        ("classify", "0009_rules_belong_to_one_client"),
        ("banking", "0001_initial"),
    ]

    operations = [
        migrations.RunSQL(sql=TRIGGER_SQL, reverse_sql=REVERSE_SQL),
    ]
