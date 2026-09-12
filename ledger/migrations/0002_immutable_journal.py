"""Tenant isolation, immutability, and the double-entry invariant.

The journal is the one place in this system where the database refuses writes
the application might otherwise make. Three guarantees, all enforced in
PostgreSQL rather than in Python, because an application bug must not be able to
violate any of them:

* **Isolation** -- the same tenant policy as every other firm-scoped table.
* **Immutability** -- no UPDATE or DELETE grant, plus a trigger that raises.
  Indian company law expects a permanent record of financial entries;
  corrections are new entries, never overwrites. Two mechanisms because grants
  get widened by a careless later migration and triggers get lost in a restore,
  but rarely both at once.
* **Balance** -- a deferred constraint trigger sums each entry's lines at
  commit. Deferred because an entry is written a line at a time and is
  legitimately unbalanced in between; commit is the only point where the
  question means anything.

``ledger_voucher_sequence`` is deliberately *not* append-only. It is a counter,
not a record, and allocating a number is an update by definition.
"""

from django.db import migrations

from core.db.rls import (
    append_only_operations,
    balanced_entry_operations,
    rls_operations,
    sequence_grant_sql,
)


class Migration(migrations.Migration):
    dependencies = [("ledger", "0001_initial")]

    operations = [
        *append_only_operations("ledger_journal_entry"),
        *append_only_operations("ledger_journal_line"),
        *balanced_entry_operations("ledger_journal_line"),
        *rls_operations("ledger_voucher_sequence"),
        migrations.RunSQL(sql=sequence_grant_sql(), reverse_sql=migrations.RunSQL.noop),
    ]
