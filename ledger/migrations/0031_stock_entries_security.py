"""Row-level security for stock entries, so one firm never sees another's stock."""

from django.db import migrations

from core.db.rls import ddl_tenant_context_operations, rls_operations


class Migration(migrations.Migration):
    dependencies = [("ledger", "0030_stock_entries")]

    operations = [
        *ddl_tenant_context_operations(),
        *rls_operations("ledger_stock_entry"),
    ]
