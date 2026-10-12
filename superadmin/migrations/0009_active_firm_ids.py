"""Gives the background assistant a way to learn which firms exist: ``app.active_firm_ids()``, ids only.

The assistant worker has no signed-in person, so the gated platform views return it nothing and it never found a firm to work for.
This installs just the one function, owned by the read-only reader role like the others, executable by the application role.
Where the reader role is missing (a database without it), nothing is installed, as with the other platform objects.
"""

from django.db import migrations

from superadmin import sql

FUNCTION = "app.active_firm_ids()"


def install(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        if not sql.reader_role_usable(cursor):
            return
        cursor.execute(
            sql.SCHEMA_GRANT_SQL
            + sql.ACTIVE_FIRM_IDS_SQL
            + f"ALTER FUNCTION {FUNCTION} OWNER TO {sql.READER_ROLE};\n"
            + f"REVOKE ALL ON FUNCTION {FUNCTION} FROM PUBLIC;\n"
            + f"GRANT EXECUTE ON FUNCTION {FUNCTION} TO {sql.APP_ROLE};\n"
            + sql.SCHEMA_REVOKE_SQL
        )


def uninstall(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute(f"DROP FUNCTION IF EXISTS {FUNCTION};")


class Migration(migrations.Migration):
    dependencies = [("superadmin", "0008_search_path_pg_temp_last")]

    operations = [migrations.RunPython(install, uninstall)]
