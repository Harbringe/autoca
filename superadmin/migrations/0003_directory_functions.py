"""Install the cross-firm directory functions, if the reader role is set up.

Skipped (not failed) when ``autoca_platform_reader`` is missing, so a database
without it migrates cleanly. Run ``python manage.py superadmin install`` after
creating the role. Fully reversible: ``migrate superadmin zero`` drops them.
"""

from django.db import migrations

from superadmin import sql


def install(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        if sql.reader_role_usable(cursor):
            cursor.execute(sql.CREATE_SQL)


def uninstall(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(sql.DROP_SQL)


class Migration(migrations.Migration):
    dependencies = [
        ("superadmin", "0002_directory_functions"),
        ("core", "0007_client_assignment_row_level_security"),
    ]

    operations = [migrations.RunPython(install, uninstall)]
