import datetime

from ledger import tds_return


def test_return_due_dates():
    assert tds_return.return_due(2025, 1) == datetime.date(2025, 7, 31)
    assert tds_return.return_due(2025, 3) == datetime.date(2026, 1, 31)
    assert tds_return.return_due(2025, 4) == datetime.date(2026, 5, 31)


def test_interest_months_count_part_of_a_month():
    assert tds_return.months_late(datetime.date(2025, 5, 10), datetime.date(2025, 6, 10)) == 1
    assert tds_return.months_late(datetime.date(2025, 5, 10), datetime.date(2025, 6, 11)) == 2
    assert tds_return.months_late(datetime.date(2025, 12, 20), datetime.date(2026, 1, 5)) == 1


def test_pan_is_read_from_the_gstin():
    class Party:
        gstin = "27ABCDE1234F1Z5"

    assert tds_return.pan_of(Party()) == "ABCDE1234F"
    assert tds_return.pan_of(None) == ""
