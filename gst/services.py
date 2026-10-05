"""Running a GST reconciliation: load, match, decide, sign off.

The only module that writes ``gst`` rows. Views call these; they do not touch
the models directly, so the rules below hold however a request arrives.

The rules, all enforced here rather than trusted to a caller:

* A run belongs to one GSTIN and one month, and both files must agree with it.
  A GSTR-2B for a different GSTIN or month is refused, not reconciled -- it would
  produce a plausible report about the wrong return.
* A signed-off run is frozen. Nothing loads into it, re-matches it or decides on
  it; a change after sign-off is a reopen, and there is no reopen yet.
* Sign-off is the client's lead or a firm admin (``core.access``), checked here
  as well as in the view.
* Every human decision is appended, never edited, and survives a re-match.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from classify.models import Party
from core.access import require_sign_off
from core.identifiers import is_valid_gstin
from core.identity import invoice_key
from core.models import Client, FirmMembership, User
from documents.models import Document, DocumentKind, DocumentStatus
from gst import matching
from gst.matching import Invoice, ItcStatus, MatchKind, Section
from gst.models import (
    DecisionKind,
    Gstr2bInvoice,
    GstRegistration,
    ReconDecision,
    ReconMatch,
    ReconRun,
    RegisterInvoice,
    RegistrationType,
    RunStatus,
)
from gst.parsers import parse_gstr2b_json, parse_register
from integrations.registry import get_storage


class GstError(RuntimeError):
    """A reconciliation rule refused the request. The message is for a person."""


# ---------------------------------------------------------------------------
# Registrations and runs
# ---------------------------------------------------------------------------


def add_registration(
    client: Client, gstin: str, registration_type: str = RegistrationType.REGULAR
) -> GstRegistration:
    gstin = matching.normalise_gstin(gstin)
    if not is_valid_gstin(gstin):
        raise GstError(f"{gstin or 'That'} is not a valid GSTIN.")
    reg = GstRegistration(
        firm_id=client.firm_id,
        client=client,
        state_code=gstin[:2],
        registration_type=registration_type,
    )
    reg.set_gstin(gstin)
    if GstRegistration.objects.filter(client=client, gstin_hash=reg.gstin_hash).exists():
        raise GstError(f"{gstin} is already registered for {client.name}.")
    reg.save()
    return reg


def get_or_create_run(
    registration: GstRegistration, period_start: datetime.date, user: User | None
) -> ReconRun:
    period_start = period_start.replace(day=1)
    run, _ = ReconRun.objects.get_or_create(
        firm_id=registration.firm_id,
        registration=registration,
        period_start=period_start,
        defaults={"client": registration.client, "created_by": user},
    )
    return run


def _require_open(run: ReconRun) -> None:
    if run.status == RunStatus.SIGNED_OFF:
        raise GstError("This reconciliation has been signed off and can no longer be changed.")


# ---------------------------------------------------------------------------
# Loading files
# ---------------------------------------------------------------------------


def _register_document(run: ReconRun, data: bytes, filename: str, kind, user) -> Document:
    """Keep the uploaded file as evidence, once per distinct content."""
    digest = Document.digest(data)
    doc = Document.objects.filter(firm_id=run.firm_id, sha256=digest).first()
    if doc is not None:
        return doc
    storage = get_storage()
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "bin"
    key = storage.tenant_key(run.firm_id, "clients", str(run.client_id), "gst", f"{digest}.{ext}")
    storage.put(key, data, content_type="application/octet-stream")
    return Document.objects.create(
        firm_id=run.firm_id,
        client=run.client,
        kind=kind,
        sha256=digest,
        original_filename=filename[:255],
        storage_key=key,
        byte_size=len(data),
        status=DocumentStatus.PARSED,
        uploaded_by=user,
    )


def _row_fields(inv: Invoice, firm_id) -> dict:
    return {
        "invoice_no": inv.invoice_no[:64],
        "invoice_date": inv.invoice_date,
        "supplier_name": inv.supplier_name[:255],
        "hsn": inv.hsn[:16],
        "section": inv.section.value,
        "taxable_paise": inv.taxable_paise,
        "igst_paise": inv.igst_paise,
        "cgst_paise": inv.cgst_paise,
        "sgst_paise": inv.sgst_paise,
        "cess_paise": inv.cess_paise,
        "source_row": int(inv.ref.rsplit(":", 1)[-1] or 0),
        "itc_available": inv.itc_available,
        "itc_reason": inv.itc_reason[:16],
        "original_no": inv.original_no[:64],
    }


@transaction.atomic
def load_register(
    run: ReconRun,
    data: bytes,
    filename: str,
    user: User | None,
    *,
    mapping: dict[str, str] | None = None,
) -> int:
    """Replace the run's purchase-register rows with those in the file."""
    _require_open(run)
    invoices = parse_register(data, filename, mapping=mapping)
    run.register_document = _register_document(run, data, filename, DocumentKind.REGISTER, user)
    run.save(update_fields=["register_document"])
    run.register_rows.all().delete()
    rows = []
    for inv in invoices:
        row = RegisterInvoice(
            firm_id=run.firm_id,
            run=run,
            category=inv.category[:128],
            rcm=inv.rcm,
            **_row_fields(inv, run.firm_id),
        )
        row.set_gstin(inv.gstin)
        rows.append(row)
    RegisterInvoice.objects.bulk_create(rows)
    return len(rows)


@transaction.atomic
def load_portal(run: ReconRun, data: bytes, filename: str, user: User | None) -> int:
    """Replace the run's GSTR-2B rows, after checking it is *this* return's 2B."""
    _require_open(run)
    if filename.lower().endswith(".json"):
        parsed = parse_gstr2b_json(data)
        invoices = parsed.invoices
        if parsed.gstin and parsed.gstin != run.registration.gstin:
            raise GstError(
                f"This GSTR-2B is for {parsed.gstin}, but this reconciliation is for "
                f"{run.registration.gstin}."
            )
        if parsed.period_start and parsed.period_start != run.period_start:
            raise GstError(
                f"This GSTR-2B is for {parsed.period_start:%B %Y}, but this reconciliation "
                f"is for {run.period_start:%B %Y}."
            )
    else:
        invoices = parse_register(data, filename, portal=True)
    run.portal_document = _register_document(run, data, filename, DocumentKind.GSTR2B, user)
    run.save(update_fields=["portal_document"])
    run.portal_rows.all().delete()
    rows = []
    for inv in invoices:
        row = Gstr2bInvoice(firm_id=run.firm_id, run=run, **_row_fields(inv, run.firm_id))
        row.set_gstin(inv.gstin)
        rows.append(row)
    Gstr2bInvoice.objects.bulk_create(rows)
    return len(rows)


# ---------------------------------------------------------------------------
# Matching
# ---------------------------------------------------------------------------


def match_key(firm_id, gstin: str, invoice_no: str) -> str:
    """An invoice's identity across re-matches: supplier + normalised number."""
    return invoice_key(firm_id, gstin, invoice_no)


def _as_invoice(row, prefix: str, rcm_parties: set[str]) -> Invoice:
    gstin = row.gstin
    return Invoice(
        ref=f"{prefix}:{row.pk}",
        gstin=gstin,
        invoice_no=row.invoice_no,
        invoice_date=row.invoice_date,
        taxable_paise=row.taxable_paise,
        igst_paise=row.igst_paise,
        cgst_paise=row.cgst_paise,
        sgst_paise=row.sgst_paise,
        cess_paise=row.cess_paise,
        supplier_name=row.supplier_name,
        hsn=row.hsn,
        category=getattr(row, "category", ""),
        section=Section(row.section),
        rcm=getattr(row, "rcm", False) or (row.gstin_hash in rcm_parties),
        blocked=getattr(row, "blocked", False),
        itc_available=row.itc_available,
        itc_reason=row.itc_reason,
        original_no=row.original_no,
    )


def _other_months(run: ReconRun):
    """What the same GSTIN's *other* months say about invoices in this one.

    Two questions a CA answers by flipping between workbooks: is this missing
    invoice in another month's GSTR-2B, and did an earlier month already take
    its credit. Only this registration's runs are consulted, and only rows the
    caller could already see (RLS scopes the queries to the firm regardless).
    """
    others = ReconRun.objects.filter(registration=run.registration).exclude(pk=run.pk)
    other_periods: dict[tuple[str, str], datetime.date] = {}
    for row in Gstr2bInvoice.objects.filter(run__in=others).select_related("run"):
        if row.section in (Section.B2B.value, Section.DN.value):
            other_periods.setdefault(
                (matching.normalise_gstin(row.gstin), matching.normalise_invoice_no(row.invoice_no)),
                row.run.period_start,
            )
    claimed: dict[tuple[str, str], datetime.date] = {}
    # Only earlier months can have "already taken" it; two drafts flagging each
    # other for the same invoice would be noise, not protection.
    taken = ReconMatch.objects.filter(
        run__in=others.filter(period_start__lt=run.period_start), kind=MatchKind.MATCHED.value, eligible_paise__gt=0
    ).select_related("run", "register_invoice")
    for m in taken:
        r = m.register_invoice
        if r is not None:
            claimed.setdefault(
                (matching.normalise_gstin(r.gstin), matching.normalise_invoice_no(r.invoice_no)),
                m.run.period_start,
            )
    return other_periods, claimed


@transaction.atomic
def reconcile_run(run: ReconRun) -> matching.Reconciliation:
    """Match the run's two datasets and store the verdicts, replacing earlier ones."""
    _require_open(run)
    if not run.register_rows.exists():
        raise GstError("Upload the purchase register first.")
    if not run.portal_rows.exists():
        raise GstError("Upload the GSTR-2B first.")

    # A party the client already treats as reverse-charge stays that way here.
    rcm_parties = set(
        Party.objects.filter(client=run.client, rcm_default=True)
        .exclude(gstin_hash="")
        .values_list("gstin_hash", flat=True)
    )
    books = {f"reg:{r.pk}": r for r in run.register_rows.all()}
    portal = {f"2b:{r.pk}": r for r in run.portal_rows.all()}
    other_periods, claimed_elsewhere = _other_months(run)
    result = matching.reconcile(
        [_as_invoice(r, "reg", rcm_parties) for r in books.values()],
        [_as_invoice(r, "2b", set()) for r in portal.values()],
        period_start=run.period_start,
        other_periods=other_periods,
        claimed_elsewhere=claimed_elsewhere,
    )

    run.matches.all().delete()
    ReconMatch.objects.bulk_create(
        ReconMatch(
            firm_id=run.firm_id,
            run=run,
            kind=m.kind.value,
            itc_status=m.itc_status.value,
            register_invoice=books[m.book.ref] if m.book else None,
            portal_invoice=portal[m.portal.ref] if m.portal else None,
            eligible_paise=m.eligible_paise,
            ineligible_paise=m.ineligible_paise,
            cause=m.cause,
            action=m.action,
            differences=m.differences,
            timing=m.timing,
        )
        for m in result.matches
    )
    return result


# ---------------------------------------------------------------------------
# Decisions and sign-off
# ---------------------------------------------------------------------------

#: What may be decided about which kind of row. A decision that could not change
#: anything (claiming credit on an invoice that is not in GSTR-2B) is refused
#: rather than recorded, since a record of it would read as though it had.
_ALLOWED = {
    DecisionKind.ACCEPT_MATCH: {
        MatchKind.POSSIBLE_MATCH,
        MatchKind.AMOUNT_MISMATCH,
        MatchKind.TAX_HEAD_MISMATCH,
    },
    DecisionKind.CLAIM_ITC: {
        MatchKind.POSSIBLE_MATCH,
        MatchKind.AMOUNT_MISMATCH,
        MatchKind.TAX_HEAD_MISMATCH,
    },
    DecisionKind.DISALLOW_ITC: {
        MatchKind.MATCHED,
        MatchKind.POSSIBLE_MATCH,
        MatchKind.AMOUNT_MISMATCH,
        MatchKind.TAX_HEAD_MISMATCH,
        MatchKind.IMPORT,
        MatchKind.ISD_CREDIT,
    },
}


def _key_for(match: ReconMatch) -> str:
    row = match.register_invoice or match.portal_invoice
    return match_key(match.firm_id, row.gstin, row.invoice_no)


@transaction.atomic
def decide(run: ReconRun, match: ReconMatch, kind: str, note: str, user: User) -> ReconDecision:
    _require_open(run)
    if match.run_id != run.pk:
        raise GstError("That row is not part of this reconciliation.")
    kind = DecisionKind(kind)
    if kind in _ALLOWED and MatchKind(match.kind) not in _ALLOWED[kind]:
        raise GstError(
            f"'{kind.label}' does not apply to a row that is "
            f"'{MatchKind(match.kind).value.replace('_', ' ')}'."
        )
    return ReconDecision.objects.create(
        firm_id=run.firm_id, run=run, match_key=_key_for(match), kind=kind, note=note[:2000],
        decided_by=user,
    )


@dataclass(frozen=True)
class Standing:
    """A match with the latest decision on it applied."""

    match: ReconMatch
    decision: ReconDecision | None
    eligible_paise: int
    ineligible_paise: int


def standings(run: ReconRun) -> list[Standing]:
    latest: dict[str, ReconDecision] = {}
    for d in run.decisions.exclude(match_key="").order_by("created_at", "id"):
        if d.kind != DecisionKind.NOTE:
            latest[d.match_key] = d
    out = []
    for m in run.matches.select_related("register_invoice", "portal_invoice"):
        d = latest.get(_key_for(m))
        eligible, ineligible = m.eligible_paise, m.ineligible_paise
        if d is not None:
            if d.kind in (DecisionKind.ACCEPT_MATCH, DecisionKind.CLAIM_ITC) and eligible == 0:
                book, portal = m.register_invoice, m.portal_invoice
                sign = -1 if book.section == Section.CDN.value else 1
                if m.kind == MatchKind.TAX_HEAD_MISMATCH.value:
                    # Credit follows the heads the supplier declared on the portal.
                    credit = sum(getattr(portal, h) for h in matching.TAX_HEADS) * sign
                else:
                    credit = sum(
                        min(getattr(book, h), getattr(portal, h)) for h in matching.TAX_HEADS
                    ) * sign
                # Accepting a match does not lift a blocked category.
                if matching.blocked_reason(_as_invoice(book, "reg", set())):
                    eligible, ineligible = 0, credit
                else:
                    eligible, ineligible = credit, 0
            elif d.kind == DecisionKind.DISALLOW_ITC:
                eligible, ineligible = 0, ineligible + eligible
        out.append(Standing(m, d, eligible, ineligible))
    return out


def unresolved(run: ReconRun) -> int:
    """Rows a person has to look at that nobody has decided yet."""
    needs = {
        MatchKind.POSSIBLE_MATCH.value,
        MatchKind.AMOUNT_MISMATCH.value,
        MatchKind.TAX_HEAD_MISMATCH.value,
    }
    return sum(1 for s in standings(run) if s.match.kind in needs and s.decision is None)


@transaction.atomic
def sign_off_run(run: ReconRun, user: User, membership: FirmMembership | None) -> ReconRun:
    require_sign_off(membership, run.client)
    _require_open(run)
    if not run.matches.exists():
        raise GstError("Run the reconciliation before signing it off.")
    open_rows = unresolved(run)
    if open_rows:
        raise GstError(
            f"{open_rows} mismatched or uncertain invoice(s) have no decision. "
            "Accept, claim, disallow or defer each one before signing off."
        )
    ReconDecision.objects.create(
        firm_id=run.firm_id, run=run, kind=DecisionKind.SIGN_OFF, decided_by=user
    )
    run.status = RunStatus.SIGNED_OFF
    run.signed_off_by = user
    run.signed_off_at = timezone.now()
    run.save(update_fields=["status", "signed_off_by", "signed_off_at"])
    return run


def summarise(run: ReconRun) -> dict:
    """The report's headline numbers, with decisions applied."""
    rows = standings(run)
    counts: dict[str, int] = {}
    eligible = blocked = ineligible = rcm = unclaimed = 0
    for s in rows:
        m = s.match
        counts[m.kind] = counts.get(m.kind, 0) + 1
        eligible += s.eligible_paise
        if m.itc_status == ItcStatus.BLOCKED.value:
            blocked += s.ineligible_paise
        else:
            ineligible += s.ineligible_paise
        if m.kind == MatchKind.RCM.value and m.register_invoice:
            r = m.register_invoice
            rcm += r.igst_paise + r.cgst_paise + r.sgst_paise + r.cess_paise
        if m.kind == MatchKind.MISSING_IN_BOOKS.value and m.portal_invoice:
            p = m.portal_invoice
            unclaimed += p.igst_paise + p.cgst_paise + p.sgst_paise + p.cess_paise
    return {
        "counts": counts,
        "eligible_paise": eligible,
        "blocked_paise": blocked,
        "ineligible_paise": ineligible,
        "rcm_liability_paise": rcm,
        "unclaimed_in_2b_paise": unclaimed,
        "unresolved": unresolved(run),
    }
