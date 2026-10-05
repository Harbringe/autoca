"""A bank account can now be a loan account.

Every existing row is a bank account, so the default is BANK and nothing about them changes.
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("banking", "0002_row_level_security")]

    operations = [
        migrations.AddField(
            model_name="bankaccount",
            name="kind",
            field=models.CharField(
                choices=[("BANK", "Bank account"), ("LOAN", "Loan account")],
                db_default="BANK",
                default="BANK",
                max_length=8,
            ),
        ),
    ]
