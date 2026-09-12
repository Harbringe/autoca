"""Work the review queue from the terminal.

A stand-in for the screen that does not exist yet, and useful past that point
for checking what the screen would show. Three things, deliberately in one
command so the listing and the decision share their addressing:

    python manage.py review --firm <uuid> --client "Acme"
    python manage.py review --firm <uuid> --client "Acme" --band JUDGEMENT
    python manage.py review --firm <uuid> --client "Acme" --place 12 --ledger "Rent" --group INDIRECT_EXPENSE

Rows are addressed by the number the listing prints, which is stable for as
long as the queue is unchanged. Placing a row teaches a rule from it, exactly
as the screen will, so the queue usually shrinks by more than one.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from classify.engine import (
    pending_approval,
    review,
    review_queue,
    review_summary,
    unresolved_for,
    vendor_for,
)
from classify.models import LedgerAccount, LedgerGroup
from classify.treatment import ReviewBand, Treatment
from core.db.session import firm_context
from core.models import Client
from core.money import format_inr

BANDS = (ReviewBand.HIGH, ReviewBand.ADVISED, ReviewBand.JUDGEMENT)


class Command(BaseCommand):
    help = "List the review queue, or place one row in a ledger."

    def add_arguments(self, parser):
        parser.add_argument("--firm", required=True, help="Firm id (UUID).")
        parser.add_argument("--client", required=True, help="Client name.")
        parser.add_argument("--band", choices=BANDS, help="Show only one confidence band.")
        parser.add_argument("--limit", type=int, default=40)

        parser.add_argument("--place", type=int, help="Row number from the listing.")
        parser.add_argument("--ledger", help="Ledger head to place it in.")
        parser.add_argument(
            "--group",
            choices=[c[0] for c in LedgerGroup.choices],
            default=LedgerGroup.INDIRECT_EXPENSE,
            help="Tally group, used only when the ledger is being created.",
        )
        parser.add_argument("--vendor", help="Party name, if there is an identifiable one.")
        parser.add_argument("--rcm", action="store_true", help="Reverse charge applies.")
        parser.add_argument("--tds", default="", help='TDS section, e.g. "194J".')
        parser.add_argument(
            "--only-this-row",
            action="store_true",
            help="Do not learn a rule from this decision.",
        )

    def handle(self, *args, **options):
        with firm_context(options["firm"]) as firm_id:
            client = Client.objects.filter(name=options["client"]).first()
            if client is None:
                raise CommandError(f"Firm {firm_id} has no client named {options['client']!r}.")

            if options["place"] is not None:
                self._place(client, options)
            self._list(client, options)

    # -- listing ------------------------------------------------------------

    def _list(self, client, options):
        summary = review_summary(client)
        self.stdout.write(
            f"queue: {summary.high} high confidence (bulk approvable), "
            f"{summary.advised} review advised, {summary.judgement} need judgement "
            f"-- {summary.total} in all"
        )
        self.stdout.write(
            f"  of those, {unresolved_for(client).count()} have no ledger yet and "
            f"{pending_approval(client).count()} are waiting to be approved"
        )

        rows = list(review_queue(client, options["band"])[: options["limit"]])
        if not rows:
            self.stdout.write(self.style.SUCCESS("nothing waiting"))
            return

        self.stdout.write("")
        for number, row in enumerate(rows, start=1):
            txn = row.transaction
            amount = format_inr(txn.amount_paise)
            side = "out" if txn.is_debit else "in "
            placed = row.ledger.name if row.ledger_id else "-- no ledger --"
            self.stdout.write(
                f"{number:>3}  {txn.value_date:%d-%m-%Y}  {side} {amount:>16}  "
                f"[{row.review_band.lower():<9}] {placed}"
            )
            self.stdout.write(f"     {txn.narration[:100]}")
            if row.counterparty:
                self.stdout.write(
                    self.style.HTTP_INFO(f"     party: {row.counterparty}  channel: {row.channel}")
                )

        if review_queue(client, options["band"]).count() > len(rows):
            self.stdout.write("\n... and more; raise --limit to see them")

    # -- placing ------------------------------------------------------------

    def _place(self, client, options):
        if not options["ledger"]:
            raise CommandError("--place needs --ledger to say where the row goes.")

        rows = list(review_queue(client, options["band"])[: options["limit"]])
        index = options["place"] - 1
        if not 0 <= index < len(rows):
            raise CommandError(
                f"--place {options['place']} is outside the {len(rows)} row(s) listed."
            )

        target, _ = LedgerAccount.objects.get_or_create(
            firm_id=client.firm_id,
            client=client,
            name=options["ledger"],
            defaults={"group": options["group"]},
        )
        treatment = Treatment(
            ledger=target,
            vendor=vendor_for(client, options["vendor"]) if options["vendor"] else None,
            rcm=options["rcm"],
            tds_section=options["tds"],
        )

        before = unresolved_for(client).count()
        _, rule = review(rows[index], treatment, learn=not options["only_this_row"])
        after = unresolved_for(client).count()

        self.stdout.write(
            self.style.SUCCESS(f"placed in {target.name}")
            + (
                f" -- and {before - after - 1} other row(s) matched the rule learned from it"
                if rule is not None and before - after > 1
                else ""
            )
        )
        self.stdout.write("")
