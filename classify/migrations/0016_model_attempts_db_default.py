from django.db import migrations, models


class Migration(migrations.Migration):
    """Give model_attempts a default in the database, not only in Python.

    0015 added the column NOT NULL with a Python-only default, so the release that does not
    know the column cannot insert into the table. This sets the column default in Postgres
    (ALTER COLUMN ... SET DEFAULT 0): metadata only, no rewrite, and harmless if the same
    statement was already run by hand. Reversible: reversing drops the default again.
    """

    dependencies = [
        ("classify", "0015_model_queue"),
    ]

    operations = [
        migrations.AlterField(
            model_name="transactionclassification",
            name="model_attempts",
            field=models.PositiveSmallIntegerField(db_default=0, default=0),
        ),
    ]
