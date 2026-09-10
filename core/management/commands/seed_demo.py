"""Create a second, unrelated firm so tenant isolation is visible by hand.

Run this after ``bootstrap_admin``. It creates a firm you are *not* a member of,
with its own clients and its own R2 objects. In the Django admin you will still
see only your own firm -- that is the isolation working. To see this firm's rows
you have to go to the Supabase table editor (which connects as a superuser and
bypasses RLS) or a shell that enters its ``firm_context``.

    python manage.py seed_demo
    python manage.py seed_demo --name "Some Other CA" --clients "Client A,Client B"
"""

from __future__ import annotations

import datetime

from django.core.management.base import BaseCommand

from core.db.session import firm_context
from core.models import Client
from core.provisioning import create_client, create_firm

DEFAULT_CLIENTS = ["Infosys BPM", "Wipro Ltd", "Zomato"]


class Command(BaseCommand):
    help = "Create an isolated demo firm + clients + R2 objects for manual review."

    def add_arguments(self, parser):
        parser.add_argument("--name", default="Bharat Associates")
        parser.add_argument(
            "--clients",
            default=",".join(DEFAULT_CLIENTS),
            help="Comma-separated client names",
        )

    def handle(self, *args, **opts):
        from integrations.registry import get_storage

        storage = get_storage()
        names = [c.strip() for c in opts["clients"].split(",") if c.strip()]

        firm = create_firm(opts["name"])
        with firm_context(firm.pk):
            for name in names:
                create_client(firm, name, datetime.date(2026, 4, 1))
            client_ids = list(Client.objects.values_list("id", "name"))

        # One firm-level marker, plus one object per client so the bucket shows
        # the firms/<id>/clients/<id>/ shape the storage adapter builds.
        storage.put(
            storage.tenant_key(firm.pk, "_seed", "firm.txt"),
            f"{firm.name}\n".encode(),
            "text/plain",
        )
        for cid, cname in client_ids:
            key = storage.tenant_key(firm.pk, "clients", str(cid), "_seed.txt")
            storage.put(key, f"{cname}\n".encode(), "text/plain")

        self.stdout.write(self.style.SUCCESS(f"Created isolated firm: {firm.name}"))
        self.stdout.write(f"  firm id   {firm.pk}")
        self.stdout.write(f"  clients   {len(client_ids)}")
        self.stdout.write(f"  R2        firms/{firm.pk}/  (firm marker + one per client)")
        self.stdout.write("")
        self.stdout.write("This firm has no members. Verify the isolation:")
        self.stdout.write("  - Django admin (as your user): this firm's clients do NOT appear")
        self.stdout.write("  - Supabase table editor: they DO (it bypasses RLS as superuser)")
        self.stdout.write(f"  - shell: with firm_context('{firm.pk}'): Client.objects.all()")
