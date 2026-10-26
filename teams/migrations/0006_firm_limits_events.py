from django.db import migrations, models


class Migration(migrations.Migration):
    """Two more kinds of team event: an invite link replaced, and a firm's limits changed by the platform owner."""

    dependencies = [
        ('teams', '0005_reporting_hierarchy'),
    ]

    operations = [
        migrations.AlterField(
            model_name='teamevent',
            name='kind',
            field=models.CharField(choices=[('member.invited', 'Invited'), ('member.joined', 'Joined'), ('invite.revoked', 'Invite revoked'), ('member.role_changed', 'Role changed'), ('firm.owner_changed', 'Ownership transferred'), ('firm.renamed', 'Firm renamed'), ('member.manager_changed', 'Moved to another team'), ('member.scope_changed', 'All-clients access changed'), ('member.deactivated', 'Deactivated'), ('member.removed', 'Removed from firm'), ('member.reactivated', 'Reactivated'), ('client.lead_changed', 'Client lead changed'), ('client.assigned', 'Assigned to client'), ('client.unassigned', 'Removed from client'), ('invite.reissued', 'Invite link replaced'), ('invite.extended', 'Invite extended'), ('firm.limits_changed', 'Firm limits changed')], max_length=32),
        ),
    ]
