"""Bank accounts, statements, and the rows read out of them.

Schema only. Tenant isolation is applied in the next migration, and it has to
be -- see the note there for why it cannot live in this one.

The ``ddl_tenant_context_operations()`` call at the top is load-bearing: these
tables carry foreign keys to ``core_client`` and ``core_firm``, which are
already behind FORCE ROW LEVEL SECURITY, and PostgreSQL's foreign key
validation scan reads the parent table. Without a tenant context that scan
raises and the migration dies. See core/db/rls.py.
"""

import django.db.models.deletion
import django.utils.timezone
import uuid
from django.db import migrations, models

from core.db.rls import ddl_tenant_context_operations


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('core', '0002_row_level_security'),
    ]

    operations = [
        *ddl_tenant_context_operations(),
        migrations.CreateModel(
            name='BankAccount',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(default=django.utils.timezone.now, editable=False)),
                ('bank_code', models.CharField(help_text='Parser identifier, e.g. AXIS.', max_length=16)),
                ('account_number', models.CharField(max_length=32)),
                ('ifsc', models.CharField(blank=True, max_length=16)),
                ('ledger_name', models.CharField(blank=True, max_length=255)),
                ('is_active', models.BooleanField(default=True)),
                ('client', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='bank_accounts', to='core.client')),
                ('firm', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='%(class)ss', to='core.firm')),
            ],
            options={
                'db_table': 'banking_bank_account',
                'ordering': ['bank_code', 'account_number'],
            },
        ),
        migrations.CreateModel(
            name='Statement',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(default=django.utils.timezone.now, editable=False)),
                ('source_filename', models.CharField(blank=True, max_length=255)),
                ('source_sha256', models.CharField(db_index=True, max_length=64)),
                ('storage_key', models.CharField(blank=True, max_length=512)),
                ('period_start', models.DateField()),
                ('period_end', models.DateField()),
                ('opening_balance', models.DecimalField(decimal_places=2, max_digits=18)),
                ('closing_balance', models.DecimalField(decimal_places=2, max_digits=18)),
                ('total_debit', models.DecimalField(decimal_places=2, max_digits=18)),
                ('total_credit', models.DecimalField(decimal_places=2, max_digits=18)),
                ('transaction_count', models.PositiveIntegerField(default=0)),
                ('parser', models.CharField(blank=True, max_length=64)),
                ('page_count', models.PositiveSmallIntegerField(default=0)),
                ('bank_account', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='statements', to='banking.bankaccount')),
                ('firm', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='%(class)ss', to='core.firm')),
            ],
            options={
                'db_table': 'banking_statement',
                'ordering': ['-period_end', '-created_at'],
            },
        ),
        migrations.CreateModel(
            name='StatementTransaction',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(default=django.utils.timezone.now, editable=False)),
                ('row_number', models.PositiveIntegerField(help_text='1-based position within the statement.')),
                ('value_date', models.DateField()),
                ('narration', models.TextField(help_text="The bank's particulars, line wrapping removed.")),
                ('cheque_number', models.CharField(blank=True, max_length=32)),
                ('debit', models.DecimalField(decimal_places=2, default=0, max_digits=18)),
                ('credit', models.DecimalField(decimal_places=2, default=0, max_digits=18)),
                ('balance', models.DecimalField(decimal_places=2, max_digits=18)),
                ('branch_code', models.CharField(blank=True, max_length=16)),
                ('dedupe_hash', models.CharField(max_length=64)),
                ('bank_account', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='transactions', to='banking.bankaccount')),
                ('firm', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='%(class)ss', to='core.firm')),
                ('statement', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='transactions', to='banking.statement')),
            ],
            options={
                'db_table': 'banking_statement_transaction',
                'ordering': ['value_date', 'row_number'],
            },
        ),
        migrations.AddConstraint(
            model_name='bankaccount',
            constraint=models.UniqueConstraint(fields=('firm', 'client', 'bank_code', 'account_number'), name='uniq_bank_account_per_client'),
        ),
        migrations.AddIndex(
            model_name='statement',
            index=models.Index(fields=['firm', 'bank_account', 'period_start'], name='idx_stmt_account_period'),
        ),
        migrations.AddConstraint(
            model_name='statement',
            constraint=models.UniqueConstraint(fields=('firm', 'bank_account', 'source_sha256'), name='uniq_statement_per_source_file'),
        ),
        migrations.AddIndex(
            model_name='statementtransaction',
            index=models.Index(fields=['firm', 'bank_account', 'value_date'], name='idx_txn_account_date'),
        ),
        migrations.AddConstraint(
            model_name='statementtransaction',
            constraint=models.UniqueConstraint(fields=('firm', 'statement', 'row_number'), name='uniq_transaction_row_per_statement'),
        ),
        migrations.AddConstraint(
            model_name='statementtransaction',
            constraint=models.UniqueConstraint(fields=('firm', 'bank_account', 'dedupe_hash'), name='uniq_transaction_per_account'),
        ),
        migrations.AddConstraint(
            model_name='statementtransaction',
            constraint=models.CheckConstraint(condition=models.Q(('debit__gte', 0), ('credit__gte', 0)), name='ck_transaction_amounts_non_negative'),
        ),
        migrations.AddConstraint(
            model_name='statementtransaction',
            constraint=models.CheckConstraint(condition=models.Q(models.Q(('debit__gt', 0), ('credit', 0)), models.Q(('debit', 0), ('credit__gt', 0)), _connector='OR'), name='ck_transaction_is_one_sided'),
        ),
    ]
