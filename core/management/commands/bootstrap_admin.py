"""Create a superuser attached to a firm, so the Django admin is reachable.

The admin runs on the low-privilege ``autoca_web`` role under RLS, and
``TenantContextMiddleware`` rejects any authenticated user with no firm
membership. A bare ``createsuperuser`` account therefore gets a 403 on every
page. This command creates the user, a firm, and an OWNER membership in one go.

    python manage.py bootstrap_admin --email you@example.com --firm "Acme & Co CA"
    python manage.py bootstrap_admin --email you@example.com --firm-id <uuid>   # reuse a firm
    #   add --demo to also create three sample clients + an R2 marker object

Then: runserver, open /admin/, log in, and complete the TOTP enrolment page.
"""

from __future__ import annotations

import datetime
import uuid
from getpass import getpass

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from core.db.session import firm_context
from core.models import Firm, FirmMembership, Role
from core.provisioning import create_client, create_firm

MIN_PASSWORD_LEN = 12


class Command(BaseCommand):
    help = "Create a superuser bound to a firm (with an OWNER membership)."

    def add_arguments(self, parser):
        parser.add_argument("--email", required=True)
        parser.add_argument("--firm", help="Firm name to create")
        parser.add_argument("--firm-id", help="Existing firm UUID to reuse instead")
        parser.add_argument("--name", default="", help="User's full name")
        parser.add_argument("--password", default=None, help="Skip the interactive prompt")
        parser.add_argument(
            "--demo",
            action="store_true",
            help="Also create three sample clients and one R2 marker object",
        )

    def handle(self, *args, **opts):
        if not opts["firm"] and not opts["firm_id"]:
            raise CommandError("Pass either --firm 'Name' or --firm-id <uuid>.")

        user_model = get_user_model()
        email = opts["email"].strip().lower()

        password = opts["password"] or getpass(f"Password for {email}: ")
        if len(password) < MIN_PASSWORD_LEN:
            raise CommandError(f"Password must be at least {MIN_PASSWORD_LEN} characters.")

        user, created = user_model.objects.get_or_create(
            email=email, defaults={"full_name": opts["name"]}
        )
        user.is_staff = True
        user.is_superuser = True
        user.set_password(password)
        if opts["name"]:
            user.full_name = opts["name"]
        user.save()

        if opts["firm_id"]:
            fid = uuid.UUID(opts["firm_id"])
            with firm_context(fid):
                firm = Firm.objects.get(pk=fid)
        else:
            firm = create_firm(opts["firm"])

        with firm_context(firm.pk):
            membership, m_created = FirmMembership.objects.get_or_create(
                firm=firm, user=user, defaults={"role": Role.OWNER}
            )
            if opts["demo"]:
                for name in ("Tata Steel Ltd", "Reliance Retail", "HDFC Bank"):
                    create_client(firm, name, datetime.date(2026, 4, 1))

        if opts["demo"]:
            from integrations.registry import get_storage

            storage = get_storage()
            key = storage.tenant_key(firm.pk, "_seed", "hello.txt")
            storage.put(key, f"seed marker for {firm.name}\n".encode(), "text/plain")

        self.stdout.write(self.style.SUCCESS("Ready."))
        self.stdout.write(f"  user       {email}  ({'created' if created else 'updated'}, superuser)")
        self.stdout.write(f"  firm       {firm.name}  ({firm.pk})")
        self.stdout.write(f"  membership OWNER  ({'created' if m_created else 'existing'})")
        if opts["demo"]:
            self.stdout.write("  demo       3 clients + 1 R2 object under firms/<id>/_seed/")
        self.stdout.write("")
        self.stdout.write("Next:")
        self.stdout.write("  python manage.py runserver")
        self.stdout.write("  open http://127.0.0.1:8000/admin/  and sign in")
        self.stdout.write("  you'll land on the TOTP setup page -- scan the QR, enter the code")
