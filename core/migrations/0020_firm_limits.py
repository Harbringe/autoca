from django.db import migrations, models


class Migration(migrations.Migration):
    """What the platform owner has agreed for a firm: limits, a trial end, and the message a suspended firm's people see.

    Every column is nullable or has a database default, so the release still running while this is applied can keep inserting firms.
    """

    dependencies = [
        ('core', '0019_job_queue'),
    ]

    operations = [
        migrations.AddField(
            model_name='firm',
            name='max_members',
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='firm',
            name='max_clients',
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='firm',
            name='trial_ends_at',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='firm',
            name='suspended_message',
            field=models.CharField(blank=True, db_default='', max_length=500),
        ),
    ]
