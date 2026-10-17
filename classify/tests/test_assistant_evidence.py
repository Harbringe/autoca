"""A payee cut off after its title is no payee, the model's own guesses are not shown back to it as evidence, and it is asked whether the ledger really fits."""

import pytest

from classify.llm import _DECIDED_BY, NEW_LEDGER_BAR, SYSTEM_PROMPT
from classify.models import ClassificationMethod
from classify.narration import analyse


@pytest.mark.parametrize("name", ["Mr", "Mr.", "MRS", "Smt.", "Shri", "Dr"])
def test_a_payee_cut_off_after_its_title_is_no_payee(name):
    assert analyse(f"DEP TFR UPI/CR/406343817962/{name}").counterparty == ""


def test_a_real_name_after_the_title_is_kept():
    assert analyse("DEP TFR UPI/CR/406343817962/SHANKA").counterparty == "SHANKA"


def test_only_a_persons_or_a_rules_placement_is_shown_to_the_model_as_evidence():
    assert set(_DECIDED_BY) == {ClassificationMethod.REVIEWED, ClassificationMethod.RULE}
    assert ClassificationMethod.LLM not in _DECIDED_BY


def test_the_model_is_asked_whether_the_ledger_fits_and_told_what_a_poor_fit_means():
    assert '"fit": bool' in SYSTEM_PROMPT
    assert "nothing here fits" in SYSTEM_PROMPT


def test_a_missing_head_is_opened_at_half_confidence():
    assert NEW_LEDGER_BAR == 0.5


@pytest.mark.parametrize(
    "narration", ["INTEREST CREDIT", "TO INTEREST", "004401000001:Int.Pd:31-12-2025 to 29-03-2026"]
)
def test_the_banks_own_words_say_it_was_the_bank(narration):
    from classify.seeds import bank_said_so

    assert bank_said_so(narration)


@pytest.mark.parametrize(
    "narration",
    [
        "DEP TFR UPI/CR/877660980889/SHANKA",
        "DEP TFR P032600626760 IOCL LPG",
        "REMT THRU CHQ RTGS UTR NO: 123",
        "",
        "UPI/CR/123456789012/SHANKAR/INTEREST",
        "DEP TFR UPI/CR/406343817962/RAJESH/interest",
        "IMPS/P2A/123456789012/RAJESH/INTEREST",
        "NEFT-SBIN123-RAJESH-INTEREST PAID",
    ],
)
def test_a_credit_or_payment_that_does_not_say_interest_is_not_the_bank(narration):
    from classify.seeds import bank_said_so

    assert not bank_said_so(narration)
