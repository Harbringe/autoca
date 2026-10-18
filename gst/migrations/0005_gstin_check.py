import uuid

import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("core", "0012_client_business_profile"),
        ("gst", "0004_run_register_from_books"),
    ]

    operations = [
        migrations.CreateModel(
            name="GstinCheck",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now, editable=False)),
                ("gstin_enc", models.BinaryField(blank=True, null=True)),
                ("gstin_hash", models.CharField(blank=True, db_index=True, max_length=64)),
                ("status", models.CharField(blank=True, db_default="", default="", max_length=24)),
                ("details_enc", models.BinaryField(blank=True, null=True)),
                ("provider", models.CharField(blank=True, db_default="", default="", max_length=32)),
                ("checked_at", models.DateTimeField()),
                ("counted_month", models.DateField(blank=True, null=True)),
                ("month_lookups", models.PositiveIntegerField(db_default=0, default=0)),
                (
                    "firm",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE, related_name="%(class)ss", to="core.firm"
                    ),
                ),
            ],
            options={"db_table": "gst_gstin_check"},
        ),
        migrations.AddConstraint(
            model_name="gstincheck",
            constraint=models.UniqueConstraint(fields=("firm", "gstin_hash"), name="uniq_gstin_check_per_firm"),
        ),
    ]
