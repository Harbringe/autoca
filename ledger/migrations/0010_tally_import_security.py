"""Tenant isolation for the Tally import tables, and the client boundary inside a firm.

Row-level security keeps one firm out of another's rows. It says nothing about
two clients of the same firm, and an opening balance names a ledger, so the
same argument as ``classify/0009`` applies: the opening's client and its
ledger's client are one value, checked by composite foreign keys, not by the
application remembering to. The same for the run an opening came from.

Both keys are deferred, like ``rule_ledger_same_client``. The run key is
``NO ACTION`` rather than ``SET NULL``, because a composite ``SET NULL`` would
also null ``client_id``; Django clears ``run_id`` first when a run is deleted.

Additive only: constraints on two tables this release creates.
"""

from django.db import migrations

from core.db.rls import ddl_tenant_context_operations, rls_operations

FORWARD = [
    "ALTER TABLE ledger_import_run ADD CONSTRAINT uniq_import_run_client_id UNIQUE (client_id, id);",
    # An opening's ledger must be a ledger of the opening's own client.
    "ALTER TABLE ledger_opening ADD CONSTRAINT opening_ledger_same_client "
    "FOREIGN KEY (client_id, ledger_id) REFERENCES classify_ledger_account (client_id, id) "
    "ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED;",
    # And so must the run it came from. run_id is nullable; under MATCH SIMPLE a NULL satisfies the key.
    "ALTER TABLE ledger_opening ADD CONSTRAINT opening_run_same_client "
    "FOREIGN KEY (client_id, run_id) REFERENCES ledger_import_run (client_id, id) "
    "ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED;",
]

REVERSE = [
    "ALTER TABLE ledger_opening DROP CONSTRAINT opening_run_same_client;",
    "ALTER TABLE ledger_opening DROP CONSTRAINT opening_ledger_same_client;",
    "ALTER TABLE ledger_import_run DROP CONSTRAINT uniq_import_run_client_id;",
]


class Migration(migrations.Migration):
    dependencies = [("ledger", "0009_tally_import_tables")]

    operations = [
        *ddl_tenant_context_operations(),
        migrations.RunSQL(sql=FORWARD, reverse_sql=REVERSE),
        *rls_operations("ledger_import_run"),
        *rls_operations("ledger_opening"),
    ]
