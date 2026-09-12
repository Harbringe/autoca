"""Put classify_vendor behind tenant isolation.

Separate from the migration that creates it, for the reason in
banking/migrations/0002_row_level_security.py: Django flushes a migration's
foreign key SQL after every operation has run, so a policy applied in the same
migration is already in force when PostgreSQL validates those keys.
"""

from django.db import migrations

from core.db.rls import rls_operations


class Migration(migrations.Migration):
    dependencies = [("classify", "0003_vendors_and_confidence")]

    operations = [
        *rls_operations("classify_vendor"),
    ]
