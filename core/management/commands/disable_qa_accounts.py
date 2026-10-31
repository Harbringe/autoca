"""Turn off the synthetic QA accounts (qa.admin@autoca.test and the like) wherever they exist.

These accounts were created by ``scripts/qa_seed.py`` for the reviewers, and the password they had was committed to a public
repository. They must not be usable on any database a deployed app serves. By default this only lists them; ``--apply`` makes each
one inactive with no usable password, and ends their firm memberships' access by leaving the accounts unable to sign in. Nothing is
deleted, because the audit trail is append-only and points at these accounts.

    python manage.py disable_qa_accounts            # list what it would turn off
    python manage.py disable_qa_accounts --apply    # turn them off
"""

from __future__ import annotations

import re

from django.core.management.base import BaseCommand

from core.models import User

#: Exactly the addresses the seed script makes: qa.<role>@autoca.test.
QA_ADDRESS = re.compile(r"^qa\.[a-z]+@autoca\.test$")


class Command(BaseCommand):
    help = "List the synthetic QA accounts, and with --apply turn them off (inactive, no usable password)."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Turn them off. Without this, only list them.")

    def handle(self, *args, apply=False, **options):
        found = [u for u in User.objects.filter(email__iendswith="@autoca.test").order_by("email") if QA_ADDRESS.match(u.email.lower())]
        if not found:
            self.stdout.write("No QA accounts here.")
            return
        for user in found:
            state = "active" if user.is_active and user.has_usable_password() else "already off"
            self.stdout.write(f"{user.email}: {state}")
            if apply and (user.is_active or user.has_usable_password()):
                user.is_active = False
                user.set_unusable_password()
                user.save(update_fields=["is_active", "password"])
        self.stdout.write("Turned off." if apply else "Nothing changed. Run again with --apply to turn them off.")
