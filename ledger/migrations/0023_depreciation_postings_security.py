"""Row-level security for depreciation postings, so one firm never sees another's."""

from django.db import migrations

from core.db.rls import ddl_tenant_context_operations, rls_operations


class Migration(migrations.Migration):
    dependencies = [("ledger", "0022_depreciation_postings")]

    operations = [
        *ddl_tenant_context_operations(),
        *rls_operations("ledger_depreciation_posting"),
    ]
