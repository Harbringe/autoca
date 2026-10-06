"""Row-level security for TDS challans, so one firm never sees another's."""

from django.db import migrations

from core.db.rls import ddl_tenant_context_operations, rls_operations


class Migration(migrations.Migration):
    dependencies = [("ledger", "0024_tds_challans")]

    operations = [
        *ddl_tenant_context_operations(),
        *rls_operations("ledger_tds_challan"),
    ]
