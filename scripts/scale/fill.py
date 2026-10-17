"""Fill the scratch database with fake firms, clients, bank accounts, statement rows, classifications, entries and parties.

Runs inside the app image against the autoca_scale_test database only, through the same models and the same row-level security as
the app (the web login, one firm at a time), so what is built is what the app would have built, only faster.

    python /scale/fill.py --txns 3000000 --firms 2 --clients 3

--txns is the total number of bank rows. Every row gets a classification; about 70% are decided and get an entry with two lines.
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import os
import random
import sys
import time
import uuid

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings.prod")
django.setup()

from django.conf import settings  # noqa: E402
from django.utils import timezone  # noqa: E402

from banking.models import AccountKind, BankAccount, Statement, StatementTransaction  # noqa: E402
from classify.models import (  # noqa: E402
    ClassificationMethod,
    LedgerAccount,
    LedgerGroup,
    Party,
    TransactionClassification,
)
from core.db.session import firm_context  # noqa: E402
from core.fy import financial_year  # noqa: E402
from core.provisioning import create_client, create_firm  # noqa: E402
from documents.models import Document, DocumentKind  # noqa: E402
from ledger.models import Direction, JournalEntry, JournalLine, VoucherType  # noqa: E402

NAMESPACE = uuid.UUID("5ca1e000-0000-4000-8000-000000000001")
BATCH = 4000
MONTHS = 36
START = datetime.date(2023, 4, 1)
EXPENSE_GROUPS = [
    LedgerGroup.INDIRECT_EXPENSE,
    LedgerGroup.DIRECT_EXPENSE,
    LedgerGroup.INDIRECT_INCOME,
    LedgerGroup.DIRECT_INCOME,
]


def guard() -> None:
    db = settings.DATABASES["default"]
    if db["NAME"] != "autoca_scale_test" or db["HOST"] != "db":
        sys.exit(
            f"Refusing: this fills only the scratch database autoca_scale_test on host 'db', not {db['NAME']} on {db['HOST']}."
        )


def month_start(n: int) -> datetime.date:
    year, month = divmod(START.month - 1 + n, 12)
    return datetime.date(START.year + year, month + 1, 1)


def build_client(
    firm, name: str, accounts: int, txns: int, ledgers: int, parties: int, rng: random.Random
) -> int:
    client = create_client(firm, name, START)
    with firm_context(firm.pk):
        expense = [
            LedgerAccount(
                firm_id=firm.pk,
                client=client,
                name=f"Ledger {i:04d}",
                group=EXPENSE_GROUPS[i % 4].value,
            )
            for i in range(ledgers)
        ]
        LedgerAccount.objects.bulk_create(expense, batch_size=2000)
        bank_ledgers = []
        bank_accounts = []
        for a in range(accounts):
            ledger = LedgerAccount(
                firm_id=firm.pk, client=client, name=f"Bank {a + 1}", group=LedgerGroup.BANK.value
            )
            bank_ledgers.append(ledger)
            account = BankAccount(
                firm_id=firm.pk,
                client=client,
                kind=AccountKind.BANK,
                bank_code="SCALE",
                ledger_name=ledger.name,
                account_last4=f"{a:04d}",
                opening_balance_paise=0,
                opening_as_of=START,
            )
            account.set_account_number(f"{uuid.uuid4().int % 10**12:012d}")
            bank_accounts.append(account)
        LedgerAccount.objects.bulk_create(bank_ledgers)
        BankAccount.objects.bulk_create(bank_accounts)
        parties_made = [
            Party(
                firm_id=firm.pk,
                client=client,
                canonical_name=f"Party {i:05d} Traders",
                alias_token=f"V{i:06x}",
            )
            for i in range(parties)
        ]
        Party.objects.bulk_create(parties_made, batch_size=2000)
    party_ids = [p.pk for p in parties_made]
    expense_rows = expense
    ledger_by_account = {
        a.pk: ledger for ledger, a in zip(bank_ledgers, bank_accounts, strict=True)
    }

    entry_no: dict[tuple[int, str], int] = {}
    made = 0
    per_account = txns // accounts
    per_statement = max(1, per_account // MONTHS)
    for account in bank_accounts:
        bank_ledger = ledger_by_account[account.pk]
        balance = 0
        for m in range(MONTHS):
            first = month_start(m)
            last = month_start(m + 1) - datetime.timedelta(days=1)
            with firm_context(firm.pk):
                document = Document.objects.create(
                    firm_id=firm.pk,
                    client=client,
                    kind=DocumentKind.BANK_STATEMENT,
                    original_filename=f"scale-{account.account_last4}-{m}.pdf",
                    sha256=hashlib.sha256(f"{account.pk}-{m}".encode()).hexdigest(),
                )
                statement = Statement.objects.create(
                    firm_id=firm.pk,
                    document=document,
                    bank_account=account,
                    period_start=first,
                    period_end=last,
                    opening_balance_paise=balance,
                    closing_balance_paise=balance,
                    total_debit_paise=0,
                    total_credit_paise=0,
                    transaction_count=per_statement,
                )
                done = 0
                while done < per_statement:
                    n = min(BATCH, per_statement - done)
                    rows, classes, entries, lines = [], [], [], []
                    for k in range(done, done + n):
                        amount = rng.randint(100, 5_000_000)
                        debit = rng.random() < 0.6
                        balance += -amount if debit else amount
                        day = first + datetime.timedelta(days=rng.randint(0, (last - first).days))
                        txn = StatementTransaction(
                            firm_id=firm.pk,
                            statement=statement,
                            bank_account=account,
                            row_number=k + 1,
                            value_date=day,
                            narration=f"UPI/{rng.randint(10**11, 10**12)}/Party {rng.randint(0, parties - 1):05d}/payment",
                            debit_paise=amount if debit else 0,
                            credit_paise=0 if debit else amount,
                            balance_paise=balance,
                            dedupe_hash=hashlib.sha256(
                                f"{account.pk}-{m}-{k}".encode()
                            ).hexdigest(),
                        )
                        rows.append(txn)
                        decided = rng.random() < 0.7
                        other = rng.choice(expense_rows)
                        party = rng.choice(party_ids) if rng.random() < 0.5 else None
                        classes.append(
                            TransactionClassification(
                                firm_id=firm.pk,
                                transaction=txn,
                                ledger_id=other.pk if decided else None,
                                party_id=party if decided else None,
                                method=ClassificationMethod.RULE
                                if decided
                                else ClassificationMethod.UNRESOLVED,
                                confidence=0.9 if decided else 0.0,
                                review_band="HIGH" if decided else "JUDGEMENT",
                                needs_review=not decided,
                            )
                        )
                        if decided:
                            vtype = VoucherType.PAYMENT if debit else VoucherType.RECEIPT
                            year = financial_year(day)
                            entry_no[(year, vtype)] = entry_no.get((year, vtype), 0) + 1
                            entry = JournalEntry(
                                firm_id=firm.pk,
                                client=client,
                                entry_no=entry_no[(year, vtype)],
                                financial_year=year,
                                entry_date=day,
                                voucher_type=vtype,
                                narration=txn.narration,
                                source_transaction=txn,
                                approved_at=timezone.now(),
                            )
                            entries.append(entry)
                            dr, cr = (other, bank_ledger) if debit else (bank_ledger, other)
                            lines.append(
                                JournalLine.build(
                                    entry=entry,
                                    ledger_account=dr,
                                    direction=Direction.DEBIT,
                                    amount_paise=amount,
                                    party_id=party if debit else None,
                                )
                            )
                            lines.append(
                                JournalLine.build(
                                    entry=entry,
                                    ledger_account=cr,
                                    direction=Direction.CREDIT,
                                    amount_paise=amount,
                                    party_id=None if debit else party,
                                )
                            )
                    StatementTransaction.objects.bulk_create(rows, batch_size=BATCH)
                    TransactionClassification.objects.bulk_create(classes, batch_size=BATCH)
                    JournalEntry.objects.bulk_create(entries, batch_size=BATCH)
                    JournalLine.objects.bulk_create(lines, batch_size=BATCH)
                    done += n
                    made += n
    return made


def main() -> None:
    guard()
    ap = argparse.ArgumentParser()
    ap.add_argument("--txns", type=int, default=300_000, help="total bank rows across everything")
    ap.add_argument("--firms", type=int, default=2)
    ap.add_argument("--clients", type=int, default=3, help="clients per firm")
    ap.add_argument("--accounts", type=int, default=2, help="bank accounts per client")
    ap.add_argument("--ledgers", type=int, default=150, help="ledgers per client")
    ap.add_argument("--parties", type=int, default=1500, help="parties per client")
    ap.add_argument("--seed", type=int, default=1)
    args = ap.parse_args()

    clients = args.firms * args.clients
    per_client = args.txns // clients
    rng = random.Random(args.seed)  # noqa: S311 -- fake data, not secrets
    started = time.monotonic()
    total = 0
    for f in range(args.firms):
        firm = create_firm(f"Scale Firm {f + 1}", firm_id=uuid.uuid5(NAMESPACE, f"firm-{f}"))
        for c in range(args.clients):
            t0 = time.monotonic()
            n = build_client(
                firm,
                f"Scale Client {c + 1}",
                args.accounts,
                per_client,
                args.ledgers,
                args.parties,
                rng,
            )
            total += n
            print(
                f"firm {f + 1} client {c + 1}: {n:,} bank rows in {time.monotonic() - t0:,.0f}s",
                flush=True,
            )
    secs = time.monotonic() - started
    print(
        f"done: {total:,} bank rows (plus their classifications, entries and lines) in {secs:,.0f}s"
    )


if __name__ == "__main__":
    main()
