"""Ledgers a model proposed, awaiting a CA's acceptance."""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("classify", "0005_llm_rationale"),
    ]

    operations = [
        migrations.AddField(
            model_name="ledgeraccount",
            name="status",
            field=models.CharField(
                choices=[
                    ("ACTIVE", "In use"),
                    ("PROPOSED", "Proposed, awaiting a CA"),
                    ("REJECTED", "Rejected by a CA"),
                ],
                default="ACTIVE",
                max_length=16,
            ),
        ),
        migrations.AddField(
            model_name="ledgeraccount",
            name="proposal_reason",
            field=models.TextField(blank=True, default=""),
        ),
    ]
