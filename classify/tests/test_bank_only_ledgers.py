"""The bank's own ledgers are for what the bank itself did, a title is not a payee, and the model's own guesses are not evidence."""

from types import SimpleNamespace

import pytest

from classify.llm import _BANK_ONLY_LEDGERS, _DECIDED_BY, SYSTEM_PROMPT, _bank_evidence
from classify.models import ClassificationMethod
from classify.narration import analyse


def row(narration, channel=""):
    return SimpleNamespace(channel=channel, transaction=SimpleNamespace(narration=narration))


@pytest.mark.parametrize(
    "narration",
    [
        "DEP TFR UPI/CR/877660980889/SHANKA",
        "DEP TFR P032600626760 IOCL LPG",
        "REMT THRU CHQ RTGS UTR NO: SBIN12345678901",
        "CHQ TRFR FROM 0062139251173 OF Mr. ASHOK",
        "",
    ],
)
def test_a_credit_or_payment_that_does_not_say_interest_is_not_bank_evidence(narration):
    assert not _bank_evidence(row(narration))


@pytest.mark.parametrize(
    "narration", ["INTEREST CREDIT", "TO INTEREST", "004401000001:Int.Pd:31-12-2025 to 29-03-2026"]
)
def test_the_banks_own_words_are_evidence(narration):
    assert _bank_evidence(row(narration))


def test_a_channel_already_read_as_interest_or_a_fee_is_evidence():
    assert _bank_evidence(row("anything", channel="INTEREST"))
    assert _bank_evidence(row("anything", channel="FEE"))


def test_the_bank_only_ledgers_are_the_seeded_ones():
    assert {"bank interest received", "bank charges", "interest paid"} <= _BANK_ONLY_LEDGERS


@pytest.mark.parametrize("name", ["Mr", "Mr.", "MRS", "Smt.", "Shri", "Dr"])
def test_a_payee_cut_off_after_its_title_is_no_payee(name):
    assert analyse(f"DEP TFR UPI/CR/406343817962/{name}").counterparty == ""


def test_a_real_name_after_the_title_is_kept():
    assert analyse("DEP TFR UPI/CR/406343817962/SHANKA").counterparty == "SHANKA"


def test_only_a_persons_or_a_rules_placement_is_shown_to_the_model_as_evidence():
    assert set(_DECIDED_BY) == {ClassificationMethod.REVIEWED, ClassificationMethod.RULE}
    assert ClassificationMethod.LLM not in _DECIDED_BY


def test_the_prompt_says_a_credit_from_a_person_is_never_bank_interest_and_a_poor_fit_is_left_for_a_person():
    assert "never bank interest" in SYSTEM_PROMPT
    assert "never park a row in a bank interest" in SYSTEM_PROMPT
