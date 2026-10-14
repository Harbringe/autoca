import datetime

from classify.transfers import Leg, pair_legs

D = datetime.date


def leg(id, account, day, amount, is_debit, narration):
    return Leg(id, account, D(2025, 4, day), amount, is_debit, narration)


def test_the_same_upi_reference_on_both_sides_pairs_a_withdrawal_with_its_deposit():
    legs = [
        leg("w", "A", 6, 5_000_000, True, "WDL TFR UPI/DR/800755013962/Bank"),
        leg("d", "B", 6, 5_000_000, False, "DEP TFR UPI/CR/800755013962/SHANKA"),
    ]
    [pair] = pair_legs(legs)
    assert (pair.debit, pair.credit, pair.strength) == ("w", "d", "reference")


def test_a_narration_naming_the_other_account_pairs_even_without_a_shared_reference():
    legs = [
        leg("w", "A", 9, 21_900_000, True, "CAS CHQ XFER WD CHEQUE TRANSFER TO"),
        leg("d", "B", 9, 21_900_000, False, "CHQ TRFR FROM 0062139251173 OF Mr."),
    ]
    [pair] = pair_legs(legs, own_numbers={"A": "62139251173", "B": "37563283596"})
    assert pair.strength == "named"


def test_a_lone_matching_amount_with_transfer_wording_on_both_sides_is_a_weaker_pair():
    legs = [
        leg("w", "A", 9, 21_900_000, True, "CAS CHQ XFER WD CHEQUE TRANSFER TO"),
        leg("d", "B", 9, 21_900_000, False, "CHQ TRFR FROM SOMEONE"),
    ]
    [pair] = pair_legs(legs)
    assert pair.strength == "unique"


def test_an_equal_amount_without_transfer_wording_is_not_claimed():
    legs = [
        leg("w", "A", 9, 21_900_000, True, "UPI/DR/111/Raju"),
        leg("d", "B", 9, 21_900_000, False, "UPI/CR/222/Mohan"),
    ]
    assert pair_legs(legs) == []


def test_a_small_amount_is_not_claimed_on_amount_and_date_alone():
    legs = [
        leg("w", "A", 9, 50_000, True, "WDL TFR UPI/DR/111/x"),
        leg("d", "B", 9, 50_000, False, "DEP TFR UPI/CR/222/y"),
    ]
    assert pair_legs(legs) == []


def test_two_equal_candidates_are_not_guessed_between_unless_a_reference_settles_it():
    legs = [
        leg("w", "A", 9, 5_000_000, True, "WDL TFR UPI/DR/900000000001/x"),
        leg("d1", "B", 9, 5_000_000, False, "DEP TFR UPI/CR/900000000001/y"),
        leg("d2", "B", 9, 5_000_000, False, "DEP TFR UPI/CR/900000000002/z"),
    ]
    assert [(p.debit, p.credit) for p in pair_legs(legs)] == [("w", "d1")]


def test_two_accounts_never_pair_with_themselves_nor_across_more_than_a_day():
    same = [leg("w", "A", 9, 5_000_000, True, "WDL TFR UPI/DR/900000000001/x"), leg("d", "A", 9, 5_000_000, False, "DEP TFR UPI/CR/900000000001/y")]
    far = [leg("w", "A", 9, 5_000_000, True, "WDL TFR UPI/DR/900000000001/x"), leg("d", "B", 12, 5_000_000, False, "DEP TFR UPI/CR/900000000001/y")]
    assert pair_legs(same) == [] and pair_legs(far) == []


def test_each_row_is_in_at_most_one_pair():
    legs = [
        leg("w1", "A", 9, 5_000_000, True, "WDL TFR UPI/DR/900000000001/x"),
        leg("w2", "A", 9, 5_000_000, True, "WDL TFR UPI/DR/900000000002/x"),
        leg("d1", "B", 9, 5_000_000, False, "DEP TFR UPI/CR/900000000001/y"),
        leg("d2", "B", 9, 5_000_000, False, "DEP TFR UPI/CR/900000000002/y"),
    ]
    pairs = pair_legs(legs)
    assert sorted((p.debit, p.credit) for p in pairs) == [("w1", "d1"), ("w2", "d2")]
