"""A row's identity across overlapping statements, and a repeat within one statement. No database."""

from __future__ import annotations

import datetime

from banking.models import StatementTransaction

FIELDS = {
    "account_hash": "acct",
    "value_date": datetime.date(2025, 7, 13),
    "narration": "FT-12345-GREENSTAR  FERTILIZERS",
    "debit_paise": 25_000_000,
    "credit_paise": 0,
    "balance_paise": -1_991_420_664,
}


def test_the_first_occurrence_keeps_the_hash_it_always_had():
    """Rows stored before a repeat was numbered must still match: only a repeat's hash is new."""
    assert StatementTransaction.compute_dedupe_hash(**FIELDS) == StatementTransaction.compute_dedupe_hash(**FIELDS, occurrence=0)


def test_a_repeat_has_its_own_hash_and_each_number_its_own():
    first = StatementTransaction.compute_dedupe_hash(**FIELDS)
    second = StatementTransaction.compute_dedupe_hash(**FIELDS, occurrence=1)
    third = StatementTransaction.compute_dedupe_hash(**FIELDS, occurrence=2)
    assert len({first, second, third}) == 3


def test_spacing_and_case_in_the_narration_do_not_matter():
    spaced = {**FIELDS, "narration": "ft-12345-greenstar fertilizers"}
    assert StatementTransaction.compute_dedupe_hash(**FIELDS) == StatementTransaction.compute_dedupe_hash(**spaced)
