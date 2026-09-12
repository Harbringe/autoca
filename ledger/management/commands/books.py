"""The reports, in the terminal.

    python manage.py books --firm <uuid> --client "Acme" --fy 2025
    python manage.py books --firm <uuid> --client "Acme" --fy 2025 --reconcile 31-03-2026

Everything here is read-only. The trial balance is printed first because if it
does not agree, nothing below it is worth reading.
"""

from __future__ import annotations

import datetime

from django.core.management.base import BaseCommand, CommandError

from core.db.session import firm_context
from core.fy import fy_label
from core.models import Client
from core.money import format_inr
from ledger.reconciliation import NoStatementError, check_balance
from ledger.reports import balance_sheet, profit_and_loss, render_trial_balance, trial_balance


class Command(BaseCommand):
    help = "Print the trial balance, P&L, balance sheet and month-end check."

    def add_arguments(self, parser):
        parser.add_argument("--firm", required=True, help="Firm id (UUID).")
        parser.add_argument("--client", required=True, help="Client name.")
        parser.add_argument(
            "--fy",
            type=int,
            required=True,
            help='Financial year by its starting year: 2025 means FY 2025-26.',
        )
        parser.add_argument(
            "--reconcile",
            help="Also check the bank ledger against the statement on this date (dd-mm-yyyy).",
        )

    def handle(self, *args, **options):
        with firm_context(options["firm"]) as firm_id:
            client = Client.objects.filter(name=options["client"]).first()
            if client is None:
                raise CommandError(f"Firm {firm_id} has no client named {options['client']!r}.")

            year = options["fy"]
            self.stdout.write(f"\n{client.name} -- FY {fy_label(datetime.date(year, 4, 1))}\n")

            report = trial_balance(client, year)
            if not report.rows:
                self.stdout.write("nothing posted for this year yet")
                return

            self.stdout.write(render_trial_balance(report))
            self.stdout.write(
                self.style.SUCCESS("\ntrial balance agrees")
                if report.balances
                else self.style.ERROR(
                    "\nTRIAL BALANCE DOES NOT AGREE -- something reached the books "
                    "without going through a voucher"
                )
            )

            self._profit_and_loss(client, year)
            self._balance_sheet(client, year)
            if options["reconcile"]:
                self._reconcile(client, options["reconcile"])

    def _profit_and_loss(self, client, year):
        report = profit_and_loss(client, year)
        self.stdout.write("\n--- Profit & Loss ---")
        for row in report.income:
            self.stdout.write(f"  income   {row.name:<34} {format_inr(-row.net_paise):>16}")
        for row in report.expenses:
            self.stdout.write(f"  expense  {row.name:<34} {format_inr(row.net_paise):>16}")
        verdict = "profit" if report.net_profit_paise >= 0 else "loss"
        self.stdout.write(
            f"  {verdict:<43} {format_inr(abs(report.net_profit_paise)):>16}"
        )

    def _balance_sheet(self, client, year):
        report = balance_sheet(client, year)
        self.stdout.write("\n--- Balance Sheet ---")
        for row in report.assets:
            self.stdout.write(f"  asset     {row.name:<33} {format_inr(row.net_paise):>16}")
        for row in report.liabilities:
            self.stdout.write(f"  liability {row.name:<33} {format_inr(-row.net_paise):>16}")
        self.stdout.write(f"  {'net profit':<43} {format_inr(report.net_profit_paise):>16}")
        if report.suspense_paise:
            self.stdout.write(
                self.style.WARNING(
                    f"  {'in suspense -- unanswered questions':<43} "
                    f"{format_inr(report.suspense_paise):>16}"
                )
            )
        if not report.balances:
            self.stdout.write(self.style.ERROR("  balance sheet does not balance"))

    def _reconcile(self, client, raw_date):
        try:
            as_of = datetime.datetime.strptime(raw_date, "%d-%m-%Y").date()
        except ValueError as exc:
            raise CommandError(f"--reconcile wants a date as dd-mm-yyyy, got {raw_date!r}") from exc

        self.stdout.write("\n--- Month end ---")
        for account in client.bank_accounts.all():
            try:
                check = check_balance(account, as_of)
            except NoStatementError as exc:
                self.stdout.write(f"  {exc}")
                continue
            style = self.style.SUCCESS if check.can_close else self.style.WARNING
            self.stdout.write("  " + style(check.explain()))
