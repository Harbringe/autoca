"""Isolation and integrity for the asset register, enforced by the database.

* **Row-level security**, so one firm never sees another's assets.
* **One client's books.** An asset's ledger and purchase must belong to the asset's own client; row-level security is per
  firm and cannot see two clients of one firm.

Like the other guards, the trigger does not set the tenant from the incoming row: it runs before the row's policy check, so
it reads under the transaction's own context.
"""

from django.db import migrations

from core.db.rls import ddl_tenant_context_operations, rls_operations

GUARD = """
CREATE OR REPLACE FUNCTION app.ledger_fixed_asset_guard()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    ledger_client uuid;
    bill_client   uuid;
BEGIN
    SELECT client_id INTO ledger_client FROM classify_ledger_account WHERE id = NEW.ledger_id;
    IF ledger_client IS DISTINCT FROM NEW.client_id THEN
        RAISE EXCEPTION 'an asset must be on a ledger of its own client' USING ERRCODE = '23514';
    END IF;
    IF NEW.bill_id IS NOT NULL THEN
        SELECT client_id INTO bill_client FROM ledger_bill WHERE id = NEW.bill_id;
        IF bill_client IS DISTINCT FROM NEW.client_id THEN
            RAISE EXCEPTION 'an asset must come from a purchase of its own client' USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS ledger_fixed_asset_guard ON ledger_fixed_asset;
CREATE TRIGGER ledger_fixed_asset_guard
    BEFORE INSERT OR UPDATE ON ledger_fixed_asset
    FOR EACH ROW EXECUTE FUNCTION app.ledger_fixed_asset_guard();
"""

REVERSE = """
DROP TRIGGER IF EXISTS ledger_fixed_asset_guard ON ledger_fixed_asset;
DROP FUNCTION IF EXISTS app.ledger_fixed_asset_guard();
"""


class Migration(migrations.Migration):
    dependencies = [("ledger", "0020_fixed_assets")]

    operations = [
        *ddl_tenant_context_operations(),
        migrations.RunSQL(sql=GUARD, reverse_sql=REVERSE),
        *rls_operations("ledger_fixed_asset"),
    ]
