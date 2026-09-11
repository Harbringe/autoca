"""Put the classification tables behind tenant isolation.

Separate from the migration that creates them, for the reason set out in
``banking/migrations/0002_row_level_security.py``: Django flushes a migration's
foreign key SQL after every operation has run, so a policy applied in the same
migration is in force when PostgreSQL validates those keys.
"""

from django.db import migrations

from core.db.rls import rls_operations


class Migration(migrations.Migration):
    dependencies = [("classify", "0001_initial")]

    operations = [
        *rls_operations("classify_ledger_account"),
        *rls_operations("classify_rule"),
        *rls_operations("classify_transaction_classification"),
    ]
