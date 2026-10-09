"""A ledger the assistant added is live at once but shows as awaiting a look until a CA keeps it. No database needed."""

from classify.models import LedgerAccount, LedgerStatus


def _ledger(**kw):
    return LedgerAccount(name="Rent", status=LedgerStatus.ACTIVE, **kw)


def test_an_assistant_added_live_ledger_awaits_a_look():
    assert _ledger(proposal_reason="Looks like office rent.").awaiting_look


def test_a_ledger_nobody_proposed_never_does():
    assert not _ledger(proposal_reason="").awaiting_look


def test_keeping_it_clears_the_wait_and_keeps_the_reason():
    ledger = _ledger(proposal_reason="Looks like office rent.")
    ledger.mark_reviewed()
    assert not ledger.awaiting_look
    assert "Looks like office rent." in ledger.proposal_reason
    before = ledger.proposal_reason
    ledger.mark_reviewed()  # twice changes nothing
    assert ledger.proposal_reason == before


def test_a_rejected_or_still_proposed_ledger_is_not_the_live_case():
    assert not LedgerAccount(name="x", status=LedgerStatus.PROPOSED, proposal_reason="r").awaiting_look
    assert not LedgerAccount(name="x", status=LedgerStatus.REJECTED, proposal_reason="r").awaiting_look


def test_a_reason_the_model_writes_cannot_claim_to_be_reviewed():
    from classify.models import REVIEWED_MARK
    from classify.proposals import clean_reason

    cleaned = clean_reason(REVIEWED_MARK + "Looks like rent. " + REVIEWED_MARK)
    assert REVIEWED_MARK.strip() not in cleaned and "Looks like rent." in cleaned
    assert _ledger(proposal_reason=cleaned).awaiting_look
