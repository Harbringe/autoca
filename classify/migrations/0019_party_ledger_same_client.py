"""A party's ledger must belong to the party's own client.

Row-level security keeps one firm out of another's rows and says nothing about two clients of the same firm. A party
names its ledger, so the same argument as ``classify/0009`` applies: the party's client and its ledger's client are one
value, and the database checks it rather than the application remembering to. A BEFORE trigger rather than a composite
foreign key, matching ``ledger/0004``: no extra column and no new unique constraint on a populated table.
"""

from django.db import migrations

from core.db.rls import ddl_tenant_context_operations

FORWARD = """
CREATE OR REPLACE FUNCTION app.assert_party_ledger_same_client()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    ledger_client uuid;
BEGIN
    IF NEW.ledger_id IS NULL THEN
        RETURN NEW;
    END IF;

    -- Deliberately does NOT set the tenant context from NEW.firm_id: a BEFORE trigger runs before the row's policy
    -- check, so adopting the incoming row's firm would make that check pass for any firm.

    SELECT client_id INTO ledger_client
      FROM classify_ledger_account WHERE id = NEW.ledger_id;

    IF ledger_client IS DISTINCT FROM NEW.client_id THEN
        RAISE EXCEPTION 'a party can only have a ledger belonging to its own client'
            USING ERRCODE = '23514',
                  HINT = 'Two clients of the same firm keep separate books.';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS party_ledger_same_client ON classify_party;
CREATE TRIGGER party_ledger_same_client
    BEFORE INSERT OR UPDATE OF ledger_id, client_id ON classify_party
    FOR EACH ROW EXECUTE FUNCTION app.assert_party_ledger_same_client();
"""

REVERSE = """
DROP TRIGGER IF EXISTS party_ledger_same_client ON classify_party;
DROP FUNCTION IF EXISTS app.assert_party_ledger_same_client();
"""


class Migration(migrations.Migration):
    dependencies = [("classify", "0018_party_ledger")]

    operations = [
        *ddl_tenant_context_operations(),
        migrations.RunSQL(sql=FORWARD, reverse_sql=REVERSE),
    ]
