"""Every row remembers what the system worked out about its counterparty.

Two plain columns with a default, added by ``ALTER TABLE ... ADD COLUMN`` --
catalogue-only DDL, so the append-only trigger on this table (see
``classify.migrations.0010``'s neighbour tables and ``ledger.models``'
explanation of the same pattern) never fires, and no validating scan is
needed because neither column references anything.

``party_candidates`` holds suggestions, not facts. It exists so a reviewer
sees *why* a row might be a known party -- a similarity score, or the model's
own reasoning -- without that suggestion ever having been trusted enough to
set ``party`` on its own. See ``classify.parties`` for the rule this is built
on: a fact resolves, a resemblance only ever suggests.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('classify', '0012_party_alias_row_level_security'),
    ]

    operations = [
        migrations.AddField(
            model_name='transactionclassification',
            name='party_candidates',
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name='transactionclassification',
            name='party_resolution',
            field=models.CharField(blank=True, choices=[('AUTO', 'Recognised from a fact -- an account number or GSTIN'), ('CANDIDATE', 'Looks similar to a known party -- needs confirming'), ('NEW', 'No known party looks like this'), ('CONFIRMED', 'A person has confirmed which party this is')], default='', max_length=16),
        ),
    ]
