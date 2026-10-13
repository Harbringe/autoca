"""A ledger the assistant thought a row belongs in but was not sure enough to open: shown to a person, never created on its own.

Two plain columns, with a database default so adding them to a populated, row-level-secured table needs no rewrite (the pattern
``bill_status`` used). Old code runs against a database that has them; the reverse is not true, so this is deployed before the
code that reads it.
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("classify", "0023_msme_and_note_section")]

    operations = [
        migrations.AddField(
            model_name="transactionclassification",
            name="suggested_ledger_name",
            field=models.CharField(blank=True, db_default="", default="", max_length=255),
        ),
        migrations.AddField(
            model_name="transactionclassification",
            name="suggested_ledger_group",
            field=models.CharField(blank=True, db_default="", default="", max_length=32),
        ),
    ]
