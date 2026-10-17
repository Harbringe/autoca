"""Tenant isolation for the Tally voucher links, and the client boundary inside a firm.

A link names an entry and a run; both must belong to the link's own client, checked by composite foreign keys, as in
0010. The entry key needs ``(client_id, id)`` to be unique on the journal, which it was not. Additive only: one unique
index on an existing table, and constraints on a table this release creates.
"""

from django.db import migrations

from core.db.rls import ddl_tenant_context_operations, rls_operations

FORWARD = [
    "ALTER TABLE ledger_journal_entry ADD CONSTRAINT uniq_entry_client_id UNIQUE (client_id, id);",
    "ALTER TABLE ledger_tally_voucher ADD CONSTRAINT tally_voucher_run_same_client "
    "FOREIGN KEY (client_id, run_id) REFERENCES ledger_import_run (client_id, id) "
    "ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED;",
    "ALTER TABLE ledger_tally_voucher ADD CONSTRAINT tally_voucher_entry_same_client "
    "FOREIGN KEY (client_id, entry_id) REFERENCES ledger_journal_entry (client_id, id) "
    "ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED;",
]
REVERSE = [
    "ALTER TABLE ledger_tally_voucher DROP CONSTRAINT tally_voucher_entry_same_client;",
    "ALTER TABLE ledger_tally_voucher DROP CONSTRAINT tally_voucher_run_same_client;",
    "ALTER TABLE ledger_journal_entry DROP CONSTRAINT uniq_entry_client_id;",
]


class Migration(migrations.Migration):
    dependencies = [("ledger", "0034_tally_vouchers")]

    operations = [
        *ddl_tenant_context_operations(),
        migrations.RunSQL(sql=FORWARD, reverse_sql=REVERSE),
        *rls_operations("ledger_tally_voucher"),
    ]
