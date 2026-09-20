"""Manage the platform layer: its database views and functions, and who owns the platform.

    python manage.py superadmin install          # after running setup_sql/role.sql
    python manage.py superadmin status
    python manage.py superadmin grant you@example.com
    python manage.py superadmin grant you@example.com --create --name "You" --password "..."
    python manage.py superadmin revoke you@example.com
    python manage.py superadmin list

Grants are deliberately not possible from any web page.
"""

from __future__ import annotations

import logging

from django.core.management.base import BaseCommand, CommandError
from django.db import connections, transaction

from core.db.session import _apply_user
from core.models import User
from superadmin import sql
from core.models import FirmMembership

security_log = logging.getLogger("autoca.security")


class Command(BaseCommand):
    help = "Install the platform views and functions, or grant/revoke platform ownership."

    def add_arguments(self, parser):
        parser.add_argument("action", choices=["install", "status", "grant", "revoke", "list"])
        parser.add_argument("email", nargs="?")
        parser.add_argument("--create", action="store_true", help="grant: create the account if missing")
        parser.add_argument("--name", default="", help="grant --create: full name")
        parser.add_argument("--password", default=None, help="grant --create: skip the prompt")
        parser.add_argument("--database", default="owner", help="Alias used by install/status.")

    def handle(self, *args, action, email, database, create, name, password, **options):
        if action in {"install", "status"}:
            return self._install(database, dry=action == "status")
        if action == "list":
            for user in User.objects.filter(is_superuser=True, is_active=True).order_by("email"):
                firms = self._memberships(user)
                state = "super admin" if not firms else f"not a super admin: belongs to {firms} firm(s)"
                self.stdout.write(f"{user.email}\t{state}")
            return
        if not email:
            raise CommandError(f"'{action}' needs an email address.")
        if action == "grant" and create and not User.objects.filter(email=email.strip().lower()).exists():
            from getpass import getpass

            from django.contrib.auth.password_validation import validate_password

            secret = password or getpass(f"Password for {email}: ")
            validate_password(secret)
            User.objects.create_user(email=email.strip().lower(), password=secret, full_name=name)
            self.stdout.write(f"Created account {email.strip().lower()} (no firm).")
        user = self._user(email)
        if action == "grant":
            if self._memberships(user):
                raise CommandError(
                    f"{user.email} belongs to a firm. A super admin belongs to no firm: use a "
                    "separate account (e.g. --create with a new email)."
                )
            user.is_superuser = True
            user.is_staff = True
            user.save(update_fields=["is_superuser", "is_staff"])
            security_log.warning("superadmin granted user=%s", user.pk)
            self.stdout.write(self.style.SUCCESS(f"{user.email} is a super admin."))
        else:
            user.is_superuser = False
            user.is_staff = False
            user.save(update_fields=["is_superuser", "is_staff"])
            security_log.warning("superadmin revoked user=%s", user.pk)
            self.stdout.write(self.style.SUCCESS(f"{user.email} is not a super admin."))

    def _memberships(self, user) -> int:
        with transaction.atomic():
            _apply_user(str(user.pk))
            return FirmMembership.objects.filter(user=user, is_active=True).count()

    def _user(self, email: str) -> User:
        email = email.strip().lower()
        # core_user is not firm-scoped, but set the user context anyway so the
        # lookup behaves the same under any future policy.
        with transaction.atomic():
            user = User.objects.filter(email=email).first()
            if user:
                _apply_user(str(user.pk))
        if not user:
            raise CommandError(f"No user with email {email}.")
        return user

    def _install(self, alias: str, dry: bool):
        with connections[alias].cursor() as cursor:
            usable = sql.reader_role_usable(cursor)
            installed = sql.functions_installed(cursor)
            if dry or not usable:
                self.stdout.write(f"reader role usable: {usable}")
                self.stdout.write(f"functions installed: {installed}")
                self.stdout.write(f"views installed: {sql.views_installed(cursor)}")
                if not usable:
                    self.stdout.write(
                        "Run superadmin/setup_sql/role.sql as the `postgres` role first."
                    )
                return
            cursor.execute(sql.CREATE_SQL)
        self.stdout.write(self.style.SUCCESS("Platform views and directory functions installed."))
