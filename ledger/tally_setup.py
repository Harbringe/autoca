"""Setting a client up from the Tally files themselves: the ledgers and bank accounts the files use.

``discover_files`` reads the files and proposes what to create, writing nothing. ``apply_setup`` creates exactly what a person confirmed:
the ledgers, each in the group they chose, and the bank accounts, each tied to the ledger of the same name so the bank vouchers find it.
Nothing is renamed or regrouped; a ledger the client already has is left alone.
"""

from __future__ import annotations

import re
from dataclasses import asdict

from django.conf import settings
from django.db import transaction

from banking.models import AccountKind, BankAccount
from classify.models import LedgerAccount, LedgerGroup
from ledger.tally_bankreport import looks_like_bank_report, parse_bank_report
from ledger.tally_discover import discover, master_groups
from ledger.tally_import import TallyImportError, _require_rights
from ledger.tally_parse import (
    TallyParseError,
    TallyTooLargeError,
    _decode,
    clean_text,
    normal_name,
    parse_masters,
)
from ledger.tally_vouchers import parse_vouchers

MAX_FILES = 12
_DIGITS = re.compile(r"\d{3,}")

#: The group a bank, loan or card account's own ledger sits in.
_ACCOUNT_GROUP = {AccountKind.BANK: LedgerGroup.BANK, AccountKind.LOAN: LedgerGroup.LOAN, AccountKind.CARD: LedgerGroup.CURRENT_LIABILITY}


_MASTER_LEDGER = re.compile(r"<LEDGER[ >]")
_VOUCHER = re.compile(r"<VOUCHER[ >]")


def looks_like_masters(filename: str, data: bytes) -> bool:
    """A Tally ledger-masters export (the list of ledgers with each one's group), as opposed to vouchers or a bank report.

    A spreadsheet or csv is only ever masters here, since vouchers and bank reports come as XML. In XML a masters export has LEDGER
    elements and no VOUCHER elements. Tally writes UTF-16 as often as UTF-8, so the text is decoded the way the readers do.
    """
    if (filename or "").lower().endswith((".xlsx", ".csv")):
        return True
    try:
        text = _decode(data)
    except TallyParseError:
        return False
    return bool(_MASTER_LEDGER.search(text)) and not _VOUCHER.search(text)


def _subject_for(filename: str, names: set[str], given: str) -> str:
    """The bank ledger a report is for: the one the person named, else a ledger whose name ends in the digits in the file's name."""
    if given.strip():
        return " ".join(given.split())
    digits = _DIGITS.findall(filename)
    for token in digits:
        matches = sorted(n for n in names if normal_name(n).endswith(token) and re.search(r"[a-z]", normal_name(n)))
        if len(matches) == 1:
            return matches[0]
    return ""


def discover_files(client, membership, files: list[tuple[str, bytes]], bank_ledgers: dict[str, str] | None = None) -> dict:
    """What the files imply for this client. Writes nothing."""
    _require_rights(membership, client)
    if not files:
        raise TallyImportError("Choose at least one file.")
    if len(files) > MAX_FILES:
        raise TallyImportError(f"Choose at most {MAX_FILES} files at a time.")
    bank_ledgers = bank_ledgers or {}
    cap = settings.MAX_TALLY_IMPORT_BYTES
    vouchers, loaded_reports, voucher_files, masters, master_files = [], [], 0, {}, 0
    #: Files that could not be used (a GST report, a spreadsheet that is not a ledger list), each with why. One of them does not stop the rest.
    ignored: list[dict[str, str]] = []
    first_refusal: Exception | None = None
    for name, data in files:
        try:
            if looks_like_bank_report(data):
                loaded_reports.append((name, parse_bank_report(data, name, max_bytes=cap)))
            elif looks_like_masters(name, data):
                masters.update(master_groups(parse_masters(data, name, max_bytes=cap)))
                master_files += 1
            else:
                parsed = parse_vouchers(data, name, max_bytes=cap)
                if len(parsed.companies) > 1:
                    raise TallyImportError(f"{name} has vouchers from more than one company. Export one company at a time.")
                vouchers.extend(parsed.vouchers)
                voucher_files += 1
        except (TallyParseError, TallyTooLargeError) as exc:
            first_refusal = first_refusal or exc
            ignored.append({"file": name, "reason": str(exc)})
    if ignored and not (vouchers or loaded_reports or masters):
        raise first_refusal  # nothing usable at all: say what was wrong with the first file, as before

    seen = {line.ledger for v in vouchers for line in v.lines} | {row.counter for _n, r in loaded_reports for row in r.rows}
    reports, named = [], []
    for name, report in loaded_reports:
        subject = _subject_for(name, seen, bank_ledgers.get(name, ""))
        reports.append({"file": name, "ledger": subject, "rows": len(report.rows), "left_out": len(report.skipped)})
        if subject:
            named.append((subject, report))
    existing = {normal_name(n) for n in LedgerAccount.objects.filter(firm_id=client.firm_id, client=client).values_list("name", flat=True)}
    found = discover(vouchers, named, existing, masters)
    have_accounts = {
        normal_name(n) for n in BankAccount.objects.filter(firm_id=client.firm_id, client=client).values_list("ledger_name", flat=True)
    }
    return {
        "vouchers": len(vouchers),
        "voucher_files": voucher_files,
        "master_files": master_files,
        "ignored": ignored,
        "reports": reports,
        "ledgers": [asdict(p) for p in found.ledgers],
        # A bank account whose ledger the client already has an account for is not proposed twice.
        "accounts": [asdict(a) for a in found.accounts if normal_name(a.ledger) not in have_accounts],
    }


def apply_setup(client, membership, user, *, ledgers: list[dict], accounts: list[dict]) -> dict:
    """Create the ledgers and bank accounts a person confirmed. All or nothing."""
    _require_rights(membership, client)
    valid_groups = {g for g, _label in LedgerGroup.choices}
    existing = {normal_name(a.name): a for a in LedgerAccount.objects.filter(firm_id=client.firm_id, client=client)}
    made = 0
    with transaction.atomic():
        for item in ledgers:
            name = clean_text(item.get("name"), what="ledger name")
            group = item.get("group")
            if group not in valid_groups:
                raise TallyImportError(f"{name!r} needs one of our groups.")
            if normal_name(name) in existing:
                continue
            existing[normal_name(name)] = LedgerAccount.objects.create(firm_id=client.firm_id, client=client, name=name, group=group)
            made += 1
        opened, waiting = 0, []
        for item in accounts:
            ledger_name = clean_text(item.get("ledger"), what="ledger name")
            number = (item.get("account_number") or "").strip()
            kind = item.get("kind")
            if kind not in AccountKind.values:
                raise TallyImportError(f"{ledger_name!r} must be a bank, loan or card account.")
            if not number:
                waiting.append(ledger_name)  # the account needs its number before it can be opened
                continue
            ledger = existing.get(normal_name(ledger_name))
            wanted = _ACCOUNT_GROUP[kind]
            if ledger is None:
                ledger = existing[normal_name(ledger_name)] = LedgerAccount.objects.create(
                    firm_id=client.firm_id, client=client, name=ledger_name, group=wanted
                )
            elif ledger.group != wanted:
                raise TallyImportError(f"{ledger_name!r} is in the {ledger.get_group_display()} group, which does not fit a {kind.lower()} account.")
            code = clean_text(item.get("bank_code") or "BANK", what="bank")[:16].upper()
            account = BankAccount(firm_id=client.firm_id, client=client, kind=kind, bank_code=code, ledger_name=ledger.name)
            account.set_account_number(number)
            if BankAccount.objects.filter(
                firm_id=client.firm_id, client=client, bank_code=code, account_number_hash=account.account_number_hash
            ).exists():
                continue
            account.save()
            opened += 1
    return {"ledgers": made, "accounts": opened, "waiting_for_a_number": waiting}


__all__ = ["TallyParseError", "apply_setup", "discover_files"]
