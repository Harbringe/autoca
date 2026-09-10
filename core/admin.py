"""Django admin.

Registered read-mostly and deliberately sparse. The admin runs on the same
low-privilege database role as the rest of the app, so RLS applies to it too --
an admin user sees their own firm and nothing else. That is intentional: a
staff-only console that could read every firm's data would be a single
compromised session away from a full breach.
"""

from django.contrib import admin

from core.models import AuditLog, Client, Firm, FirmMembership, User


@admin.register(Firm)
class FirmAdmin(admin.ModelAdmin):
    list_display = ("name", "is_active", "created_at")
    search_fields = ("name",)


@admin.register(Client)
class ClientAdmin(admin.ModelAdmin):
    list_display = ("name", "firm", "fy_start", "created_at")
    search_fields = ("name",)


@admin.register(FirmMembership)
class FirmMembershipAdmin(admin.ModelAdmin):
    list_display = ("user", "firm", "role", "is_active")
    list_filter = ("role", "is_active")


@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    list_display = ("email", "full_name", "is_active", "is_staff", "last_login")
    search_fields = ("email", "full_name")


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "user", "method", "path", "status_code")
    list_filter = ("method", "status_code")
    readonly_fields = [f.name for f in AuditLog._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
