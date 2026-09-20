"""Invites, the work log, and team history. Isolation follows in 0002."""

import django.db.models.deletion
import django.utils.timezone
import uuid
from django.conf import settings
from django.db import migrations, models

from core.db.rls import ddl_tenant_context_operations


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ('core', '0007_client_assignment_row_level_security'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        *ddl_tenant_context_operations(),
        migrations.CreateModel(
            name='Invite',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(default=django.utils.timezone.now, editable=False)),
                ('email', models.EmailField(max_length=254)),
                ('full_name', models.CharField(blank=True, max_length=255)),
                ('role', models.CharField(choices=[('FIRM_ADMIN', 'Firm administrator'), ('SENIOR_CA', 'Senior CA'), ('STAFF', 'Staff'), ('READ_ONLY', 'Read only')], default='STAFF', max_length=16)),
                ('token_hash', models.CharField(max_length=64, unique=True)),
                ('expires_at', models.DateTimeField()),
                ('used_at', models.DateTimeField(blank=True, null=True)),
                ('revoked_at', models.DateTimeField(blank=True, null=True)),
                ('accepted_membership', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to='core.firmmembership')),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('firm', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='%(class)ss', to='core.firm')),
                ('manager', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='+', to='core.firmmembership')),
            ],
            options={
                'db_table': 'teams_invite',
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='ActivityEvent',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(default=django.utils.timezone.now, editable=False)),
                ('user_id', models.UUIDField(db_index=True)),
                ('client_id', models.UUIDField(blank=True, null=True)),
                ('kind', models.CharField(choices=[('row.placed', 'Rows placed'), ('ledger.created', 'Ledgers created'), ('rule.created', 'Rules written by hand'), ('proposal.decided', 'Ledger proposals decided'), ('model.run', 'Model runs')], max_length=32)),
                ('quantity', models.PositiveIntegerField(default=1)),
                ('subject_id', models.UUIDField(blank=True, null=True)),
                ('firm', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='%(class)ss', to='core.firm')),
            ],
            options={
                'db_table': 'teams_activity_event',
                'ordering': ['-created_at'],
                'indexes': [models.Index(fields=['firm', 'user_id', 'created_at'], name='idx_activity_user'), models.Index(fields=['firm', 'client_id', 'created_at'], name='idx_activity_client')],
            },
        ),
        migrations.CreateModel(
            name='TeamEvent',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(default=django.utils.timezone.now, editable=False)),
                ('kind', models.CharField(choices=[('member.invited', 'Invited'), ('member.joined', 'Joined'), ('invite.revoked', 'Invite revoked'), ('member.role_changed', 'Role changed'), ('member.manager_changed', 'Moved to another team'), ('member.scope_changed', 'All-clients access changed'), ('member.deactivated', 'Deactivated'), ('member.reactivated', 'Reactivated'), ('client.lead_changed', 'Client lead changed'), ('client.assigned', 'Assigned to client'), ('client.unassigned', 'Removed from client')], max_length=32)),
                ('actor_id', models.UUIDField(blank=True, null=True)),
                ('member_id', models.UUIDField(blank=True, db_index=True, null=True)),
                ('client_id', models.UUIDField(blank=True, db_index=True, null=True)),
                ('detail', models.JSONField(blank=True, default=dict)),
                ('firm', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='%(class)ss', to='core.firm')),
            ],
            options={
                'db_table': 'teams_team_event',
                'ordering': ['-created_at'],
                'indexes': [models.Index(fields=['firm', '-created_at'], name='idx_team_event_firm')],
            },
        ),
    ]
