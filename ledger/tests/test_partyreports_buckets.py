"""Where a bill falls in the ageing report, with no database."""

from __future__ import annotations

import pytest

from ledger.partyreports import BUCKET_LABELS, bucket_for


@pytest.mark.parametrize(
    ("days", "bucket"),
    [(0, "0-30"), (30, "0-30"), (31, "31-60"), (60, "31-60"), (61, "61-90"), (90, "61-90"), (91, "Over 90"), (900, "Over 90")],
)
def test_ageing_buckets_are_cut_at_30_60_and_90_days(days, bucket):
    assert bucket_for(days) == bucket


def test_the_buckets_are_in_reading_order():
    assert BUCKET_LABELS == ("0-30", "31-60", "61-90", "Over 90")
