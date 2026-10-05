"""The records that go with a working draft: a marker, a review history, a change log.

Tables only. Their row-level security is in 0007 and the new locking rules in
0008, for the reason ``core.db.rls.rls_operations`` gives: Django holds foreign
key SQL back until the schema editor closes, so a policy added in the same
migration is applied before the keys are and the keys' validation then dies on
``tenant context missing``.
"""

import uuid

import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models

from core.db.rls import ddl_tenant_context_operations


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0011_client_signed_off_through'),
        ('ledger', '0005_journal_line_names_a_party'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        # First, so the new tables' foreign keys validate. Harmless here: both
        # tables are created empty in this migration, so there is nothing for
        # the scan to have missed.
        *ddl_tenant_context_operations(),
        migrations.AddField(
            model_name='journalentry',
            name='marker',
            field=models.CharField(blank=True, choices=[('', 'No marker'), ('AI_POSTED', 'Posted by the AI'), ('AI_REVISED', 'Changed by the AI after a correction')], default='', max_length=12),
        ),
        migrations.CreateModel(
            name='BooksEvent',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(default=django.utils.timezone.now, editable=False)),
                ('action', models.CharField(choices=[('REQUESTED', 'Approval requested'), ('RETURNED', 'Returned for changes'), ('SIGNED_OFF', 'Signed off'), ('REOPENED', 'Reopened')], max_length=12)),
                ('through_date', models.DateField(blank=True, null=True)),
                ('note', models.TextField(blank=True, default='')),
                ('actor', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('client', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='books_events', to='core.client')),
                ('firm', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='%(class)ss', to='core.firm')),
            ],
            options={
                'db_table': 'ledger_books_event',
                'ordering': ['created_at'],
                'indexes': [models.Index(fields=['firm', 'client', 'created_at'], name='idx_books_event')],
            },
        ),
        migrations.CreateModel(
            name='EntryChange',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('created_at', models.DateTimeField(default=django.utils.timezone.now, editable=False)),
                ('entry_id', models.UUIDField(db_index=True)),
                ('voucher_type', models.CharField(max_length=16)),
                ('entry_no', models.PositiveIntegerField()),
                ('entry_date', models.DateField()),
                ('action', models.CharField(choices=[('EDITED', 'Ledger changed'), ('REMOVED', 'Entry removed'), ('AI_REVISED', 'Revised by the AI after a correction'), ('RENUMBERED', 'Voucher renumbered at sign-off')], max_length=12)),
                ('before', models.JSONField(default=dict)),
                ('after', models.JSONField(blank=True, default=dict)),
                ('note', models.TextField(blank=True, default='')),
                ('actor', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT, related_name='+', to=settings.AUTH_USER_MODEL)),
                ('client', models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name='entry_changes', to='core.client')),
                ('firm', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='%(class)ss', to='core.firm')),
            ],
            options={
                'db_table': 'ledger_entry_change',
                'ordering': ['created_at'],
                'indexes': [models.Index(fields=['firm', 'client', 'created_at'], name='idx_entry_change')],
            },
        ),
    ]
