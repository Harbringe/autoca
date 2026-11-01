"""Tenant isolation for the voucher-series tables, the client boundary inside a firm, and an append-only master audit trail.

A voucher class names a head ledger, which must belong to the class's own client, checked by composite foreign keys to the ledger table's
``(client_id, id)`` key, as in 0010 and 0035. The master change log may only ever be inserted into, like the entry change log. Additive
only: constraints and policies on tables this release creates.
"""

from django.db import migrations

from core.db.rls import append_only_operations, ddl_tenant_context_operations, rls_operations

LEDGER_COLUMNS = ("head_ledger_id",)

FORWARD = [
    f"ALTER TABLE ledger_voucher_class ADD CONSTRAINT voucher_class_{column.removesuffix('_id')}_same_client "
    f"FOREIGN KEY (client_id, {column}) REFERENCES classify_ledger_account (client_id, id) "
    "ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED;"
    for column in LEDGER_COLUMNS
]
REVERSE = [
    f"ALTER TABLE ledger_voucher_class DROP CONSTRAINT voucher_class_{column.removesuffix('_id')}_same_client;"
    for column in reversed(LEDGER_COLUMNS)
]


class Migration(migrations.Migration):
    dependencies = [("ledger", "0039_voucher_series_classes_audit")]

    operations = [
        *ddl_tenant_context_operations(),
        migrations.RunSQL(sql=FORWARD, reverse_sql=REVERSE),
        *rls_operations("ledger_custom_voucher_type"),
        *rls_operations("ledger_numbering_format"),
        *rls_operations("ledger_voucher_class"),
        *rls_operations("ledger_master_change"),
        *append_only_operations("ledger_master_change"),
    ]
