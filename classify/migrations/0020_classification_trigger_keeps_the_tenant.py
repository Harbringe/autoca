"""A BEFORE trigger must not choose the tenant.

``app.assert_classification_client_matches`` (migration 0010) set the transaction's tenant context from the incoming
row's own ``firm_id``. A BEFORE trigger runs before the row's policy check, so adopting the row's firm as the tenant makes
``WITH CHECK (firm_id = app.current_firm_id())`` pass for whatever firm the row names. See ``ledger/0013`` for the full
argument. Replaced here by the same check with the tenant switch removed; the writing transaction already has its context.
"""

from django.db import migrations

FORWARD = """
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
"""


class Migration(migrations.Migration):
    dependencies = [("classify", "0019_party_ledger_same_client")]

    # Going back would restore the flaw, so the reverse is deliberately a no-op.
    operations = [migrations.RunSQL(sql=FORWARD, reverse_sql=migrations.RunSQL.noop)]
