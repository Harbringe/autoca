"""Superseded by 0003, which installs the directory functions once the tables
they read (including core_client_assignment) exist. Kept so databases that
already applied it stay consistent; it does nothing in either direction."""

from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("superadmin", "0001_initial"),
        ("core", "0005_job_row_level_security"),
        ("banking", "0002_row_level_security"),
    ]

    operations = [migrations.RunPython(migrations.RunPython.noop, migrations.RunPython.noop)]
