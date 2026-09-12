"""Post reviewed rows to the ledger, as a named person.

The permission check is real and is the point of the ``--as`` argument: only a
senior CA or firm admin may approve, and this command has no way around that
because it goes through the same ``ledger.approval.approve`` every other caller
does.

    python manage.py approve --firm <uuid> --client "Acme" --as ca@firm.test --band HIGH
    python manage.py approve --firm <uuid> --client "Acme" --as ca@firm.test --all

``--band HIGH`` is the one-click bulk approval the review screen will offer:
everything the system is confident about, posted together. ``--all`` posts every
row that has a ledger, which is what you want when checking the pipeline end to
end and rarely what you want on a client's real books.
"""

from __future__ import annotations

from django.core.exceptions import PermissionDenied
from django.core.management.base import BaseCommand, CommandError

from classify.engine import pending_approval
from classify.treatment import ReviewBand
from core.db.session import firm_context
from core.models import Client, FirmMembership, User
from core.money import format_inr
from ledger.approval import NotApprovableError, approve_many


class Command(BaseCommand):
    help = "Approve classified transactions into the immutable journal."

    def add_arguments(self, parser):
        parser.add_argument("--firm", required=True, help="Firm id (UUID).")
        parser.add_argument("--client", required=True, help="Client name.")
        parser.add_argument(
            "--as", dest="approver", required=True, help="Email of the approving user."
        )
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument("--band", choices=[ReviewBand.HIGH, ReviewBand.ADVISED])
        group.add_argument("--all", action="store_true", dest="everything")
        parser.add_argument("--dry-run", action="store_true")

    def handle(self, *args, **options):
        user = User.objects.filter(email__iexact=options["approver"]).first()
        if user is None:
            raise CommandError(f"No user with the email {options['approver']!r}.")

        with firm_context(options["firm"]) as firm_id:
            client = Client.objects.filter(name=options["client"]).first()
            if client is None:
                raise CommandError(f"Firm {firm_id} has no client named {options['client']!r}.")

            membership = FirmMembership.objects.filter(user=user, is_active=True).first()
            if membership is None:
                raise CommandError(f"{user.email} is not an active member of this firm.")

            rows = list(pending_approval(client))
            if options["band"]:
                rows = [row for row in rows if row.review_band == options["band"]]

            if not rows:
                self.stdout.write("nothing is waiting to be approved")
                return

            total = sum(row.transaction.amount_paise for row in rows)
            self.stdout.write(
                f"{len(rows)} row(s) totalling {format_inr(total)}, "
                f"approving as {user.email} ({membership.role})"
            )
            if options["dry_run"]:
                for row in rows[:20]:
                    self.stdout.write(
                        f"  {row.transaction.value_date:%d-%m-%Y} "
                        f"{format_inr(row.transaction.amount_paise):>16}  {row.ledger.name}"
                    )
                self.stdout.write(self.style.WARNING("dry run -- nothing posted"))
                return

            try:
                results = approve_many(rows, membership=membership)
            except PermissionDenied as exc:
                raise CommandError(
                    f"{user.email} is a {membership.role} and may not approve entries. "
                    f"Only a senior CA or firm admin can. ({exc})"
                ) from exc
            except NotApprovableError as exc:
                raise CommandError(f"Nothing was posted: {exc}") from exc

            self.stdout.write(
                self.style.SUCCESS(f"posted {len(results)} entries to the journal")
            )
            self.stdout.write(
                "these are permanent -- a mistake is corrected with a new entry, "
                "not an edit"
            )
