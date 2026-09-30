from django.db import migrations, models


class Migration(migrations.Migration):
    """Where a row stands in the model queue: three nullable-or-defaulted columns and one partial index.

    The columns are metadata-only on Postgres 11+ (NULL, and a constant default), so no table
    rewrite. The index is a plain AddIndex rather than a concurrent one: it is partial and no
    row satisfies it until the queue is used, so the build is one scan that writes nothing,
    and a plain AddIndex keeps the migration atomic. Reversible: reversing drops the index and
    the columns.
    """

    dependencies = [
        ("classify", "0014_ai_revised_marker"),
    ]

    operations = [
        migrations.AddField(
            model_name="transactionclassification",
            name="model_state",
            field=models.CharField(
                blank=True,
                choices=[
                    ("waiting", "Waiting for the assistant"),
                    ("claimed", "Being read by the assistant"),
                    ("done", "The assistant suggested a ledger"),
                    ("declined", "Left for a person"),
                ],
                max_length=8,
                null=True,
            ),
        ),
        migrations.AddField(
            model_name="transactionclassification",
            name="model_claimed_until",
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="transactionclassification",
            name="model_attempts",
            field=models.PositiveSmallIntegerField(default=0),
        ),
        migrations.AddIndex(
            model_name="transactionclassification",
            index=models.Index(
                condition=models.Q(("model_state__in", ["waiting", "claimed"])),
                fields=["firm", "model_state"],
                name="idx_classification_model_queue",
            ),
        ),
    ]
