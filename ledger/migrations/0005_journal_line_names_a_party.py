"""``JournalLine.vendor`` becomes ``JournalLine.party``, following classify.

A rename, deliberately, and not the drop-and-add that Django's autodetector
proposes when it cannot tell one from the other. Two reasons it has to be a
rename here:

* The column holds posted data. Dropping it would discard which party every
  entry ever written was with -- the answer to "how much did we pay them this
  year" for every year already in the books.
* ``ledger_journal_line`` is append-only: the application role holds no UPDATE
  or DELETE grant and a trigger refuses both. Re-populating a new column would
  need exactly the UPDATE that table exists to forbid.

``ALTER TABLE ... RENAME COLUMN`` is catalogue-only DDL. It touches no rows, so
the row-level trigger never fires, and PostgreSQL rewrites the dependent
constraints itself -- they reference columns by number, not by name -- so the
composite key added in 0004 survives without being restated here.
"""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("ledger", "0004_journal_lines_stay_in_one_clients_books"),
        ("classify", "0011_vendor_becomes_party"),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.RenameField(
                    model_name="journalline", old_name="vendor", new_name="party"
                ),
            ],
            database_operations=[
                migrations.RunSQL(
                    sql="ALTER TABLE ledger_journal_line "
                        "RENAME COLUMN vendor_id TO party_id;",
                    reverse_sql="ALTER TABLE ledger_journal_line "
                                "RENAME COLUMN party_id TO vendor_id;",
                ),
            ],
        ),
        # Django's state still records this key as pointing at ``classify.vendor``
        # and wants to restate it. The restatement is true but its SQL is not
        # wanted: recreating a foreign key makes PostgreSQL validate it, which
        # scans two FORCE ROW LEVEL SECURITY tables from a migration that has no
        # tenant context, and the policy refuses. PostgreSQL has already followed
        # the rename on its own -- a constraint is bound to the table's identity,
        # not its name -- so the database is correct and only the state is
        # behind. This says exactly that: update the state, touch nothing.
        migrations.SeparateDatabaseAndState(
            state_operations=[
                migrations.AlterField(
                    model_name="journalline",
                    name="party",
                    field=models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="journal_lines",
                        to="classify.party",
                    ),
                ),
            ],
            database_operations=[],
        ),
    ]
