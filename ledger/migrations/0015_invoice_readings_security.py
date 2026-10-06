"""Row-level security for invoice readings, so one firm never sees another's drafts.

A reading is mutable (a person books it or sets it aside), so unlike the journal it gets isolation and nothing else.
"""

from django.db import migrations

from core.db.rls import ddl_tenant_context_operations, rls_operations


class Migration(migrations.Migration):
    dependencies = [("ledger", "0014_invoice_readings")]

    operations = [
        *ddl_tenant_context_operations(),
        *rls_operations("ledger_invoice_reading"),
    ]
