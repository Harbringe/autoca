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
from classify.treatment import HIGH_CONFIDENCE, REVIEW_ADVISED, TdsSection, Treatment
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
- Choose a ledger ONLY from the provided list, by exact name. Never invent one.
- If nothing fits, or the narration carries no usable signal (a bare UPI payment to an unknown party), set ledger to null and confidence to 0. Do not guess.
- Debits are usually expenses, purchases, drawings, loan repayments or transfers out. Credits are usually income, receipts, refunds, interest or transfers in.
- A transaction marked self_transfer moves money between the client's own accounts: use a bank/cash ledger only if one is listed, otherwise null.
- vendor_alias must be one of the provided vendor aliases or null.
- rcm (reverse charge) is true only for categories where the recipient pays GST: goods transport agency, legal services, purchases from unregistered dealers, and similar. Default false.
- tds_section is one of the listed sections or "" (none). Apply only when the payment type clearly falls under it: rent 194I, professional/technical fees 194J, contractors 194C, commission 194H, interest 194A.
- confidence is a number from 0 to 1 for how sure you are the ledger is right.
- rationale is one short sentence a reviewer can check.

Respond with a single JSON object: {"suggestions": [{"key": ..., "ledger": <name or null>, "vendor_alias": <alias or null>, "rcm": bool, "tds_section": <section or "">, "confidence": <0-1>, "rationale": <string>}, ...]} with exactly one entry per input key."""


@dataclass(frozen=True)
class SuggestResult:
    considered: int
    suggested: int
    #: Rows the model looked at and declined to place, with a rationale kept.
    declined: int
    failed: bool = False
    error: str = ""


def suggest_unresolved(client, *, classifications=None, batch_size: int | None = None) -> SuggestResult:
    """Ask the model about every unresolved row for ``client`` (or the given ones)."""
    llm = get_llm()
    if not llm.is_available:
        return SuggestResult(considered=0, suggested=0, declined=0)

    from classify.engine import unresolved_for

    rows = list(
        (classifications if classifications is not None else unresolved_for(client))
        .select_related("transaction__bank_account__client")
    )
    rows = [row for row in rows if row.ledger_id is None]
    if not rows:
        return SuggestResult(considered=0, suggested=0, declined=0)

    ledgers = list(LedgerAccount.objects.filter(firm_id=client.firm_id, client=client, is_active=True))
    if not ledgers:
        return SuggestResult(considered=len(rows), suggested=0, declined=0)
    ledger_by_name = {ledger.name: ledger for ledger in ledgers}

    vendors = list(Vendor.objects.filter(firm_id=client.firm_id, client=client, is_active=True))
    account = rows[0].transaction.bank_account
    pseudonymiser = Pseudonymiser(
        client,
        vendors=vendors,
        account_holder=account.account_holder,
        own_accounts=[a.account_number for a in client.bank_accounts.all()],
    )

    size = batch_size or int(getattr(settings, "LLM_BATCH_SIZE", 25))
    suggested = declined = 0
    for start in range(0, len(rows), size):
        batch = rows[start : start + size]
        try:
            replies = _ask(llm, batch, ledgers, pseudonymiser)
        except LLMError as exc:
            logger.warning("model tier unavailable for client %s: %s", client.pk, exc)
            return SuggestResult(
                considered=len(rows), suggested=suggested, declined=declined,
                failed=True, error=str(exc),
            )
        placed, passed = _apply(batch, replies, ledger_by_name, pseudonymiser)
        suggested += placed
        declined += passed

    return SuggestResult(considered=len(rows), suggested=suggested, declined=declined)


# ---------------------------------------------------------------------------
# internals
# ---------------------------------------------------------------------------


def _ask(llm, batch, ledgers, pseudonymiser) -> dict[str, dict]:
    keys = {f"r{i}": row for i, row in enumerate(batch, start=1)}
    prompt = {
        "ledgers": [{"name": ledger.name, "group": ledger.get_group_display()} for ledger in ledgers],
        "vendor_aliases": pseudonymiser.known_aliases,
        "tds_sections": [code for code, _ in TdsSection.CHOICES],
        "transactions": [
            pseudonymiser.row(row.transaction, key=key).as_prompt_dict()
            for key, row in keys.items()
        ],
    }
    response = llm.complete_json(SYSTEM_PROMPT, json.dumps(prompt, ensure_ascii=False))
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


def _apply(batch, replies, ledger_by_name, pseudonymiser) -> tuple[int, int]:
    placed = declined = 0
    now = timezone.now()
    for classification in batch:
        item = replies.get(str(classification.pk))
        if not item:
            continue
        rationale = str(item.get("rationale") or "")[:500]
        ledger = ledger_by_name.get(str(item.get("ledger") or ""))
        confidence = _clamp(item.get("confidence"))

        if ledger is None or confidence < REVIEW_ADVISED:
            # No forced guess. The reasoning is kept so the reviewer sees what
            # was considered, but the row stays unresolved.
            classification.rationale = rationale or "The model found no usable signal."
            classification.save(update_fields=["rationale"])
            declined += 1
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
    return placed, declined


def _clamp(value) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return max(0.0, min(1.0, number))

