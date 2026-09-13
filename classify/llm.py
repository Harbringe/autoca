"""The model tier: a suggestion for what the rules could not place.

Where this sits in the loop, and what it may and may not do:

    classify_statement()   rules place what they can
    suggest_unresolved()   THIS -- the model suggests for the rest
    review() / approve()   a person decides; a rule is learned

Three rules bound it.

**It only ever suggests.** A model-sourced classification lands in the review
queue with ``method=LLM`` and a confidence the model reported, capped below the
high-confidence band. It can never be bulk-approved; a person looks at every
one. The requirements are explicit that a confident wrong answer is worse than
an honest "I don't know", so a suggestion the model itself rates below the
review threshold is not recorded as a suggestion at all -- the row stays
unresolved with the model's reasoning attached, so the reviewer at least knows
what was considered.

**It only sees pseudonymised rows** (:mod:`classify.pseudonymise`), and only
the client's ledger names and vendor aliases. It answers with a ledger *name*,
which is checked against the list it was given. A name it invented is
discarded; a vendor alias it invented is discarded.

**It cannot fail the pipeline.** A provider outage, a malformed reply, a
timeout: logged, counted, and the rows stay in the queue for a person. The
statement upload that triggered it has already succeeded.

Batched per statement, because classification is not latency-sensitive and a
system prompt carrying the chart of accounts is identical across rows.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from django.conf import settings
from django.utils import timezone

from classify.models import ClassificationMethod, LedgerAccount, Vendor
from classify.pseudonymise import Pseudonymiser
from classify.treatment import HIGH_CONFIDENCE, REVIEW_ADVISED, TdsSection, Treatment, band_for
from integrations.llm.base import LLMError
from integrations.registry import get_llm

logger = logging.getLogger("autoca.llm")

#: The most a model-sourced suggestion may claim. Strictly below the band that
#: is eligible for bulk approval: a model suggestion is reviewed by a person,
#: always, and this is the number that enforces it.
LLM_CONFIDENCE_CAP = HIGH_CONFIDENCE - 0.01

SYSTEM_PROMPT = """You are a bookkeeping assistant for an Indian chartered accountancy firm. You classify bank statement transactions into the client's chart of accounts.

You will receive a list of transactions. Each has: a key, the channel (UPI/NEFT/IMPS/etc.), the direction (debit = money left the bank account, credit = money came in), a coarse amount band, the counterparty as an anonymised token or a business name, the payer's remark if any, and the narration with identifiers masked as <ACCT>, <PAN>, <GSTIN> and similar.

Rules:
- Prefer a ledger from "ledgers" or "proposed_ledgers", by exact name.
- Only if none of them fits AND the transaction clearly belongs to a category the client lacks, set ledger to null and propose one in new_ledger: {"name": ..., "group": ...}. Take the name from "standard_ledgers" when one fits; otherwise a short conventional Indian bookkeeping name. group must be one of "proposable_groups". Never propose anything in "rejected_ledger_names" or a near-duplicate of an existing ledger. Never propose a bank, cash or suspense ledger, and never a ledger named after a person.
- If the narration carries no usable signal (a bare UPI payment to an unknown party, a transfer with no remark), set ledger and new_ledger to null and confidence to 0. Do not guess, and do not propose a ledger to hold unexplained amounts.
- Debits are usually expenses, purchases, drawings, loan repayments or transfers out. Credits are usually income, receipts, refunds, interest or transfers in.
- A transaction marked self_transfer moves money between the client's own accounts: use a bank/cash ledger only if one is listed, otherwise null.
- vendor_alias must be one of the provided vendor aliases or null.
- rcm (reverse charge) is true only for categories where the recipient pays GST: goods transport agency, legal services, purchases from unregistered dealers, and similar. Default false.
- tds_section is one of the listed sections or "" (none). Apply only when the payment type clearly falls under it: rent 194I, professional/technical fees 194J, contractors 194C, commission 194H, interest 194A.
- confidence is a number from 0 to 1 for how sure you are the ledger is right.
- rationale is one short sentence a reviewer can check.

Respond with a single JSON object: {"suggestions": [{"key": ..., "ledger": <name or null>, "new_ledger": <{"name", "group"} or null>, "vendor_alias": <alias or null>, "rcm": bool, "tds_section": <section or "">, "confidence": <0-1>, "rationale": <string>}, ...]} with exactly one entry per input key."""


@dataclass(frozen=True)
class SuggestResult:
    considered: int
    suggested: int
    #: Rows the model looked at and declined to place, with a rationale kept.
    declined: int
    failed: bool = False
    error: str = ""
    #: Rows already placed by a rule that the model agreed with; left as they were.
    confirmed: int = 0
    #: New ledgers the model proposed this run, awaiting a CA.
    proposed: int = 0


#: A ceiling on new proposals per run, so one odd statement cannot bury the
#: chart of accounts under a pile of one-row ledgers.
MAX_PROPOSALS_PER_RUN = 12


class _Chart:
    """The ledgers one batch may use, and the door to proposing a new one."""

    def __init__(self, client, known, own_ledger_name):
        from classify.models import LedgerStatus

        self.client = client
        self.known = known
        self.own = own_ledger_name
        self.status = LedgerStatus
        self.proposed = 0

    @property
    def usable(self):
        return [
            ledger for ledger in self.known
            if ledger.is_active
            and ledger.status in (self.status.ACTIVE, self.status.PROPOSED)
            and ledger.name != self.own
        ]

    def by_name(self, name):
        return next((ledger for ledger in self.usable if ledger.name == name), None)

    def propose(self, spec, reason):
        from classify.proposals import resolve_proposal

        if not isinstance(spec, dict):
            return None
        before = len(self.known)
        ledger = resolve_proposal(
            self.client, spec.get("name"), spec.get("group"), reason,
            known=self.known, excluded_names=(self.own,),
            allow_new=self.proposed < MAX_PROPOSALS_PER_RUN,
        )
        if len(self.known) > before:
            self.proposed += 1
        return ledger


def suggest_unresolved(client, *, classifications=None, batch_size: int | None = None) -> SuggestResult:
    """Ask the model about every unresolved row for ``client`` (or the given ones)."""
    from classify.engine import unresolved_for

    rows = classifications if classifications is not None else unresolved_for(client)
    return _suggest(client, rows, batch_size=batch_size, replace=False)


def recategorize(client, *, statement=None, batch_size: int | None = None) -> SuggestResult:
    """Ask the model again about every row no person has decided and nobody has posted.

    Where the model agrees with a rule's placement, the rule's placement stands.
    Where it disagrees, the row becomes a model suggestion -- capped below HIGH,
    so a person has to look at the disagreement before it can be posted. Where
    it declines, the existing placement stands with the reasoning attached.
    """
    from classify.engine import not_decided_by_a_person

    return _suggest(
        client, not_decided_by_a_person(client, statement), batch_size=batch_size, replace=True
    )


def _suggest(client, classifications, *, batch_size, replace: bool) -> SuggestResult:
    llm = get_llm()
    if not llm.is_available:
        return SuggestResult(considered=0, suggested=0, declined=0)

    rows = list(classifications.select_related("transaction__bank_account__client"))
    if not replace:
        rows = [row for row in rows if row.ledger_id is None]
    if not rows:
        return SuggestResult(considered=0, suggested=0, declined=0)

    # Every ledger in any status: proposals are checked against rejected names too.
    known = list(LedgerAccount.objects.filter(firm_id=client.firm_id, client=client))
    vendors = list(Vendor.objects.filter(firm_id=client.firm_id, client=client, is_active=True))
    own_accounts = [a.account_number for a in client.bank_accounts.all()]

    by_account: dict = {}
    for row in rows:
        by_account.setdefault(row.transaction.bank_account, []).append(row)

    size = batch_size or int(getattr(settings, "LLM_BATCH_SIZE", 25))
    suggested = declined = confirmed = 0
    chart = _Chart(client, known, "")
    for account, account_rows in by_account.items():
        # The account the rows came from is the other side of every entry, so
        # it can never be the ledger a row is placed in -- that would post
        # Dr Bank / Cr Bank. Another of the client's accounts remains a valid
        # contra for a self-transfer.
        chart.own = account.ledger_name
        pseudonymiser = Pseudonymiser(
            client, vendors=vendors, account_holder=account.account_holder, own_accounts=own_accounts
        )
        for start in range(0, len(account_rows), size):
            batch = account_rows[start : start + size]
            try:
                replies = _ask_splitting(llm, batch, chart, pseudonymiser)
            except LLMError as exc:
                logger.warning("model tier unavailable for client %s: %s", client.pk, exc)
                return SuggestResult(
                    considered=len(rows), suggested=suggested, declined=declined,
                    failed=True, error=str(exc), confirmed=confirmed, proposed=chart.proposed,
                )
            placed, passed, agreed = _apply(batch, replies, chart, pseudonymiser)
            suggested += placed
            declined += passed
            confirmed += agreed

    return SuggestResult(
        considered=len(rows), suggested=suggested, declined=declined, confirmed=confirmed,
        proposed=chart.proposed,
    )


# ---------------------------------------------------------------------------
# internals
# ---------------------------------------------------------------------------


#: Signs the reply was cut off or malformed, which a smaller batch usually fixes.
_SPLITTABLE = ("json_validate_failed", "agreed shape", "not JSON")


def _ask_splitting(llm, batch, chart, pseudonymiser) -> dict[str, dict]:
    """Ask about a batch; if the reply is cut off, ask about each half instead."""
    try:
        return _ask(llm, batch, chart, pseudonymiser)
    except LLMError as exc:
        if len(batch) < 2 or not any(sign in str(exc) for sign in _SPLITTABLE):
            raise
        logger.info("model reply unusable for %d rows (%s); splitting the batch", len(batch), exc)
        middle = len(batch) // 2
        return {
            **_ask_splitting(llm, batch[:middle], chart, pseudonymiser),
            **_ask_splitting(llm, batch[middle:], chart, pseudonymiser),
        }


def _ask(llm, batch, chart, pseudonymiser) -> dict[str, dict]:
    from classify.standard_ledgers import PROPOSABLE_GROUPS, STANDARD_LEDGERS

    keys = {f"r{i}": row for i, row in enumerate(batch, start=1)}
    usable = chart.usable
    taken = {ledger.name for ledger in chart.known}
    prompt = {
        "ledgers": [
            {"name": ledger.name, "group": ledger.get_group_display()}
            for ledger in usable if not ledger.is_proposed
        ],
        "proposed_ledgers": [
            {"name": ledger.name, "group": ledger.get_group_display()}
            for ledger in usable if ledger.is_proposed
        ],
        "rejected_ledger_names": [
            ledger.name for ledger in chart.known if ledger.status == chart.status.REJECTED
        ],
        "standard_ledgers": [
            {"name": name, "group": group} for name, group in STANDARD_LEDGERS if name not in taken
        ],
        "proposable_groups": sorted(PROPOSABLE_GROUPS),
        "vendor_aliases": pseudonymiser.known_aliases,
        "tds_sections": [code for code, _ in TdsSection.CHOICES],
        "transactions": [
            pseudonymiser.row(row.transaction, key=key).as_prompt_dict()
            for key, row in keys.items()
        ],
    }
    # Reasoning models spend part of this budget thinking before they answer; a
    # budget that only fits the answer truncates it, and JSON mode then rejects it.
    response = llm.complete_json(
        SYSTEM_PROMPT,
        json.dumps(prompt, ensure_ascii=False),
        max_tokens=int(getattr(settings, "LLM_MAX_TOKENS", 8192)),
    )
    logger.info(
        "model tier: %d rows, %d in / %d out tokens, model=%s",
        len(batch), response.input_tokens, response.output_tokens, response.model,
    )
    try:
        parsed = json.loads(response.text)
        items = parsed["suggestions"] if isinstance(parsed, dict) else parsed
        replies = {}
        for item in items:
            key = str(item.get("key", ""))
            if key in keys:
                replies[key] = item
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise LLMError("The model's reply did not have the agreed shape.") from exc
    return {str(keys[key].pk): item for key, item in replies.items()}


def _apply(batch, replies, chart, pseudonymiser) -> tuple[int, int, int]:
    placed = declined = confirmed = 0
    now = timezone.now()
    for classification in batch:
        item = replies.get(str(classification.pk))
        if not item:
            continue
        rationale = str(item.get("rationale") or "")[:500]
        confidence = _clamp(item.get("confidence"))
        ledger = chart.by_name(str(item.get("ledger") or ""))
        if ledger is None and item.get("new_ledger") and confidence >= REVIEW_ADVISED:
            if classification.method == ClassificationMethod.RULE:
                # A rule placed this row in a ledger that is in use; a proposal
                # may not displace it, or an approvable row becomes unapprovable
                # until someone accepts a ledger the rule never needed.
                ledger = None
            else:
                ledger = chart.propose(item.get("new_ledger"), rationale)

        if ledger is None or confidence < REVIEW_ADVISED:
            # No forced guess. The reasoning is kept so the reviewer sees what
            # was considered. A rule's placement stands; an earlier model
            # suggestion the model no longer stands behind does not.
            classification.rationale = rationale or "The model found no usable signal."
            fields = ["rationale"]
            if classification.method == ClassificationMethod.LLM:
                classification.ledger = classification.vendor = None
                classification.rcm = False
                classification.tds_section = ""
                classification.method = ClassificationMethod.UNRESOLVED
                classification.confidence = 0.0
                classification.review_band = band_for(0.0)
                classification.needs_review = True
                fields += ["ledger", "vendor", "rcm", "tds_section", "method", "confidence", "review_band", "needs_review"]
            classification.save(update_fields=fields)
            declined += 1
            continue

        if (
            classification.method == ClassificationMethod.RULE
            and classification.ledger_id == ledger.pk
        ):
            # Agreement with a rule adds nothing but a second opinion. Replacing
            # it would demote a bulk-approvable row to a capped suggestion.
            classification.rationale = rationale
            classification.save(update_fields=["rationale"])
            confirmed += 1
            continue

        vendor = pseudonymiser.vendor_for_alias(item.get("vendor_alias") or "")
        tds = str(item.get("tds_section") or "")
        if tds not in {code for code, _ in TdsSection.CHOICES}:
            tds = ""
        classification.apply(
            Treatment(ledger=ledger, vendor=vendor, rcm=bool(item.get("rcm")), tds_section=tds),
            method=ClassificationMethod.LLM,
            confidence=min(confidence, LLM_CONFIDENCE_CAP),
        )
        classification.rationale = rationale
        classification.needs_review = True
        classification.reviewed_at = None
        classification.save(
            update_fields=[
                "ledger", "vendor", "rcm", "tds_section", "method", "rule",
                "confidence", "review_band", "needs_review", "rationale", "reviewed_at",
            ]
        )
        placed += 1
    logger.debug("model tier applied %d suggestions at %s", placed, now)
    return placed, declined, confirmed


def _clamp(value) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, number))

