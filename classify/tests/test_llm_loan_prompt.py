"""The model is told when it is reading a loan, because the standing rules would file an instalment as income.

The standing prompt reads a credit as "usually sales or receipts". On a loan statement a credit is an instalment, so
a loan batch gets an extra note, and a bank batch gets exactly the prompt it always did.
"""

from __future__ import annotations

from types import SimpleNamespace

from classify.llm import LOAN_ADDENDUM, SYSTEM_PROMPT, system_prompt_for


def _batch(kind):
    return [SimpleNamespace(transaction=SimpleNamespace(bank_account=SimpleNamespace(kind=kind)))]


def test_a_bank_batch_gets_the_standing_prompt_unchanged():
    assert system_prompt_for(_batch("BANK")) == SYSTEM_PROMPT


def test_a_loan_batch_gets_the_loan_note_appended():
    prompt = system_prompt_for(_batch("LOAN"))

    assert prompt.startswith(SYSTEM_PROMPT)
    assert prompt.endswith(LOAN_ADDENDUM)
    assert "LOAN ACCOUNT STATEMENT" in prompt
    assert "Never place a credit here in sales" in prompt


def test_an_empty_batch_gets_the_standing_prompt():
    assert system_prompt_for([]) == SYSTEM_PROMPT
