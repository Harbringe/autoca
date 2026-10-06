"""Row-level security for close acknowledgements, so one firm never sees another's reasons."""

from django.db import migrations

from core.db.rls import ddl_tenant_context_operations, rls_operations


class Migration(migrations.Migration):
    dependencies = [("ledger", "0016_close_acknowledgements")]

    operations = [
        *ddl_tenant_context_operations(),
        *rls_operations("ledger_close_acknowledgement"),
    ]
