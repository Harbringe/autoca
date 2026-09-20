"""Put core_client_assignment behind tenant isolation."""

from django.db import migrations

from core.db.rls import rls_operations


class Migration(migrations.Migration):
    dependencies = [("core", "0006_teams_and_assignments")]

    operations = [
        *rls_operations("core_client_assignment"),
    ]
