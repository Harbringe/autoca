"""Row-level security for employees and payroll, so one firm never sees another's staff or salaries."""

from django.db import migrations

from core.db.rls import ddl_tenant_context_operations, rls_operations


class Migration(migrations.Migration):
    dependencies = [("ledger", "0026_payroll")]

    operations = [
        *ddl_tenant_context_operations(),
        *rls_operations("ledger_employee"),
        *rls_operations("ledger_payroll_run"),
        *rls_operations("ledger_payroll_line"),
    ]
