"""Team structure: client leads, reporting lines, client assignments.

Both new foreign keys are nullable and start empty, so the validation scan
under the DDL context (which sees no rows) has nothing to miss. Isolation for
the new table follows in 0007.
"""

import uuid

import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models

from core.db.rls import ddl_tenant_context_operations


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0005_job_row_level_security'),
    ]

    operations = [
        *ddl_tenant_context_operations(),
        migrations.AddField(
            model_name='client',
            name='lead',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='led_clients', to='core.firmmembership'),
        ),
        migrations.AddField(
            model_name='firmmembership',
            name='manager',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='reports', to='core.firmmembership'),
        ),
        migrations.CreateModel(
            name='ClientAssignment',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(default=django.utils.timezone.now, editable=False)),
                ('assigned_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('client', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='assignments', to='core.client')),
                ('firm', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='%(class)ss', to='core.firm')),
                ('membership', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='assignments', to='core.firmmembership')),
            ],
            options={
                'db_table': 'core_client_assignment',
                'ordering': ['created_at'],
                'constraints': [models.UniqueConstraint(fields=('client', 'membership'), name='uniq_assignment_per_client_member')],
            },
        ),
    ]
