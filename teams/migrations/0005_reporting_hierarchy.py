from django.db import migrations


def backfill_reporting_lines(apps, schema_editor):
    FirmMembership = apps.get_model("core", "FirmMembership")
    db = schema_editor.connection.alias
    firms = FirmMembership.objects.using(db).values_list("firm_id", flat=True).distinct()
    for firm_id in firms.iterator():
        active_admins = list(
            FirmMembership.objects.using(db)
            .filter(firm_id=firm_id, role="FIRM_ADMIN", is_active=True)
            .order_by("-is_owner", "created_at")
        )
        owner = next((member for member in active_admins if member.is_owner), None)
        parent_admin = owner or (active_admins[0] if active_admins else None)
        if owner:
            FirmMembership.objects.using(db).filter(
                firm_id=firm_id, role="FIRM_ADMIN", is_owner=False, manager__isnull=True
            ).update(manager_id=owner.pk)
        if parent_admin:
            FirmMembership.objects.using(db).filter(
                firm_id=firm_id, role="SENIOR_CA", manager__isnull=True
            ).update(manager_id=parent_admin.pk)
        seniors = list(
            FirmMembership.objects.using(db)
            .filter(firm_id=firm_id, role="SENIOR_CA", is_active=True)
            .order_by("created_at")
            .values_list("pk", "manager_id")
        )
        if seniors:
            senior_by_manager = {}
            for senior_id, manager_id in seniors:
                if manager_id is not None:
                    senior_by_manager.setdefault(manager_id, senior_id)
            members = FirmMembership.objects.using(db).filter(
                firm_id=firm_id, role__in=("STAFF", "READ_ONLY")
            ).values_list("pk", "manager_id")
            managers = {
                pk: (role, is_active, manager_id)
                for pk, role, is_active in FirmMembership.objects.using(db)
                .filter(firm_id=firm_id)
                .values_list("pk", "role", "is_active", "manager_id")
            }
            for member_id, old_manager_id in members.iterator():
                old_manager = managers.get(old_manager_id)
                if old_manager is None:
                    continue
                if old_manager[0] == "SENIOR_CA" and old_manager[1]:
                    continue
                parent_admin = old_manager_id if old_manager[0] == "FIRM_ADMIN" else old_manager[2]
                senior_id = senior_by_manager.get(parent_admin)
                if senior_id is None:
                    continue
                if old_manager_id != senior_id:
                    FirmMembership.objects.using(db).filter(pk=member_id).update(manager_id=senior_id)


class Migration(migrations.Migration):
    dependencies = [("teams", "0004_member_removed_event"), ("core", "0012_client_business_profile")]

    operations = [migrations.RunPython(backfill_reporting_lines, migrations.RunPython.noop)]
