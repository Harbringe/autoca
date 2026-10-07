"""The queue for the model tier: rows wait, and a short call reads a few at a time.

An upload used to ask the model about every unresolved row inside its own request,
and a rate limit part-way through abandoned the rest with nothing to say they had
never been read (R1-10). Now the upload only marks such rows as waiting
(:func:`mark_waiting`), and :func:`process_next_batch` reads one small batch per
call, in three phases so that no lock and no transaction is held while the provider
is being asked:

    1. claim    a transaction: ``FOR UPDATE SKIP LOCKED`` over waiting rows, mark them
                claimed for a minute, read what the prompt needs. Committed.
    2. ask      no transaction open. One attempt, a short timeout, and a typed
                :class:`~integrations.llm.base.LLMRateLimited` instead of a sleep.
    3. apply    a transaction: re-read the rows, apply the answers to those still
                unplaced and still ours, auto-post, release the rest. Committed.

Two browsers never read the same row: the second call's claim skips what the first
holds. A call that dies leaves its rows claimed until the claim lapses, and the next
call picks them up. ``model_attempts`` counts claims, so a row that cannot be
answered is left for a person after three rather than looping.

Everything here that touches the database runs in a ``firm_context`` of its own,
because the view that calls it opts out of the request-wide transaction.
"""

from __future__ import annotations

import logging
import math
import time
from dataclasses import asdict, dataclass
from datetime import timedelta

from django.core.cache import cache
from django.db import DatabaseError, transaction
from django.db.models import F, Q
from django.utils import timezone

from classify.llm import _apply, _ask_splitting, _Chart, _context_for
from classify.models import LedgerAccount, ModelState, Party, PartyAlias, TransactionClassification
from classify.pseudonymise import Pseudonymiser
from core.db.session import firm_context
from integrations.llm.base import LLMError, LLMRateLimited
from integrations.registry import get_llm

logger = logging.getLogger("autoca.llm")

DEFAULT_ROWS = 10
MAX_ROWS = 15
#: How long a call may hold its rows. A call is bounded to about this, and a dead one lapses.
CLAIM_SECONDS = 60
MAX_ATTEMPTS = 3
#: After a provider failure: 30 s, then 60, then 120 (and 120 from there).
PROVIDER_BACKOFF_SECONDS = (30, 60, 120)
#: A daily pause is kept at least this long, and never longer than a day.
DAILY_PAUSE_RANGE = (600, 86_400)
#: Asked again this soon when someone else's call is reading the last rows.
OTHER_CALL_RETRY_SECONDS = 5

_DECLINE_NOTE = "The assistant could not read this row after three tries. It is for a person to place."


@dataclass(frozen=True)
class BatchOutcome:
    processed: int
    suggested: int
    declined: int
    #: Rows still waiting for the assistant, including any another call is reading.
    waiting: int
    state: str  # working | idle | paused
    retry_after_seconds: int | None
    reason: str  # "" | rate_limit | daily_limit | provider_down | assistant_off
    message: str
    #: Of the rows suggested, how many were very sure and went straight into the books.
    auto_posted: int = 0
    proposed: int = 0

    def as_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# marking rows
# ---------------------------------------------------------------------------


def mark_waiting(rows) -> int:
    """Queue these rows for the assistant. Returns how many were queued.

    Only rows with no ledger are queued, and a row another call is reading right now is
    left alone, or a second browser would read it twice. Attempts start again from zero:
    this is also what the manual "ask again" does, and a person asking wants a fresh try.
    """
    live_claim = Q(model_state=ModelState.CLAIMED, model_claimed_until__gt=timezone.now())
    return (
        rows.filter(ledger__isnull=True)
        .exclude(live_claim)
        .update(model_state=ModelState.WAITING, model_claimed_until=None, model_attempts=0)
    )


def waiting_count(client) -> int:
    """Unplaced rows still queued for the assistant, whether waiting or being read."""
    from classify.engine import unresolved_for

    return unresolved_for(client).filter(model_state__in=[ModelState.WAITING, ModelState.CLAIMED]).count()


# ---------------------------------------------------------------------------
# the pause: one cache key per firm, so polling costs nothing
# ---------------------------------------------------------------------------


def _pause_key(firm_id) -> str:
    return f"assistant:pause:{firm_id}"


def _current_pause(firm_id) -> dict | None:
    entry = cache.get(_pause_key(firm_id))
    if entry and entry["until"] > time.time():
        return entry
    return None


def _pause(firm_id, *, seconds: float, reason: str, strikes: int = 0) -> dict:
    entry = {"until": time.time() + seconds, "reason": reason, "strikes": strikes}
    # Kept past the pause so the next failure knows how many came before it.
    cache.set(_pause_key(firm_id), entry, timeout=int(seconds) + 600)
    return entry


def _strikes(firm_id) -> int:
    entry = cache.get(_pause_key(firm_id))
    return entry["strikes"] if entry else 0


def _paused_outcome(entry: dict, waiting: int, *, processed=0, declined=0) -> BatchOutcome:
    seconds = max(1, math.ceil(entry["until"] - time.time()))
    reason = entry["reason"]
    if reason == "daily_limit":
        message = (
            f"The assistant has used today's allowance. The remaining {waiting} "
            f"row{'s' if waiting != 1 else ''} wait for a person or for tomorrow."
        )
    elif reason == "rate_limit":
        message = f"The assistant is going too fast for its provider and will resume in {seconds} seconds."
    else:
        message = f"The assistant's provider is not answering. Trying again in {seconds} seconds."
    return BatchOutcome(processed, 0, declined, waiting, "paused", seconds, reason, message)


def assistant_state(firm_id) -> tuple[str, int | None]:
    """What the screens may say about the assistant right now: ``(reason, seconds)``.

    Blank reason is working (or idle, when nothing waits). ``assistant_off`` when no model is set up; otherwise the
    firm-wide pause, with the seconds left. Read from the same cache the worker writes, so polling costs nothing.
    """
    if not get_llm().is_available:
        return "assistant_off", None
    paused = _current_pause(firm_id)
    if paused:
        return paused["reason"], max(1, math.ceil(paused["until"] - time.time()))
    return "", None


# ---------------------------------------------------------------------------
# one batch
# ---------------------------------------------------------------------------


@dataclass
class _Claim:
    rows: list
    waiting: int
    until: object = None
    account_ledger_name: str = ""
    pseudonymiser: Pseudonymiser | None = None
    context: dict | None = None
    chart: _Chart | None = None


def process_next_batch(client, *, max_rows: int | None = None) -> BatchOutcome:
    """Read the next few waiting rows for ``client`` with the model. See the module note."""
    firm_id = client.firm_id
    size = min(max(int(max_rows or DEFAULT_ROWS), 1), MAX_ROWS)

    llm = get_llm()
    if not llm.is_available:
        with firm_context(firm_id):
            left = waiting_count(client)
        return BatchOutcome(
            0, 0, 0, left, "idle", None, "assistant_off",
            "The assistant is switched off, so the rows wait for a person.",
        )

    paused = _current_pause(firm_id)
    if paused:
        with firm_context(firm_id):
            left = waiting_count(client)
        return _paused_outcome(paused, left)

    with firm_context(firm_id):
        claim = _claim(client, size)
    if not claim.rows:
        if claim.waiting:
            return BatchOutcome(
                0, 0, 0, claim.waiting, "working", OTHER_CALL_RETRY_SECONDS, "",
                "Another window is reading the rest.",
            )
        return BatchOutcome(0, 0, 0, 0, "idle", None, "", "Nothing is waiting for the assistant.")

    # No transaction is open here, and no lock is held.
    replies, failure = {}, None
    try:
        replies = _ask_splitting(
            llm.without_waiting(), claim.rows, claim.chart, claim.pseudonymiser, claim.context
        )
    except LLMError as exc:
        failure = exc
        logger.warning("model tier unavailable for client %s: %s", client.pk, exc)

    with firm_context(firm_id):
        if failure is not None:
            return _release_after_failure(client, claim, failure)
        return _apply_batch(client, claim, replies)


def _claim(client, size: int) -> _Claim:
    from classify.engine import unresolved_for

    now = timezone.now()
    queued = unresolved_for(client).filter(
        Q(model_state=ModelState.WAITING) | Q(model_state=ModelState.CLAIMED, model_claimed_until__lt=now)
    )
    order = ("transaction__statement__period_start", "transaction__row_number")
    # One bank account per call, so one call to the model reads one account's rows.
    account_id = (
        queued.order_by(*order).values_list("transaction__bank_account_id", flat=True).first()
    )
    if account_id is None:
        return _Claim(rows=[], waiting=waiting_count(client))

    rows = list(
        queued.filter(transaction__bank_account_id=account_id)
        .select_related("transaction__bank_account__client")
        .order_by(*order)
        .select_for_update(skip_locked=True, of=("self",))[:size]
    )
    spent = [row for row in rows if row.model_attempts >= MAX_ATTEMPTS]
    rows = [row for row in rows if row.model_attempts < MAX_ATTEMPTS]
    _decline(spent)
    if not rows:
        return _Claim(rows=[], waiting=waiting_count(client))

    until = now + timedelta(seconds=CLAIM_SECONDS)
    TransactionClassification.objects.filter(pk__in=[row.pk for row in rows]).update(
        model_state=ModelState.CLAIMED, model_claimed_until=until, model_attempts=F("model_attempts") + 1
    )
    for row in rows:
        row.model_attempts += 1

    account = rows[0].transaction.bank_account
    parties = list(Party.objects.filter(firm_id=client.firm_id, client=client, is_active=True))
    pseudonymiser = Pseudonymiser(
        client,
        parties=parties,
        account_holder=account.account_holder,
        own_accounts=[a.account_number for a in client.bank_accounts.all()],
        spellings=list(PartyAlias.objects.filter(firm_id=client.firm_id, client=client)),
    )
    chart = _Chart(
        client,
        list(LedgerAccount.objects.filter(firm_id=client.firm_id, client=client).select_related("party_record", "employee_record")),
        account.ledger_name,
    )
    return _Claim(
        rows=rows,
        waiting=0,
        until=until,
        account_ledger_name=account.ledger_name,
        pseudonymiser=pseudonymiser,
        context=_context_for(client, rows, pseudonymiser),
        chart=chart,
    )


def _ours(claim: _Claim):
    """The claimed rows that are still ours: not lapsed and taken by another call since."""
    return TransactionClassification.objects.filter(
        pk__in=[row.pk for row in claim.rows],
        model_state=ModelState.CLAIMED,
        model_claimed_until=claim.until,
    )


def _decline(rows) -> None:
    """Leave these rows for a person, with a plain reason if nothing else has been said."""
    for row in rows:
        if not row.rationale:
            row.rationale = _DECLINE_NOTE
        row.model_state = ModelState.DECLINED
        row.model_claimed_until = None
        row.save(update_fields=["rationale", "model_state", "model_claimed_until"])


def _release_after_failure(client, claim: _Claim, failure: LLMError) -> BatchOutcome:
    firm_id = client.firm_id
    if isinstance(failure, LLMRateLimited):
        # Not the rows' fault: released without counting the try.
        _ours(claim).update(
            model_state=ModelState.WAITING, model_claimed_until=None, model_attempts=F("model_attempts") - 1
        )
        daily = failure.daily
        low, high = DAILY_PAUSE_RANGE
        seconds = min(max(failure.retry_after, low), high) if daily else max(failure.retry_after, 1)
        entry = _pause(firm_id, seconds=seconds, reason="daily_limit" if daily else "rate_limit")
        return _paused_outcome(entry, waiting_count(client))

    rows = list(_ours(claim).select_for_update(of=("self",)))
    _decline([row for row in rows if row.model_attempts >= MAX_ATTEMPTS])
    TransactionClassification.objects.filter(
        pk__in=[row.pk for row in rows if row.model_attempts < MAX_ATTEMPTS]
    ).update(model_state=ModelState.WAITING, model_claimed_until=None)
    strikes = _strikes(firm_id) + 1
    backoff = PROVIDER_BACKOFF_SECONDS[min(strikes, len(PROVIDER_BACKOFF_SECONDS)) - 1]
    entry = _pause(firm_id, seconds=backoff, reason="provider_down", strikes=strikes)
    return _paused_outcome(entry, waiting_count(client), processed=len(claim.rows))


def _apply_batch(client, claim: _Claim, replies: dict) -> BatchOutcome:
    from ledger.approval import auto_post

    firm_id = client.firm_id
    rows = list(
        _ours(claim).select_related("transaction__bank_account__client").select_for_update(of=("self",))
    )
    # A person may have placed a claimed row while the model was being asked. Theirs stands.
    open_rows = [row for row in rows if row.ledger_id is None]
    placed_by_others = [row.pk for row in rows if row.ledger_id is not None]

    chart = _Chart(
        client,
        list(LedgerAccount.objects.filter(firm_id=firm_id, client=client).select_related("party_record", "employee_record")),
        claim.account_ledger_name,
    )
    opened_before = chart.proposed = _recent_proposals(client)
    _apply(open_rows, replies, chart, claim.pseudonymiser)

    done, declined, again = [], [], []
    for row in open_rows:
        if str(row.pk) not in replies:
            again.append(row)
        elif row.ledger_id is not None:
            done.append(row)
        else:
            declined.append(row.pk)

    TransactionClassification.objects.filter(pk__in=[row.pk for row in done] + placed_by_others).update(
        model_state=ModelState.DONE, model_claimed_until=None
    )
    TransactionClassification.objects.filter(pk__in=declined).update(
        model_state=ModelState.DECLINED, model_claimed_until=None
    )
    # No answer for a row is a failed try, not a decision: back to waiting until the third.
    _decline([row for row in again if row.model_attempts >= MAX_ATTEMPTS])
    TransactionClassification.objects.filter(
        pk__in=[row.pk for row in again if row.model_attempts < MAX_ATTEMPTS]
    ).update(model_state=ModelState.WAITING, model_claimed_until=None)

    auto_posted = 0
    for row in done:
        try:
            with transaction.atomic():
                if auto_post(row) is not None:
                    auto_posted += 1
        except DatabaseError:
            continue

    cache.delete(_pause_key(firm_id))
    left = waiting_count(client)
    return BatchOutcome(
        processed=len(claim.rows),
        suggested=len(done),
        declined=len(declined) + len([row for row in again if row.model_attempts >= MAX_ATTEMPTS]),
        waiting=left,
        state="working" if left else "idle",
        retry_after_seconds=None,
        reason="",
        message=(
            f"The assistant is reading; {left} row{'s' if left != 1 else ''} to go."
            if left
            else "The assistant has read every row."
        ),
        auto_posted=auto_posted,
        proposed=chart.proposed - opened_before,
    )


def _recent_proposals(client) -> int:
    """Ledgers the assistant opened for this client in the last hour.

    The cap on new ledgers used to be per run; a run is now ten rows, so the same cap
    per hour keeps one odd statement from burying the chart under one-row ledgers.
    """
    return LedgerAccount.objects.filter(
        firm_id=client.firm_id,
        client=client,
        created_at__gte=timezone.now() - timedelta(hours=1),
    ).exclude(proposal_reason="").count()
