import uuid

import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models

from core.db.rls import ddl_tenant_context_operations, rls_operations


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0021_client_gst_return_entries'),
        ('ledger', '0046_cheques'),
    ]

    operations = [
        migrations.AlterField(
            model_name='masterchange',
            name='kind',
            field=models.CharField(choices=[('LEDGER', 'Ledger'), ('GROUP', 'Group'), ('PARTY', 'Party'), ('RULE', 'Rule'), ('SETTING', 'Setting'), ('ITEM', 'Stock item'), ('GODOWN', 'Godown'), ('CENTRE', 'Cost centre'), ('BUDGET', 'Budget'), ('CHEQUE', 'Cheque'), ('BOM', 'Bill of materials')], max_length=8),
        ),
        migrations.AlterField(
            model_name='stockentry',
            name='kind',
            field=models.CharField(choices=[('OPENING', 'Opening stock'), ('ADJUSTMENT', 'Stock adjustment'), ('TALLY', 'Imported from Tally'), ('TRANSFER', 'Stock transfer'), ('PRODUCTION', 'Production')], max_length=12),
        ),
        migrations.AddField(
            model_name='stockentry',
            name='production',
            field=models.UUIDField(blank=True, db_index=True, null=True),
        ),
        migrations.CreateModel(
            name='BillOfMaterials',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(default=django.utils.timezone.now, editable=False)),
                ('name', models.CharField(help_text='The finished item.', max_length=200)),
                ('unit', models.CharField(blank=True, db_default='', default='', max_length=16)),
                ('output_quantity', models.DecimalField(decimal_places=3, default=1, max_digits=18)),
                ('components', models.JSONField(default=list)),
                ('client', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='boms', to='core.client')),
                ('firm', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='%(class)ss', to='core.firm')),
            ],
            options={'db_table': 'ledger_bom', 'ordering': ['name']},
        ),
        migrations.AddConstraint(
            model_name='billofmaterials',
            constraint=models.UniqueConstraint(fields=('firm', 'client', 'name'), name='uniq_bom_name'),
        ),
        migrations.AddConstraint(
            model_name='billofmaterials',
            constraint=models.CheckConstraint(condition=models.Q(('output_quantity__gt', 0)), name='ck_bom_output_positive'),
        ),
        *ddl_tenant_context_operations(),
        *rls_operations("ledger_bom"),
    ]
