"""Render everything the system did with a statement, as one HTML page.

Built for the case where there is no Tally to import into and no review screen
yet: the only way to check the work is to read it, and reading it in a terminal
means losing the alignment that makes a statement checkable at all.

The page puts the chain side by side -- the row as the bank printed it, what
was read out of it, how it was classified and on what evidence, and the journal
entry it became -- so a person can run an eye down it against the original PDF.
That comparison is the real acceptance test for a new bank's format, and it
needs no software at either end beyond a browser.

    python manage.py verify_statement --firm <uuid> --client "Acme" --out report.html

Nothing is written to the database. This is a read-only view.
"""

from __future__ import annotations

import datetime
import html
import pathlib

from django.core.management.base import BaseCommand, CommandError

from banking.models import Statement
from classify.treatment import ReviewBand
from core.db.session import firm_context
from core.fy import financial_year
from core.models import Client
from core.money import format_inr
from ledger.models import JournalEntry
from ledger.reconciliation import NoStatementError, check_balance
from ledger.reports import trial_balance


class Command(BaseCommand):
    help = "Write an HTML page showing everything known about a statement."

    def add_arguments(self, parser):
        parser.add_argument("--firm", required=True, help="Firm id (UUID).")
        parser.add_argument("--client", required=True, help="Client name.")
        parser.add_argument("--out", default="statement-verification.html")
        parser.add_argument(
            "--statement",
            help="Statement id. Defaults to the most recently uploaded one.",
        )

    def handle(self, *args, **options):
        with firm_context(options["firm"]) as firm_id:
            client = Client.objects.filter(name=options["client"]).first()
            if client is None:
                raise CommandError(f"Firm {firm_id} has no client named {options['client']!r}.")

            statement = self._statement_for(client, options.get("statement"))
            page = self._render(client, statement)

        destination = pathlib.Path(options["out"])
        destination.write_text(page, encoding="utf-8")
        self.stdout.write(
            self.style.SUCCESS(f"wrote {destination.resolve()} -- open it in a browser")
        )

    def _statement_for(self, client, statement_id):
        statements = Statement.objects.filter(
            firm_id=client.firm_id, bank_account__client=client
        ).select_related("bank_account", "document")
        statement = (
            statements.filter(pk=statement_id).first()
            if statement_id
            else statements.order_by("-created_at").first()
        )
        if statement is None:
            raise CommandError(f"{client.name} has no statements. Ingest one first.")
        return statement

    # -- rendering ----------------------------------------------------------

    def _render(self, client, statement) -> str:
        rows = list(
            statement.transactions.select_related(
                "classification__ledger", "classification__party"
            ).order_by("row_number")
        )
        entries = {
            entry.source_transaction_id: entry
            for entry in JournalEntry.objects.filter(
                firm_id=statement.firm_id, source_transaction__statement=statement
            ).prefetch_related("lines__ledger_account")
        }

        return PAGE.format(
            client=esc(client.name),
            account=esc(str(statement.bank_account)),
            period=f"{statement.period_start:%d-%m-%Y} to {statement.period_end:%d-%m-%Y}",
            parser=esc(f"{statement.parser} v{statement.parser_version}"),
            source=esc(statement.document.original_filename or statement.document.sha256[:16]),
            generated=datetime.datetime.now().strftime("%d-%m-%Y %H:%M"),
            summary=self._summary(statement, rows, entries),
            chain=self._chain(statement, rows, entries),
            books=self._books(client, statement),
        )

    def _summary(self, statement, rows, entries) -> str:
        posted = len(entries)
        classified = sum(1 for r in rows if getattr(r, "classification", None) and r.classification.ledger_id)
        return "".join(
            tile(label, value, tone)
            for label, value, tone in (
                ("Rows read", str(len(rows)), ""),
                ("Opening", format_inr(statement.opening_balance_paise), ""),
                ("Closing", format_inr(statement.closing_balance_paise), ""),
                ("Classified", f"{classified} / {len(rows)}", "" if classified == len(rows) else "warn"),
                ("Posted", f"{posted} / {len(rows)}", "ok" if posted == len(rows) else "warn"),
            )
        )

    def _chain(self, statement, rows, entries) -> str:
        running = statement.opening_balance_paise
        out = []
        liability = statement.bank_account.kind == "LOAN"  # a loan's balance rises with a debit
        for row in rows:
            running += -row.signed_paise if liability else row.signed_paise
            drift = running - row.balance_paise
            classification = getattr(row, "classification", None)
            entry = entries.get(row.pk)

            out.append(
                ROW.format(
                    n=row.row_number,
                    date=f"{row.value_date:%d-%m-%Y}",
                    narration=esc(row.narration),
                    debit=format_inr(row.debit_paise) if row.debit_paise else "",
                    credit=format_inr(row.credit_paise) if row.credit_paise else "",
                    balance=format_inr(row.balance_paise),
                    chain_class="ok" if drift == 0 else "bad",
                    chain=("&#10003;" if drift == 0 else f"off by {format_inr(drift)}"),
                    ledger=self._ledger_cell(classification),
                    evidence=self._evidence_cell(classification),
                    entry=self._entry_cell(entry),
                )
            )
        return "".join(out)

    @staticmethod
    def _ledger_cell(classification) -> str:
        if classification is None:
            return '<span class="muted">not classified</span>'
        if classification.ledger is None:
            return '<span class="warn-text">awaiting a ledger</span>'
        bits = [esc(classification.ledger.name)]
        if classification.party_id:
            bits.append(f'<span class="muted">{esc(classification.party.canonical_name)}</span>')
        if classification.rcm:
            bits.append('<span class="flag">RCM</span>')
        if classification.tds_section:
            bits.append(f'<span class="flag">TDS {esc(classification.tds_section)}</span>')
        return "<br>".join(bits)

    @staticmethod
    def _evidence_cell(classification) -> str:
        """Why the system placed it where it did. The part worth checking."""
        if classification is None:
            return ""
        band = {
            ReviewBand.HIGH: "ok",
            ReviewBand.ADVISED: "warn",
            ReviewBand.JUDGEMENT: "bad",
        }.get(classification.review_band, "")
        return (
            f'<span class="pill {band}">{esc(classification.review_band.lower())}</span> '
            f'<span class="muted">{classification.confidence:.2f}</span><br>'
            f'<span class="mono">{esc(classification.channel)}</span> '
            f'{esc(classification.counterparty[:40])}'
            + (' <span class="flag">self</span>' if classification.is_self_transfer else "")
        )

    @staticmethod
    def _entry_cell(entry) -> str:
        if entry is None:
            return '<span class="muted">not posted</span>'
        lines = "".join(
            f'<div><span class="mono">{line.direction}</span> {esc(line.ledger_account.name)} '
            f"{format_inr(line.amount_paise)}</div>"
            for line in entry.lines.all()
        )
        return f'<div class="vno">{esc(entry.voucher_type)} #{entry.entry_no}</div>{lines}'

    def _books(self, client, statement) -> str:
        """The month-end check and the trial balance, which is where errors surface."""
        blocks = []
        try:
            check = check_balance(statement.bank_account, statement.period_end)
            blocks.append(
                f'<p class="{"ok-text" if check.matches else "bad-text"}">{esc(check.explain())}</p>'
            )
        except NoStatementError as exc:
            blocks.append(f'<p class="muted">{esc(str(exc))}</p>')

        report = trial_balance(client, financial_year(statement.period_start))
        if report.rows:
            body = "".join(
                f"<tr><td>{esc(r.name)}</td>"
                f'<td class="num">{format_inr(r.closing_debit_paise) if r.closing_debit_paise else ""}</td>'
                f'<td class="num">{format_inr(r.closing_credit_paise) if r.closing_credit_paise else ""}</td></tr>'
                for r in report.rows
            )
            blocks.append(
                f'<table class="tb"><thead><tr><th>Particulars</th><th class="num">Debit</th>'
                f'<th class="num">Credit</th></tr></thead><tbody>{body}</tbody>'
                f'<tfoot><tr><td>Total</td><td class="num">{format_inr(report.total_debit_paise)}</td>'
                f'<td class="num">{format_inr(report.total_credit_paise)}</td></tr></tfoot></table>'
                f'<p class="{"ok-text" if report.balances else "bad-text"}">'
                f'{"Trial balance agrees." if report.balances else "TRIAL BALANCE DOES NOT AGREE."}</p>'
                f'<p class="muted">{esc(report.footer.caption())}</p>'
            )
        else:
            blocks.append('<p class="muted">Nothing posted yet, so there is no trial balance.</p>')
        return "".join(blocks)


def esc(value) -> str:
    return html.escape(str(value or ""))


def tile(label, value, tone) -> str:
    return f'<div class="tile {tone}"><span>{esc(label)}</span><strong>{esc(value)}</strong></div>'


ROW = """<tr>
  <td class="num muted">{n}</td>
  <td class="nowrap">{date}</td>
  <td class="narration">{narration}</td>
  <td class="num dr">{debit}</td>
  <td class="num cr">{credit}</td>
  <td class="num">{balance}</td>
  <td class="chk {chain_class}">{chain}</td>
  <td>{ledger}</td>
  <td class="evidence">{evidence}</td>
  <td class="entry">{entry}</td>
</tr>"""


PAGE = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Statement verification &mdash; {client}</title>
<style>
  :root {{
    --ink:#16191c; --soft:#5a6169; --faint:#8a9198; --rule:#e2e6e6;
    --ground:#fbfbfa; --surface:#fff; --ok:#17624a; --warn:#8a5008; --bad:#9a2f2f;
    --ok-bg:#e6f2ec; --warn-bg:#f9efdd; --bad-bg:#f9e7e5;
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{
      --ink:#e7eaea; --soft:#aeb5ba; --faint:#7e858b; --rule:#2b3137;
      --ground:#121517; --surface:#191c1f; --ok:#6fc7a3; --warn:#dfac5c; --bad:#e4918a;
      --ok-bg:#16302a; --warn-bg:#332810; --bad-bg:#331f1e;
    }}
  }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--ground); color:var(--ink);
    font:14px/1.5 ui-sans-serif,system-ui,-apple-system,"Segoe UI",sans-serif; }}
  .wrap {{ max-width:1500px; margin:0 auto; padding:24px 20px 64px; }}
  h1 {{ font-size:1.5rem; margin:0 0 .25rem; }}
  h2 {{ font-size:1.1rem; margin:2.5rem 0 .75rem; }}
  .meta {{ color:var(--faint); font-size:.82rem; display:flex; flex-wrap:wrap; gap:.3rem 1.4rem; }}
  .tiles {{ display:flex; flex-wrap:wrap; gap:0; border:1px solid var(--rule);
    background:var(--surface); margin:1.25rem 0 0; }}
  .tile {{ padding:.7rem 1.1rem; display:flex; flex-direction:column; gap:.1rem; flex:1 1 8rem; }}
  .tile + .tile {{ border-left:1px solid var(--rule); }}
  .tile span {{ font-size:.72rem; color:var(--faint); text-transform:uppercase; letter-spacing:.08em; }}
  .tile strong {{ font-size:1.15rem; font-variant-numeric:tabular-nums; }}
  .tile.ok strong {{ color:var(--ok); }} .tile.warn strong {{ color:var(--warn); }}
  .scroll {{ overflow-x:auto; border:1px solid var(--rule); background:var(--surface); }}
  table {{ border-collapse:collapse; width:100%; font-size:.82rem; }}
  th {{ text-align:left; font-size:.7rem; text-transform:uppercase; letter-spacing:.07em;
    color:var(--faint); padding:.55rem .6rem; border-bottom:1px solid var(--rule); white-space:nowrap; }}
  td {{ padding:.5rem .6rem; border-bottom:1px solid var(--rule); vertical-align:top; }}
  tbody tr:last-child td {{ border-bottom:0; }}
  .num {{ text-align:right; font-variant-numeric:tabular-nums; white-space:nowrap; }}
  .nowrap {{ white-space:nowrap; }}
  .narration {{ min-width:20rem; max-width:26rem; word-break:break-word; }}
  .evidence {{ min-width:13rem; font-size:.76rem; }}
  .entry {{ min-width:14rem; font-size:.76rem; }}
  .vno {{ font-weight:600; margin-bottom:.15rem; }}
  .dr {{ color:var(--bad); }} .cr {{ color:var(--ok); }}
  .chk {{ text-align:center; font-weight:700; }}
  .chk.ok {{ color:var(--ok); }} .chk.bad {{ color:var(--bad); background:var(--bad-bg); }}
  .muted {{ color:var(--faint); }}
  .mono {{ font-family:ui-monospace,Menlo,Consolas,monospace; font-size:.92em; }}
  .pill {{ display:inline-block; padding:.05em .45em; border-radius:2px; font-size:.68rem;
    font-weight:700; text-transform:uppercase; letter-spacing:.05em;
    background:var(--rule); color:var(--soft); }}
  .pill.ok {{ background:var(--ok-bg); color:var(--ok); }}
  .pill.warn {{ background:var(--warn-bg); color:var(--warn); }}
  .pill.bad {{ background:var(--bad-bg); color:var(--bad); }}
  .flag {{ display:inline-block; padding:.05em .4em; border:1px solid var(--rule);
    border-radius:2px; font-size:.68rem; color:var(--soft); }}
  .warn-text {{ color:var(--warn); }} .ok-text {{ color:var(--ok); }} .bad-text {{ color:var(--bad); font-weight:600; }}
  .tb {{ max-width:46rem; border:1px solid var(--rule); background:var(--surface); }}
  .tb tfoot td {{ font-weight:700; border-top:2px solid var(--rule); }}
  p {{ max-width:70ch; }}
</style></head>
<body><div class="wrap">
  <h1>{account}</h1>
  <div class="meta">
    <span>{client}</span><span>{period}</span>
    <span>parser {parser}</span><span>source {source}</span>
    <span>generated {generated}</span>
  </div>
  <div class="tiles">{summary}</div>

  <h2>Every row, from the bank&rsquo;s print to the posted entry</h2>
  <p class="muted">Read the first six columns against the original PDF. The tick
  column re-walks the running balance independently &mdash; if any row shows a
  drift, the parse is wrong and nothing below it can be trusted.</p>
  <div class="scroll"><table>
    <thead><tr>
      <th>#</th><th>Date</th><th>Narration as printed</th>
      <th class="num">Debit</th><th class="num">Credit</th><th class="num">Balance</th>
      <th>Chain</th><th>Ledger</th><th>Why</th><th>Journal entry</th>
    </tr></thead>
    <tbody>{chain}</tbody>
  </table></div>

  <h2>The books that result</h2>
  {books}
</div></body></html>
"""
