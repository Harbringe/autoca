"""Two more platform read models: every firm's invitations, and each firm at a glance.

Reinstalls the ``superadmin.sql`` set, as 0005 and 0007 did, because the set of views grew. Skipped rather than failed when
``autoca_platform_reader`` is missing; ``manage.py superadmin install`` adds everything once it exists.
"""

from django.db import migrations, models

from superadmin import sql


def install(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        if sql.reader_role_usable(cursor):
            cursor.execute(sql.CREATE_SQL)


class Migration(migrations.Migration):
    dependencies = [
        ("superadmin", "0009_active_firm_ids"),
        ("core", "0020_firm_limits"),
        ("teams", "0006_firm_limits_events"),
    ]

    operations = [
        migrations.RunPython(install, migrations.RunPython.noop),
        migrations.CreateModel(
            name="PlatformInvite",
            fields=[
                ("id", models.UUIDField(primary_key=True, serialize=False)),
                ("firm_id", models.UUIDField()),
                ("firm_name", models.CharField(max_length=255, verbose_name="firm")),
                ("email", models.EmailField(max_length=254)),
                ("full_name", models.CharField(max_length=255, verbose_name="name")),
                ("role", models.CharField(choices=[("FIRM_ADMIN", "Firm administrator"), ("SENIOR_CA", "Senior CA"), ("STAFF", "Staff"), ("READ_ONLY", "Read only")], max_length=16)),
                ("make_owner", models.BooleanField(verbose_name="owner")),
                ("created_at", models.DateTimeField()),
                ("expires_at", models.DateTimeField()),
                ("used_at", models.DateTimeField(null=True)),
                ("revoked_at", models.DateTimeField(null=True)),
                ("created_by_email", models.EmailField(max_length=254, null=True, verbose_name="invited by")),
                ("state", models.CharField(max_length=16)),
            ],
            options={
                "verbose_name": "invitation",
                "verbose_name_plural": "invitations",
                "db_table": 'app"."platform_invites',
                "ordering": ["-created_at"],
                "abstract": False,
                "managed": False,
            },
        ),
        migrations.CreateModel(
            name="PlatformFirmStats",
            fields=[
                ("id", models.UUIDField(primary_key=True, serialize=False)),
                ("name", models.CharField(max_length=255)),
                ("is_active", models.BooleanField(verbose_name="in service")),
                ("created_at", models.DateTimeField()),
                ("max_members", models.PositiveIntegerField(null=True, verbose_name="people limit")),
                ("max_clients", models.PositiveIntegerField(null=True, verbose_name="client limit")),
                ("trial_ends_at", models.DateTimeField(null=True, verbose_name="trial ends")),
                ("active_members", models.IntegerField(verbose_name="people")),
                ("pending_invites", models.IntegerField(verbose_name="invites waiting")),
                ("clients", models.IntegerField()),
                ("statements_this_month", models.IntegerField(verbose_name="statements this month")),
                ("last_activity", models.DateTimeField(null=True, verbose_name="last activity")),
                ("failed_jobs_30d", models.IntegerField(verbose_name="failed jobs (30 days)")),
            ],
            options={
                "verbose_name": "firm at a glance",
                "verbose_name_plural": "platform dashboard",
                "db_table": 'app"."platform_firm_stats',
                "ordering": ["name"],
                "abstract": False,
                "managed": False,
            },
        ),
    ]
