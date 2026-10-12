"""A way for the background assistant to learn which firms exist, and nothing more.

``run_assistant`` has no signed-in person, so it has no firm and no user. The only list of firms it could read was the
platform administrator's view, which is gated on a signed-in platform superuser and so returned nothing to the worker: it
looked at zero firms, and no row was ever read by the model. This function hands out the ids of the active firms and
nothing else (no names, no counts), so the worker can then enter each firm the ordinary way and read only that firm's rows
under row-level security. It runs with its owner's rights (that is how it can see ``core_firm``), has a fixed search path,
and is executable by the application role alone.
"""

from django.db import migrations

APP_ROLE = "autoca_app"

CREATE = f"""
CREATE OR REPLACE FUNCTION app.active_firm_ids()
RETURNS SETOF uuid
LANGUAGE sql STABLE SECURITY DEFINER SET search_path = pg_catalog, public, pg_temp
AS $$
    SELECT f.id FROM core_firm f WHERE f.is_active;
$$;

REVOKE ALL ON FUNCTION app.active_firm_ids() FROM PUBLIC;
GRANT EXECUTE ON FUNCTION app.active_firm_ids() TO {APP_ROLE};
"""

DROP = "DROP FUNCTION IF EXISTS app.active_firm_ids();"


class Migration(migrations.Migration):
    dependencies = [("core", "0017_client_profile")]

    operations = [migrations.RunSQL(sql=CREATE, reverse_sql=DROP)]
