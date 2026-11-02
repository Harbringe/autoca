from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0020_firm_limits'),
    ]

    operations = [
        migrations.AddField(
            model_name='client',
            name='gst_return_entries',
            field=models.JSONField(blank=True, db_default={}, default=dict),
        ),
    ]
