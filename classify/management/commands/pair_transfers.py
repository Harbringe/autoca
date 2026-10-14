"""Find a client's transfers between its own accounts among rows nobody has decided yet.

    python manage.py pair_transfers --firm <uuid> --client "Acme"           # a preview: nothing is written
    python manage.py pair_transfers --firm <uuid> --client "Acme" --apply

Each side of a pair is placed in the other account's ledger, so approving either one posts a single Contra. Rows a person or a rule has
placed, and rows already in the books, are never touched.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from classify.transfers import pair_own_transfers
from core.db.session import firm_context
from core.models import Client


class Command(BaseCommand):
    help = "Pair a client's transfers between its own accounts (preview unless --apply)."

    def add_arguments(self, parser):
        parser.add_argument("--firm", required=True)
        parser.add_argument("--client", required=True)
        parser.add_argument("--apply", action="store_true", help="Place the rows. Without it, only say what would be paired.")

    def handle(self, *args, firm, client, apply, **options):
        with firm_context(firm):
            try:
                record = Client.objects.get(firm_id=firm, name=client)
            except Client.DoesNotExist:
                raise CommandError(f"No client called {client!r} in that firm.") from None
            pairs = pair_own_transfers(record, apply=apply)
            by_strength: dict[str, int] = {}
            for pair in pairs:
                by_strength[pair.strength] = by_strength.get(pair.strength, 0) + 1
            verb = "Paired" if apply else "Would pair"
            self.stdout.write(f"{verb} {len(pairs)} transfer(s): {by_strength}")
