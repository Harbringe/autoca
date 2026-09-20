"""A firm owner: one flagged firm administrator per firm."""

from django.db import migrations, models

from core.db.rls import ddl_tenant_context_operations


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0007_client_assignment_row_level_security'),
    ]

    operations = [
        *ddl_tenant_context_operations(),
        migrations.AddField(
            model_name='firmmembership',
            name='is_owner',
            field=models.BooleanField(default=False),
        ),
        migrations.AddConstraint(
            model_name='firmmembership',
            constraint=models.UniqueConstraint(condition=models.Q(('is_owner', True)), fields=('firm',), name='uniq_owner_per_firm'),
        ),
    ]
