"""Run a statement through the whole pipeline from the command line.

    python manage.py ingest_statement --firm <uuid> --client "Ramesh Deshmukh" axis.pdf
    python manage.py ingest_statement --firm <uuid> --client "..." axis.pdf --export books.xml

The firm id is required and cannot be inferred from the client name, because
finding a client without already knowing their firm would mean reading
``core_client`` with no tenant context -- which is precisely what the database
refuses to do. The command follows ``core.management.commands.bootstrap_admin``
in taking the id and opening that one context for the whole run.
"""

from __future__ import annotations

import pathlib

from django.core.management.base import BaseCommand, CommandError

from banking.ingest import ingest_statement
from banking.parsers import StatementParseError
from classify.engine import classify_statement, unresolved_for
from classify.seeds import seed_client
from core.db.session import firm_context
from core.models import Client
from ledger.tally import export_statement


class Command(BaseCommand):
    help = "Ingest a bank statement PDF, classify its rows, and optionally export Tally XML."

    def add_arguments(self, parser):
        parser.add_argument("path", help="Path to the statement PDF.")
        parser.add_argument("--firm", required=True, help="Firm id (UUID).")
        parser.add_argument("--client", required=True, help="Client name, as filed by the firm.")
        parser.add_argument("--export", help="Write Tally XML to this path.")
        parser.add_argument(
            "--no-seed",
            action="store_true",
            help="Skip the built-in interest and charges rules.",
        )

    def handle(self, *args, **options):
        path = pathlib.Path(options["path"])
        if not path.is_file():
            raise CommandError(f"No such file: {path}")

        with firm_context(options["firm"]) as firm_id:
            client = Client.objects.filter(name=options["client"]).first()
            if client is None:
                raise CommandError(
                    f"Firm {firm_id} has no client named {options['client']!r}."
                )

            try:
                result = ingest_statement(
                    client=client, data=path.read_bytes(), filename=path.name
                )
            except StatementParseError as exc:
                raise CommandError(str(exc)) from exc

            statement = result.statement
            verb = "ingested" if result.is_new else "already present"
            self.stdout.write(
                f"{verb}: {statement} -- {result.rows_created} new rows, "
                f"{result.rows_already_present} already known"
            )

            if not options["no_seed"]:
                seed_client(client)

            classified = classify_statement(statement)
            self.stdout.write(
                f"classified: {classified.placed} placed, {classified.queued} queued "
                f"for review ({classified.hit_rate:.0%} automatic)"
            )

            queued = unresolved_for(client).count()
            if queued:
                self.stdout.write(self.style.WARNING(f"{queued} rows awaiting a ledger"))

            if options["export"]:
                self._export(statement, client, pathlib.Path(options["export"]))

    def _export(self, statement, client, destination: pathlib.Path) -> None:
        result = export_statement(statement, company_name=client.name)
        destination.write_text(result.xml, encoding="utf-8")
        self.stdout.write(
            self.style.SUCCESS(
                f"wrote {result.voucher_count} vouchers and {result.ledger_count} "
                f"ledger masters to {destination}"
            )
        )
        if result.skipped:
            self.stdout.write(
                f"left out {len(result.skipped)} unclassified rows; "
                f"classify them and export again"
            )
