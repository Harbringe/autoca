"""Which ledgers and bank accounts a set of Tally files implies, and the group each most likely belongs in.

Pure: names in, proposals out. A person confirms or changes every proposal before anything is created, so a wrong guess costs a click, not
the books. Each proposal says why it was guessed, and says so plainly when the evidence was thin (``unsure``).

A ledger's group is decided from how the files use it, strongest evidence first: what its *name* says (a bank, a tax, a round-off), then
the part it plays in a voucher (the party of a sale is a debtor, the head of a purchase is a purchase account), and, from a bank report
alone, the direction of the money.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from classify.models import LedgerGroup as G
from ledger.models import VoucherType
from ledger.tally_bankreport import ParsedBankReport
from ledger.tally_parse import ParsedMasters, normal_name, resolve_group
from ledger.tally_vouchers import ParsedVoucher

_BANK_WORDS = re.compile(r"\b(bank|a/c|ac|sb|current|savings)\b")
_LOAN_WORDS = re.compile(r"\b(loan|cc|od|overdraft|cash credit|term loan)\b")
_CARD_WORDS = re.compile(r"\bcredit card\b")
_COMPANY_WORDS = re.compile(r"\b(ltd|limited|pvt|private|traders|trading|industries|agro|agency|agencies|enterprises|stores|corp|co|company|distributors|foods|oils)\b")
_TCS = re.compile(r"\btcs\b")
_ACCOUNT_NUMBER = re.compile(r"\d{6,}")


@dataclass
class Proposal:
    name: str
    group: str
    reason: str
    #: How many times the files use it.
    uses: int = 0
    #: The evidence was thin: a person should look at this one.
    unsure: bool = False


@dataclass
class AccountProposal:
    """A bank, loan or card account the files imply, to be added to the client."""

    ledger: str
    kind: str
    bank_code: str
    #: Read from the ledger's name when it carries one; blank when the person must type it.
    account_number: str


@dataclass
class Discovery:
    ledgers: list[Proposal] = field(default_factory=list)
    accounts: list[AccountProposal] = field(default_factory=list)


def name_group(name: str) -> tuple[str, str] | None:
    """The group a ledger's name alone settles, with the reason; None when the name says nothing."""
    key = normal_name(name)
    if key in ("cash", "cash-in-hand", "petty cash", "cash in hand"):
        return G.CASH, "Cash by name"
    if _CARD_WORDS.search(key):
        return G.CURRENT_LIABILITY, "A credit card by name"
    if _LOAN_WORDS.search(key) and (_ACCOUNT_NUMBER.search(key) or "loan" in key):
        return G.LOAN, "A loan or cash-credit account by name"
    if _BANK_WORDS.search(key) and _ACCOUNT_NUMBER.search(key):
        return G.BANK, "A bank account by name and number"
    if any(t in key for t in ("cgst", "sgst", "igst", "utgst", "cess")):
        return G.DUTIES_AND_TAXES, "GST by name"
    if _TCS.search(key):
        return G.CURRENT_ASSET, "Tax collected at source by name"
    if re.search(r"\btds\b", key):
        return G.DUTIES_AND_TAXES, "Tax deducted at source by name"
    if "round" in key or key in ("r/f", "r/off"):
        return G.INDIRECT_EXPENSE, "Round-off by name"
    if "suspense" in key:
        return G.SUSPENSE, "Suspense by name"
    return None


def _account_for(name: str, group: str) -> AccountProposal | None:
    if group not in (G.BANK, G.LOAN):
        return None
    number = max(_ACCOUNT_NUMBER.findall(name), key=len, default="")
    words = re.findall(r"[A-Za-z]+", name)
    code = (words[0] if words else "BANK").upper()[:16]
    return AccountProposal(ledger=name, kind="LOAN" if group == G.LOAN else "BANK", bank_code=code, account_number=number)


#: Tally's own books-wide ledgers, which a masters export lists but no client of ours needs created.
_TALLY_OWN = {"profit & loss a/c"}


def master_groups(masters: ParsedMasters) -> dict[str, tuple[str, str, str | None]]:
    """Each ledger of a masters export: normalised name -> (name as written, the group Tally puts it in, that group or None when not ours).

    The group is read from the ledger's own parent in the file, walked up to the nearest group we know, so a firm's own sub-group
    (a "Fertilizer Dealers" group under Sundry Debtors) still lands on Sundry Debtors.
    """
    out: dict[str, tuple[str, str, str | None]] = {}
    for ledger in masters.ledgers:
        key = normal_name(ledger.name)
        if key in _TALLY_OWN:
            continue
        resolved = resolve_group(ledger.parent, masters.groups)
        out[key] = (ledger.name, ledger.parent, resolved.group)
    return out


def discover(
    vouchers: list[ParsedVoucher],
    reports: list[tuple[str, ParsedBankReport]],
    existing: set[str],
    masters: dict[str, tuple[str, str, str | None]] | None = None,
) -> Discovery:
    """Propose the ledgers (and bank accounts) the files use that the client does not have yet.

    ``reports`` pairs each bank report with the name of the bank ledger it is the report of. ``existing`` is the normalised names of the
    client's ledgers, which are left alone. ``masters`` (from ``master_groups``) is what Tally itself says each ledger's group is: it
    settles the group outright, so a ledger named in it is never a guess, and a ledger only the masters list is proposed too.
    """
    masters = masters or {}
    votes: dict[str, Counter] = defaultdict(Counter)
    spelled: dict[str, str] = {}
    uses: Counter = Counter()
    unsure_only: dict[str, bool] = {}

    def vote(name: str, group: str, reason: str, *, weak: bool = False) -> None:
        key = normal_name(name)
        spelled.setdefault(key, name)
        votes[key][(group, reason)] += 1
        unsure_only[key] = unsure_only.get(key, True) and weak

    for v in vouchers:
        for line in v.lines:
            key = normal_name(line.ledger)
            spelled.setdefault(key, line.ledger)
            uses[key] += 1
            settled = name_group(line.ledger)
            if settled:
                vote(line.ledger, *settled)
            elif v.tally_type in (VoucherType.SALES, VoucherType.CREDIT_NOTE) or v.tally_type in ("Sales", "Credit Note"):
                vote(line.ledger, G.DEBTOR if line.is_party else G.SALES, "The customer on a sale" if line.is_party else "Booked as the sales head")
            elif v.tally_type in (VoucherType.PURCHASE, VoucherType.DEBIT_NOTE) or v.tally_type in ("Purchase", "Debit Note"):
                vote(line.ledger, G.CREDITOR if line.is_party else G.PURCHASE, "The supplier on a purchase" if line.is_party else "Booked as the purchase head")
            elif v.tally_type == "Receipt":
                vote(line.ledger, G.DEBTOR if line.bills else (G.INDIRECT_INCOME if line.signed_paise < 0 else G.SUSPENSE), "Received from", weak=not line.bills)
            elif v.tally_type == "Payment":
                vote(line.ledger, G.CREDITOR if line.bills else (G.INDIRECT_EXPENSE if line.signed_paise > 0 else G.SUSPENSE), "Paid to", weak=not line.bills)
            else:
                vote(line.ledger, G.SUSPENSE, "Used in a journal or contra; no clear group", weak=True)

    for subject, report in reports:
        spelled.setdefault(normal_name(subject), subject)
        settled = name_group(subject) or (G.BANK, "The bank ledger this report is for")
        vote(subject, *settled)
        for row in report.rows:
            key = normal_name(row.counter)
            spelled.setdefault(key, row.counter)
            uses[key] += 1
            settled = name_group(row.counter)
            if settled:
                vote(row.counter, *settled)
                continue
            company = bool(_COMPANY_WORDS.search(key))
            paid = row.signed_paise < 0  # money out of the bank
            if company:
                vote(row.counter, G.CREDITOR if paid else G.DEBTOR, "Looks like a business; paid to" if paid else "Looks like a business; received from", weak=True)
            else:
                vote(row.counter, G.INDIRECT_EXPENSE if paid else G.INDIRECT_INCOME, "An expense paid from the bank" if paid else "Income received in the bank", weak=True)

    for key, (written, _parent, _group) in masters.items():
        spelled.setdefault(key, written)
        votes.setdefault(key, Counter())

    out = Discovery()
    for key, counts in sorted(votes.items(), key=lambda kv: spelled[kv[0]].lower()):
        if key in existing:
            continue
        if key in masters:
            written, parent, settled_group = masters[key]
            if settled_group is not None:
                group, reason, unsure = settled_group, f"Its group in Tally: {parent or 'none given'}", False
            else:  # the file puts it under a group of the firm's own that we cannot place
                guess = counts.most_common(1)[0][0] if counts else (G.SUSPENSE, "")
                group, reason, unsure = guess[0], f"Tally puts it under {parent!r}, which is not a standard group; check it", True
            out.ledgers.append(Proposal(name=spelled[key], group=group, reason=reason, uses=uses.get(key, 0), unsure=unsure))
            account = _account_for(spelled[key], group)
            if account is not None:
                out.accounts.append(account)
            continue
        (group, reason), top = counts.most_common(1)[0]
        split = len({g for g, _r in counts}) > 1
        out.ledgers.append(
            Proposal(name=spelled[key], group=group, reason=reason, uses=uses.get(key, 0), unsure=unsure_only.get(key, False) or split)
        )
        account = _account_for(spelled[key], group)
        if account is not None:
            out.accounts.append(account)
    return out
