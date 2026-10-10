"""Names are written one way, and two spellings of one business are told apart from two businesses. No database needed."""

import pytest

from core.names import normalise, same_business


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("SHRI NARAYAN TRADING CO.", "Shri Narayan Trading Co."),
        ("gajraj trading company", "Gajraj Trading Company"),
        ("S.B.H DRYFRUITS", "S.B.H Dryfruits"),
        ("  Shri   Padmavati  Trading Co   Wadepuri ", "Shri Padmavati Trading Co Wadepuri"),
        ("ABC ENTERPRISES LLP", "Abc Enterprises LLP"),
        ("rajesh AND sons", "Rajesh and Sons"),
        ("M/S RAVI TRADERS", "M/S Ravi Traders"),
        ("McDonald Traders", "McDonald Traders"),
        ("D'SOUZA & CO", "D'Souza & Co"),
        ("RAM-LAXMAN STORES 24X7", "Ram-Laxman Stores 24X7"),
        ("", ""),
    ],
)
def test_one_way_of_writing_a_name(raw, expected):
    assert normalise(raw) == expected


def test_writing_a_name_twice_changes_nothing():
    once = normalise("SHRI NARAYAN TRADING CO. LOHA")
    assert normalise(once) == once


@pytest.mark.parametrize(
    "a, b",
    [
        ("SHRI NARAYAN TRADING CO.", "Shri Narayan Trading Company Loha"),
        ("Gajraj Trading Company", "GAJRAJ TRADING CO"),
        ("Ravi Traders Pvt Ltd", "Ravi Traders Private Limited"),
    ],
)
def test_two_spellings_of_one_business_match(a, b):
    assert same_business(a, b)


@pytest.mark.parametrize(
    "a, b",
    [
        ("Shri Narayan Trading Co", "Shri Padmavati Trading Co Wadepuri"),
        ("Shri Narayan Traders", "Shri Narayan Trading Company Loha"),
        ("Trading Co", "Shri Narayan Trading Company"),
        ("", "Shri Narayan Trading Company"),
    ],
)
def test_different_businesses_do_not(a, b):
    assert not same_business(a, b)
