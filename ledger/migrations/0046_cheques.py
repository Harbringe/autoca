import uuid

import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models

from core.db.rls import ddl_tenant_context_operations, rls_operations

FORWARD = [
    "ALTER TABLE banking_bank_account ADD CONSTRAINT uniq_bank_account_client_id UNIQUE (client_id, id);",
    "ALTER TABLE ledger_cheque ADD CONSTRAINT cheque_account_same_client "
    "FOREIGN KEY (client_id, bank_account_id) REFERENCES banking_bank_account (client_id, id) "
    "ON DELETE NO ACTION DEFERRABLE INITIALLY DEFERRED;",
]
REVERSE = [
    "ALTER TABLE ledger_cheque DROP CONSTRAINT cheque_account_same_client;",
    "ALTER TABLE banking_bank_account DROP CONSTRAINT uniq_bank_account_client_id;",
]


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0021_client_gst_return_entries'),
        ('classify', '0009_rules_belong_to_one_client'),
        ('banking', '0004_card_accounts'),
        ('ledger', '0045_cost_centres_and_budgets'),
    ]

    operations = [
        migrations.AlterField(
            model_name='masterchange',
            name='kind',
            field=models.CharField(choices=[('LEDGER', 'Ledger'), ('GROUP', 'Group'), ('PARTY', 'Party'), ('RULE', 'Rule'), ('SETTING', 'Setting'), ('ITEM', 'Stock item'), ('GODOWN', 'Godown'), ('CENTRE', 'Cost centre'), ('BUDGET', 'Budget'), ('CHEQUE', 'Cheque')], max_length=8),
        ),
        migrations.CreateModel(
            name='Cheque',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(default=django.utils.timezone.now, editable=False)),
                ('direction', models.CharField(choices=[('ISSUED', 'Issued by the client'), ('RECEIVED', 'Received by the client')], max_length=8)),
                ('number', models.CharField(max_length=12)),
                ('cheque_date', models.DateField()),
                ('issued_on', models.DateField()),
                ('amount_paise', models.BigIntegerField()),
                ('payee_name', models.CharField(blank=True, db_default='', default='', max_length=200)),
                ('status', models.CharField(choices=[('PENDING', 'Not yet presented'), ('CLEARED', 'Cleared'), ('BOUNCED', 'Bounced'), ('CANCELLED', 'Cancelled')], db_default='PENDING', default='PENDING', max_length=10)),
                ('status_on', models.DateField(blank=True, null=True)),
                ('note', models.CharField(blank=True, db_default='', default='', max_length=300)),
                ('bank_account', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='cheques', to='banking.bankaccount')),
                ('client', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='cheques', to='core.client')),
                ('firm', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='%(class)ss', to='core.firm')),
                ('party', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='cheques', to='classify.party')),
            ],
            options={'db_table': 'ledger_cheque', 'ordering': ['cheque_date', 'number']},
        ),
        migrations.AddConstraint(
            model_name='cheque',
            constraint=models.CheckConstraint(condition=models.Q(('amount_paise__gt', 0)), name='ck_cheque_amount_positive'),
        ),
        migrations.AddConstraint(
            model_name='cheque',
            constraint=models.UniqueConstraint(fields=('firm', 'client', 'bank_account', 'direction', 'number'), name='uniq_cheque_number_per_account'),
        ),
        migrations.AddIndex(
            model_name='cheque',
            index=models.Index(fields=['firm', 'client', 'status', 'cheque_date'], name='idx_cheque_status_date'),
        ),
        *ddl_tenant_context_operations(),
        migrations.RunSQL(sql=FORWARD, reverse_sql=REVERSE),
        *rls_operations("ledger_cheque"),
    ]
