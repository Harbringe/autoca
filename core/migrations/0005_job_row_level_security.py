"""Put core_job behind tenant isolation.

A job's result carries whatever the work produced -- statement ids, row counts,
and the domain's own error messages, which quote narrations. That is a firm's
data like any other and gets the same policy.
"""

from django.db import migrations

from core.db.rls import rls_operations


class Migration(migrations.Migration):
    dependencies = [("core", "0004_job")]

    operations = [
        *rls_operations("core_job"),
    ]
