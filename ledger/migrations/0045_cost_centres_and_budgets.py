import uuid

import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models

from core.db.rls import ddl_tenant_context_operations, rls_operations

FORWARD = [
    "ALTER TABLE ledger_cost_centre ADD CONSTRAINT uniq_cost_centre_client_id UNIQUE (client_id, id);",
    # A tag names a cost centre of its own client, and a budget a ledger of its own client.
    "ALTER TABLE ledger_cost_centre_tag ADD CONSTRAINT cost_tag_centre_same_client "
    "FOREIGN KEY (client_id, cost_centre_id) REFERENCES ledger_cost_centre (client_id, id) "
    "ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED;",
    "ALTER TABLE ledger_budget ADD CONSTRAINT budget_ledger_same_client "
    "FOREIGN KEY (client_id, ledger_id) REFERENCES classify_ledger_account (client_id, id) "
    "ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED;",
]
REVERSE = [
    "ALTER TABLE ledger_budget DROP CONSTRAINT budget_ledger_same_client;",
    "ALTER TABLE ledger_cost_centre_tag DROP CONSTRAINT cost_tag_centre_same_client;",
    "ALTER TABLE ledger_cost_centre DROP CONSTRAINT uniq_cost_centre_client_id;",
]


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0021_client_gst_return_entries'),
        ('classify', '0009_rules_belong_to_one_client'),
        ('ledger', '0044_employee_uan_esic'),
    ]

    operations = [
        migrations.AlterField(
            model_name='masterchange',
            name='kind',
            field=models.CharField(choices=[('LEDGER', 'Ledger'), ('GROUP', 'Group'), ('PARTY', 'Party'), ('RULE', 'Rule'), ('SETTING', 'Setting'), ('ITEM', 'Stock item'), ('GODOWN', 'Godown'), ('CENTRE', 'Cost centre'), ('BUDGET', 'Budget')], max_length=8),
        ),
        migrations.CreateModel(
            name='CostCentre',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(default=django.utils.timezone.now, editable=False)),
                ('name', models.CharField(max_length=100)),
                ('client', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='cost_centres', to='core.client')),
                ('firm', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='%(class)ss', to='core.firm')),
            ],
            options={'db_table': 'ledger_cost_centre', 'ordering': ['name']},
        ),
        migrations.AddConstraint(
            model_name='costcentre',
            constraint=models.UniqueConstraint(fields=('firm', 'client', 'name'), name='uniq_cost_centre_name'),
        ),
        migrations.CreateModel(
            name='CostCentreTag',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(default=django.utils.timezone.now, editable=False)),
                ('amount_paise', models.BigIntegerField()),
                ('client', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='cost_centre_tags', to='core.client')),
                ('cost_centre', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='tags', to='ledger.costcentre')),
                ('firm', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='%(class)ss', to='core.firm')),
                ('line', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='cost_centre_tags', to='ledger.journalline')),
            ],
            options={'db_table': 'ledger_cost_centre_tag'},
        ),
        migrations.AddConstraint(
            model_name='costcentretag',
            constraint=models.CheckConstraint(condition=models.Q(('amount_paise__gt', 0)), name='ck_cost_tag_positive'),
        ),
        migrations.AddConstraint(
            model_name='costcentretag',
            constraint=models.UniqueConstraint(fields=('line', 'cost_centre'), name='uniq_cost_tag_per_line_centre'),
        ),
        migrations.CreateModel(
            name='Budget',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(default=django.utils.timezone.now, editable=False)),
                ('period', models.DateField()),
                ('amount_paise', models.BigIntegerField()),
                ('client', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='budgets', to='core.client')),
                ('firm', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='%(class)ss', to='core.firm')),
                ('ledger', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='budgets', to='classify.ledgeraccount')),
            ],
            options={'db_table': 'ledger_budget', 'ordering': ['period']},
        ),
        migrations.AddConstraint(
            model_name='budget',
            constraint=models.CheckConstraint(condition=models.Q(('amount_paise__gte', 0)), name='ck_budget_not_negative'),
        ),
        migrations.AddConstraint(
            model_name='budget',
            constraint=models.UniqueConstraint(fields=('firm', 'client', 'ledger', 'period'), name='uniq_budget_ledger_month'),
        ),
        *ddl_tenant_context_operations(),
        migrations.RunSQL(sql=FORWARD, reverse_sql=REVERSE),
        *rls_operations("ledger_cost_centre"),
        *rls_operations("ledger_cost_centre_tag"),
        *rls_operations("ledger_budget"),
    ]
