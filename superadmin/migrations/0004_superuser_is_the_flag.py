"""Super admin becomes "a superuser with no firm"; the grant table goes.

Any existing grant is carried over by setting is_superuser/is_staff on that
account. The directory functions are dropped first (their old body reads the
table) and reinstalled with the new rule if the reader role is set up.
"""

from django.db import migrations

from superadmin import sql


def drop_functions(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        # This migration imports the live ``superadmin.sql``, so on a database
        # built from scratch 0003 has already installed the platform views added
        # much later (0005). They depend on app.superadmin_can_read(), so they go
        # first; ``install`` below puts them back. On a database that applied
        # this migration before the views existed, dropping nothing is harmless.
        cursor.execute(sql.DROP_VIEWS_SQL)
        cursor.execute("".join(f"DROP FUNCTION IF EXISTS {fn};\n" for fn in reversed(sql.FUNCTIONS)))


def carry_grants_over(apps, schema_editor):
    SuperAdmin = apps.get_model("superadmin", "SuperAdmin")
    User = apps.get_model("core", "User")
    ids = list(SuperAdmin.objects.values_list("user_id", flat=True))
    if ids:
        User.objects.filter(pk__in=ids).update(is_superuser=True, is_staff=True)


def install(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        if sql.reader_role_usable(cursor):
            cursor.execute(sql.CREATE_SQL)


class Migration(migrations.Migration):
    dependencies = [("superadmin", "0003_directory_functions")]

    operations = [
        migrations.RunPython(drop_functions, migrations.RunPython.noop),
        migrations.RunPython(carry_grants_over, migrations.RunPython.noop),
        migrations.DeleteModel(name="SuperAdmin"),
        migrations.RunPython(install, drop_functions),
    ]
