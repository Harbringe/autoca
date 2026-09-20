"""Tenant isolation for invites; isolation plus immutability for the two logs."""

from django.db import migrations

from core.db.rls import append_only_operations, rls_operations


class Migration(migrations.Migration):
    dependencies = [("teams", "0001_initial")]

    operations = [
        *rls_operations("teams_invite"),
        *append_only_operations("teams_activity_event"),
        *append_only_operations("teams_team_event"),
    ]
