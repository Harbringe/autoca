"""Row-level security for stock items."""

from django.db import migrations

from core.db.rls import ddl_tenant_context_operations, rls_operations


class Migration(migrations.Migration):
    dependencies = [("ledger", "0032_stock_items")]

    operations = [
        *ddl_tenant_context_operations(),
        *rls_operations("ledger_stock_item"),
    ]
