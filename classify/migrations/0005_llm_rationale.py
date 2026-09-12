"""Where a model-sourced suggestion keeps its reasoning.

One short sentence the reviewer can check, stored beside the suggestion rather
than in a log, because the reviewer is the person it was written for.
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("classify", "0004_vendor_row_level_security"),
    ]

    operations = [
        migrations.AddField(
            model_name="transactionclassification",
            name="rationale",
            field=models.TextField(
                blank=True,
                default="",
                help_text="Why the model suggested what it did, in one sentence a reviewer can check.",
            ),
        ),
    ]
