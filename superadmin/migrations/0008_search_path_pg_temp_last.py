"""The directory functions search ``pg_temp`` last, not first.

PostgreSQL looks in a session's temporary schema before any other unless it is named in ``search_path``. These functions
run with the owner's rights and name tables without a schema, so a session able to create a temporary table called
``core_user`` could have them read its rows instead of the real ones. Naming ``pg_temp`` last closes that. Existing
functions are altered in place (not recreated), so the views built on them are untouched.
"""

from django.db import migrations

from superadmin import sql


def alter(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        # The functions belong to the reader role; where this role may not act as it (as on install), there is nothing here.
        if not sql.reader_role_usable(cursor):
            return
        for function in sql.FUNCTIONS:
            # The names are this package's own constants, and a DO block cannot take bound parameters.
            cursor.execute(
                f"DO $$ BEGIN IF to_regprocedure('{function}') IS NOT NULL THEN "
                f"ALTER FUNCTION {function} SET search_path = pg_catalog, public, pg_temp; END IF; END $$;"
            )


class Migration(migrations.Migration):
    dependencies = [("superadmin", "0007_client_business_profile_view")]

    operations = [migrations.RunPython(alter, migrations.RunPython.noop)]
