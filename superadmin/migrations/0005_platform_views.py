"""The platform admin's read models: gated, SELECT-only views across firms.

Reinstalls the whole ``superadmin.sql`` set, so the new gate function and the
views arrive together with the existing directory functions. Like 0003, this is
skipped rather than failed when ``autoca_platform_reader`` is missing, so a
database without the role still migrates; ``manage.py superadmin install`` adds
everything once the role exists.

Reversing drops only what this migration added -- the views and the gate -- and
leaves the older functions for 0003 to own.
"""

from django.db import migrations

from superadmin import sql


def install(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        if sql.reader_role_usable(cursor):
            cursor.execute(sql.CREATE_SQL)


def uninstall(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(sql.DROP_VIEWS_SQL)
        cursor.execute("DROP FUNCTION IF EXISTS app.superadmin_can_read();")


class Migration(migrations.Migration):
    dependencies = [
        ("superadmin", "0004_superuser_is_the_flag"),
        ("core", "0010_profile"),
        ("banking", "0002_row_level_security"),
    ]

    operations = [migrations.RunPython(install, uninstall)]
