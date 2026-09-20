"""Tenant isolation and immutability for the two records 0006 created.

Both are append-only, unlike the journal they describe: a review step or a
change-log line is a fact about something that happened, and must never itself
be edited -- the log that says who removed an entry is the last thing that may
be removable.
"""

from django.db import migrations

from core.db.rls import append_only_operations


class Migration(migrations.Migration):

    dependencies = [("ledger", "0006_review_records_and_marker")]

    operations = [
        *append_only_operations("ledger_books_event"),
        *append_only_operations("ledger_entry_change"),
    ]
