"""An asset can come from an entry that is not an invoice (a journal or payment brought from Tally), and must be its own client's."""

import django.db.models.deletion
from django.db import migrations, models

GUARD = """
CREATE OR REPLACE FUNCTION app.ledger_fixed_asset_guard()
RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    ledger_client uuid;
    bill_client   uuid;
    entry_client  uuid;
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
    IF NEW.entry_id IS NOT NULL THEN
        SELECT client_id INTO entry_client FROM ledger_journal_entry WHERE id = NEW.entry_id;
        IF entry_client IS DISTINCT FROM NEW.client_id THEN
            RAISE EXCEPTION 'an asset must come from an entry of its own client' USING ERRCODE = '23514';
        END IF;
    END IF;
    RETURN NEW;
END;
$$;
"""

PREVIOUS = """
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
"""


class Migration(migrations.Migration):
    dependencies = [("ledger", "0048_payroll_line_pf_wages")]

    operations = [
        migrations.AddField(
            model_name="fixedasset",
            name="entry",
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name="registered_assets",
                to="ledger.journalentry",
            ),
        ),
        migrations.RunSQL(sql=GUARD, reverse_sql=PREVIOUS),
    ]
