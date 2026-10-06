"""The admin site itself, and who may open it.

Separate from ``core.admin`` because ``INSTALLED_APPS`` names the ``AppConfig``
below, so Django imports this module while the app registry is still being
built. Nothing here may import a model at module level; the registrations that
do live in ``core.admin`` and ``superadmin.admin``, which Django autodiscovers
once the registry is ready.

**Who may open it.** Django asks only for ``is_staff``. That is too generous in
a multi-tenant product: a firm's own administrator is staff of their firm, not
of the platform, and the admin edits rows with none of the app's guard rails in
front of them. So the gate is a dotted path in settings, ``ADMIN_ACCESS``, of
the same shape as ``FIRMLESS_ACCESS`` -- ``core`` must not import the platform
add-on, and a setting keeps that true. With nothing configured the site falls
back to Django's own rule, so removing the add-on leaves a working admin rather
than a locked one.

**No firm is chosen here.** An earlier version made the owner pick a firm before
any firm-scoped page would open, and every request then ran inside that firm's
tenant context. It meant the Firms page listed one firm and a fresh install
looked empty. Lists now read across firms through the gated views in
``superadmin/sql.py``, and each write opens the context of the one firm it
changes, at the moment it changes it.
"""

import unicodedata

from django.conf import settings
from django.contrib import admin
from django.contrib.admin.apps import AdminConfig
from django.http import HttpResponse
from django.utils.module_loading import import_string


class PlatformAdminSite(admin.AdminSite):
    """An admin site only the platform owner can open."""

    site_header = "AutoCA platform"
    site_title = "AutoCA platform"
    index_title = "Platform administration"

    def has_permission(self, request):
        if not super().has_permission(request):
            return False
        path = getattr(settings, "ADMIN_ACCESS", None)
        if not path:
            # No add-on configured: Django's own is_staff rule stands.
            return True
        return bool(import_string(path)(request.user))

    def login(self, request, extra_context=None):
        """The admin's own password form, behind the same brake as the app's login.

        Django's form has no limit of its own, and ``/admin/`` is reachable from the internet. The counter is the one the
        app's login uses (keyed on the account), so a locked account is locked on both doors. The second factor still
        follows the password; this is the missing brake on the first step.
        """
        from core import throttle

        # Read the account the way the form and the backend do (NFKC, then strip and lower), so spellings that sign in
        # as one account share one counter instead of each getting its own.
        typed = unicodedata.normalize("NFKC", str(request.POST.get("username", ""))) if request.method == "POST" else ""
        account = typed.strip().lower()[:254]
        if account:
            try:
                throttle.check("login", account)
            except throttle.Throttled as exc:
                response = HttpResponse("Too many attempts. Try again later.", status=429, content_type="text/plain")
                response["Retry-After"] = str(exc.retry_after)
                return response
        response = super().login(request, extra_context)
        # A good password redirects; the form coming back to a POST means it was refused.
        if account and request.method == "POST" and response.status_code == 200:
            throttle.record_failure("login", account)
        return response


class PlatformAdminConfig(AdminConfig):
    default_site = "core.adminsite.PlatformAdminSite"
