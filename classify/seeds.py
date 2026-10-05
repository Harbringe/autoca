"""The rules that are true for every client, and the ledgers they need.

Deliberately short. It is tempting to seed a large opinionated chart of accounts
and a hundred merchant mappings, and it is the wrong instinct: a payee's meaning
is a fact about a particular client's business, not about the payee. The same
UPI credit from Zerodha is brokerage income to one client and a redemption of
the proprietor's own investment to the next, and the sample statement this was
built against maps two Zerodha payments to two different ledgers on exactly that
basis.

So only two kinds of rule are seeded:

* what the *bank itself* did -- interest it paid, charges it levied. Those mean
  the same thing in every set of books.
* what the client did with their own money -- a transfer between two accounts
  they own, or between the bank and the cash box (an ATM withdrawal, a counter
  deposit), is a contra entry rather than income or expenditure, in every set
  of books. Cash-in-Hand is therefore seeded: it is not a judgement about the
  trade, every business has one, and without it the most mechanical rows on a
  statement have nowhere legal to go.

Everything else is left to the review queue on the first statement and to
learned rules thereafter. A firm reaches near-full automation within two or
three months that way, and never has to hunt for a wrong seeded assumption.
"""

from __future__ import annotations

from django.db import transaction

from classify.engine import default_confidence
from classify.models import (
    ClassificationRule,
    Direction,
    LedgerAccount,
    LedgerGroup,
    MatchType,
    RuleSource,
)
from classify.narration import Channel

#: Seeds sit below learned and hand-written rules, so anything a firm decides
#: for itself wins. See ``classify.engine.LEARNED_PRIORITY``.
SEED_PRIORITY = 100

#: (ledger name, Tally group)
SEED_LEDGERS = [
    ("Bank Interest Received", LedgerGroup.INDIRECT_INCOME),
    ("Bank Charges", LedgerGroup.INDIRECT_EXPENSE),
    ("Cash-in-Hand", LedgerGroup.CASH),
    ("Suspense A/c", LedgerGroup.SUSPENSE),
]

#: (ledger name, match type, pattern, direction)
SEED_RULES = [
    # The bank crediting the account's own interest. Income, always.
    ("Bank Interest Received", MatchType.CHANNEL_IS, Channel.INTEREST, Direction.CREDIT),
    # Interest the bank collected, and anything it called a charge or a fee.
    ("Bank Charges", MatchType.CHANNEL_IS, Channel.INTEREST, Direction.DEBIT),
    ("Bank Charges", MatchType.CHANNEL_IS, Channel.FEE, Direction.ANY),
    # Cash out of the bank is cash into the box, and the reverse. A contra.
    ("Cash-in-Hand", MatchType.CHANNEL_IS, Channel.CASH, Direction.ANY),
]


def seed_client(client, *, created_by=None) -> dict[str, int]:
    """Give ``client`` the ledgers and rules that are true regardless of trade.

    Idempotent, so it is safe to call on every statement upload rather than
    only at client creation -- which matters, because a client created before
    this module existed would otherwise never get them.
    """
    ledgers = {}
    ledgers_created = 0
    for name, group in SEED_LEDGERS:
        ledger, created = LedgerAccount.objects.get_or_create(
            firm_id=client.firm_id, client=client, name=name, defaults={"group": group}
        )
        ledgers[name] = ledger
        ledgers_created += created

    rules_created = 0
    for ledger_name, match_type, pattern, direction in SEED_RULES:
        _, created = ClassificationRule.objects.get_or_create(
            firm_id=client.firm_id,
            client=client,
            match_type=match_type,
            pattern=pattern,
            direction=direction,
            defaults={
                "ledger": ledgers[ledger_name],
                "source": RuleSource.SEED,
                "priority": SEED_PRIORITY,
                "confidence": default_confidence(match_type, RuleSource.SEED),
                "created_by": created_by,
            },
        )
        rules_created += created

    return {"ledgers": ledgers_created, "rules": rules_created}


class LedgerRenameError(ValueError):
    """The new name belongs to a different ledger of this client."""


@transaction.atomic
def rename_account_ledger(account, name: str) -> int:
    """Rename a bank account's ledger, carrying its entries with it.

    Changing only ``account.ledger_name`` would make :func:`contra_ledger_for`
    open a second, empty ledger under the new name: every approved entry would
    stay on the old one and month-end reconciliation would stop matching.
    Returns how many journal lines already name the ledger, so a caller can say
    how many entries moved with it.
    """
    from ledger.models import JournalLine

    name = " ".join(name.split())
    if not name:
        raise LedgerRenameError("A ledger name is required.")
    if name == account.ledger_name:
        return 0

    current = LedgerAccount.objects.filter(
        firm_id=account.firm_id, client_id=account.client_id, name=account.ledger_name
    ).first()
    clash = LedgerAccount.objects.filter(
        firm_id=account.firm_id, client_id=account.client_id, name=name
    ).exclude(pk=current.pk if current else None)
    if clash.exists():
        raise LedgerRenameError(f"This client already has a ledger named {name!r}.")

    posted = 0
    if current is not None:
        posted = JournalLine.objects.filter(firm_id=account.firm_id, ledger_account=current).count()
        current.name = name
        current.save(update_fields=["name"])
    account.ledger_name = name
    account.save(update_fields=["ledger_name"])
    return posted


def contra_ledger_for(account) -> LedgerAccount:
    """The ledger representing one of the client's own bank accounts.

    A transfer between two accounts the client owns posts against the *other*
    account's ledger, which makes the voucher a Contra. Creating it on demand
    means the second account does not have to have been uploaded first.

    A loan account's ledger is a liability (Loans), not a bank account: it is what the client owes, and it must
    not be counted among the client's bank balances.
    """
    group = LedgerGroup.LOAN if account.kind == "LOAN" else LedgerGroup.BANK
    ledger, _ = LedgerAccount.objects.get_or_create(
        firm_id=account.firm_id,
        client=account.client,
        name=account.ledger_name,
        defaults={"group": group},
    )
    return ledger
