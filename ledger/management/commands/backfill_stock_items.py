"""Create stock items for the products already on a client's booked invoices.

    python manage.py backfill_stock_items --firm <uuid> --client "Acme"          # a preview: nothing is written
    python manage.py backfill_stock_items --firm <uuid> --client "Acme" --apply

Only the item master is created, from the lines of invoices behind booked purchases and sales. No bill is re-posted and no ledger
is opened or changed, so the books do not move.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from core.db.session import firm_context
from core.models import Client
from ledger import item_ledgers
from ledger.invoice_intake import fields_of
from ledger.models import Bill, BillKind, InvoiceReading, StockItem


class Command(BaseCommand):
    help = "Create stock items from the lines of booked invoices (no postings)."

    def add_arguments(self, parser):
        parser.add_argument("--firm", required=True)
        parser.add_argument("--client", required=True)
        parser.add_argument("--apply", action="store_true", help="Write the items. Without it, only say what would be created.")

    def handle(self, *args, firm, client, apply, **options):
        with firm_context(firm):
            try:
                record = Client.objects.get(firm_id=firm, name=client)
            except Client.DoesNotExist:
                raise CommandError(f"No client called {client!r} in that firm.") from None
            bills = Bill.objects.filter(
                firm_id=firm, client=record, kind__in=(BillKind.PURCHASE, BillKind.SALES)
            ).values_list("pk", flat=True)
            seen: list[str] = []
            for reading in InvoiceReading.objects.filter(firm_id=firm, client=record, bill_id__in=list(bills)):
                for line in fields_of(reading).get("items") or []:
                    description = str(line.get("description") or "").strip()
                    if not description:
                        continue
                    before = StockItem.objects.filter(firm_id=firm, client=record).count()
                    if apply:
                        item = item_ledgers.item_for(record, description, str(line.get("unit") or ""), str(line.get("hsn_sac") or ""))
                        if StockItem.objects.filter(firm_id=firm, client=record).count() > before:
                            seen.append(item.name)
                    elif description not in seen:
                        seen.append(description)
            verb = "Created" if apply else "Would create (roughly, before matching similar names)"
            self.stdout.write(f"{verb}: {len(seen)} item(s)")
            for name in seen[:50]:
                self.stdout.write(f"  {name}")
