"""The platform clients view gains ``business_profile``.

Reinstalls the ``superadmin.sql`` set, as 0005 did, because the view's column
list changed. Skipped rather than failed when ``autoca_platform_reader`` is
missing; ``manage.py superadmin install`` adds everything once it exists.
"""

from django.db import migrations, models

from superadmin import sql


def install(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        if sql.reader_role_usable(cursor):
            cursor.execute(sql.CREATE_SQL)


class Migration(migrations.Migration):
    dependencies = [
        ("superadmin", "0006_platform_read_models"),
        ("core", "0012_client_business_profile"),
    ]

    operations = [
        migrations.RunPython(install, migrations.RunPython.noop),
        migrations.AddField(
            model_name="platformclient",
            name="business_profile",
            field=models.TextField(default="", verbose_name="what the business does"),
            preserve_default=False,
        ),
    ]
