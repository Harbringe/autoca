"""Put the documents tables behind tenant isolation.

Separate from the migration that creates them, and it has to be. Django opens
one schema editor per migration and flushes its deferred SQL -- which is where
foreign key constraints live -- when that editor closes, after every operation
has run. A policy applied in the same migration is therefore already in force
when PostgreSQL validates those keys, and the validation scan dies on a table it
can no longer read.
"""

from django.db import migrations

from core.db.rls import rls_operations


class Migration(migrations.Migration):
    dependencies = [("documents", "0001_initial")]

    operations = [
        *rls_operations("documents_document"),
    ]
