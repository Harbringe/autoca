"""What the books will say, and what only the client can answer.

``book_narration`` is the voucher narration a CA would write; the bank's own
string is evidence, not a narration. ``open_question`` replaces the guess a
row used to get when the evidence ran out.
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("classify", "0007_mirrored_entry"),
    ]

    operations = [
        migrations.AddField(
            model_name="transactionclassification",
            name="book_narration",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="transactionclassification",
            name="open_question",
            field=models.TextField(blank=True, default=""),
        ),
    ]
