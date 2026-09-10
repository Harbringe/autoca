"""Install the RLS machinery and put every firm-scoped table behind it.

Every future migration that creates a firm-scoped table must append its own
``rls_operations("<table>")``. Forgetting is not a silent failure: the isolation
suite enumerates ``FirmScopedModel`` subclasses and fails CI for any table
lacking ENABLE, FORCE, and a tenant_isolation policy.
"""

from django.db import migrations

from core.db.rls import (
    bootstrap_operations,
    membership_rls_operations,
    rls_operations,
    sequence_grant_sql,
)


class Migration(migrations.Migration):
    dependencies = [("core", "0001_initial")]

    operations = [
        *bootstrap_operations(),
        # The tenant root. A firm may read exactly one row here: its own.
        *rls_operations("core_firm", column="id"),
        *rls_operations("core_client"),
        *rls_operations("core_audit_log"),
        # Membership needs the bootstrap predicate; see core/db/rls.py.
        *membership_rls_operations("core_firm_membership"),
        migrations.RunSQL(
            sql=sequence_grant_sql(),
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]
