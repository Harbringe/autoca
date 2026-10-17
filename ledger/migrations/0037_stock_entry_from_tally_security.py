"""A stock movement and the import run it came from belong to one client, checked by a composite foreign key as in 0010."""

from django.db import migrations

from core.db.rls import ddl_tenant_context_operations

FORWARD = [
    "ALTER TABLE ledger_stock_entry ADD CONSTRAINT stock_entry_run_same_client "
    "FOREIGN KEY (client_id, run_id) REFERENCES ledger_import_run (client_id, id) "
    "ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED;",
]
REVERSE = ["ALTER TABLE ledger_stock_entry DROP CONSTRAINT stock_entry_run_same_client;"]


class Migration(migrations.Migration):
    dependencies = [("ledger", "0036_stock_entry_from_tally")]

    operations = [
        *ddl_tenant_context_operations(),
        migrations.RunSQL(sql=FORWARD, reverse_sql=REVERSE),
    ]
