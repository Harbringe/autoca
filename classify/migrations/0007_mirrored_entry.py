"""The other side of a transfer between a client's own accounts, recorded once."""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("classify", "0006_ledger_proposals"),
    ]

    operations = [
        migrations.AddField(
            model_name="transactionclassification",
            name="mirrored_entry_id",
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
    ]
