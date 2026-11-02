from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('ledger', '0042_godowns_and_transfers'),
    ]

    operations = [
        migrations.AddField(
            model_name='stockitem',
            name='aliases',
            field=models.JSONField(blank=True, db_default=[], default=list),
        ),
    ]
