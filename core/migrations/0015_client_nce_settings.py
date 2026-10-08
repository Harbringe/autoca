from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0014_client_close_period'),
    ]

    operations = [
        migrations.AddField(
            model_name='client',
            name='nce_settings',
            field=models.JSONField(blank=True, db_default={}, default=dict),
        ),
    ]
