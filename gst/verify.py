"""Checking a GSTIN against the GST portal, through the configured provider.

Informs a person; never changes a party, an invoice or the books, and booking never waits on it. An answer is reused for
``REUSE_DAYS`` so a supplier on forty invoices is looked up once a month, and a firm may make at most
``settings.GSTIN_CHECKS_PER_MONTH`` live lookups a month so a loop cannot run up the provider's bill.
"""

from __future__ import annotations

import dataclasses
import datetime
from dataclasses import dataclass

from django.conf import settings
from django.db import connection, transaction
from django.db.models import Sum
from django.utils import timezone

from core import names
from core.identifiers import is_valid_gstin
from core.identity import normalise_gstin
from gst.models import GstinCheck
from integrations.gstverify.base import GstinLookupError, GstinNotFound, TaxpayerDetails
from integrations.registry import get_gstverify

REUSE_DAYS = 30
#: The soonest the same GSTIN may be asked of the portal again, even on request.
REFRESH_MIN_MINUTES = 60


class GstinCheckRefused(RuntimeError):
    """The check was not made (bad GSTIN, monthly cap). The message is for a person."""


@dataclass(frozen=True)
class CheckResult:
    gstin: str
    #: "found", "not_found" (the portal has no such GSTIN) or "unavailable" (could not ask and nothing is on file).
    outcome: str
    details: dict
    status: str
    checked_at: datetime.datetime | None
    #: True when the answer is an earlier one: reused, or the last known after a failed attempt.
    from_cache: bool
    provider: str = ""
    message: str = ""


def _provider_name() -> str:
    return type(get_gstverify()).__name__


def _month_start(now: datetime.datetime) -> datetime.datetime:
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def lookups_this_month(firm_id) -> int:
    """Live lookups the firm has made this month, every one counted, including repeats of the same GSTIN."""
    month = _month_start(timezone.now()).date()
    return GstinCheck.objects.filter(firm_id=firm_id, counted_month=month).aggregate(n=Sum("month_lookups"))["n"] or 0


def check_gstin(firm_id, gstin: str, *, refresh: bool = False) -> CheckResult:
    gstin = normalise_gstin(gstin)
    if not is_valid_gstin(gstin):
        raise GstinCheckRefused(f"{gstin or 'That'} is not a valid GSTIN.")
    # One firm's checks run one at a time: the hour's wait, the month's allowance, the provider call and the count that
    # records it all happen under this lock, so two requests at once cannot both pass the same check. A firm's lookups wait
    # on each other for the length of one provider call; other firms are unaffected.
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", [f"gstin-check:{firm_id}"])
        return _check_locked(firm_id, gstin, refresh)


def _check_locked(firm_id, gstin: str, refresh: bool) -> CheckResult:
    row = GstinCheck(firm_id=firm_id)
    row.set_gstin(gstin)
    existing = GstinCheck.objects.filter(firm_id=firm_id, gstin_hash=row.gstin_hash).first()
    now = timezone.now()
    if existing is not None and not refresh and now - existing.checked_at < datetime.timedelta(days=REUSE_DAYS):
        return _result(existing, from_cache=True)

    if existing is not None and now - existing.checked_at < datetime.timedelta(minutes=REFRESH_MIN_MINUTES):
        return _result(existing, from_cache=True)
    if lookups_this_month(firm_id) >= settings.GSTIN_CHECKS_PER_MONTH:
        if existing is not None:
            return dataclasses.replace(_result(existing, from_cache=True), message="This month's allowance of GSTIN checks is used up; showing the last answer.")
        raise GstinCheckRefused("This month's allowance of GSTIN checks for the firm is used up.")

    try:
        details = get_gstverify().lookup(gstin)
    except GstinNotFound:
        _save(existing or row, status="not found", details={}, now=now)
        return CheckResult(gstin, "not_found", {}, "not found", now, False, _provider_name(), "The portal has no record of this GSTIN.")
    except GstinLookupError as exc:
        if existing is not None:
            return dataclasses.replace(_result(existing, from_cache=True), message=f"Could not check just now ({exc}); showing the last answer.")
        return CheckResult(gstin, "unavailable", {}, "", None, False, _provider_name(), f"Could not check just now ({exc}).")

    saved = _save(existing or row, status=(details.status or "").lower(), details=_details_dict(details), now=now)
    return _result(saved, from_cache=False)


def _details_dict(d: TaxpayerDetails) -> dict:
    out = dataclasses.asdict(d)
    out.pop("gstin", None)
    return out


def _save(row: GstinCheck, *, status: str, details: dict, now) -> GstinCheck:
    month = _month_start(now).date()
    row.month_lookups = (row.month_lookups + 1) if row.counted_month == month else 1
    row.counted_month = month
    row.status = status[:24]
    row.set_details(details)
    row.provider = _provider_name()[:32]
    row.checked_at = now
    row.save()
    return row


def _result(row: GstinCheck, *, from_cache: bool) -> CheckResult:
    details = row.details
    found = row.status != "not found"
    return CheckResult(
        row.gstin, "found" if found else "not_found", details, row.status, row.checked_at, from_cache, row.provider,
        "" if found else "The portal has no record of this GSTIN.",
    )


def _same(a: str, b: str) -> bool:
    return names.same_business(a, b) or (bool(names.tokens(a)) and names.tokens(a) == names.tokens(b))


def compare_with_party(result: CheckResult, party_name: str) -> dict:
    """How the portal's names sit beside the party's name in the books. A mismatch is shown, never fixed."""
    portal = [n for n in (result.details.get("legal_name"), result.details.get("trade_name")) if n]
    return {
        "name_matches": any(_same(party_name, n) for n in portal) if portal else None,
        "cancelled": result.status in ("cancelled", "suspended"),
    }
