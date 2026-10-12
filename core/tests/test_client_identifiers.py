"""The registration formats a client's profile accepts, and the masking of a number shown to someone who may not edit."""

from __future__ import annotations

import pytest

from api.serializers.core import _mask
from core.identifiers import is_valid_cin, is_valid_tan, is_valid_udyam


@pytest.mark.parametrize("value", ["ABCD12345E", "mumb01234a"])
def test_good_tans(value):
    assert is_valid_tan(value)


@pytest.mark.parametrize("value", ["", "ABCDE1234F", "ABC123456D", "ABCD1234E"])
def test_bad_tans(value):
    assert not is_valid_tan(value)


@pytest.mark.parametrize("value", ["U12345MH2020PTC123456", "L99999DL1990PLC000001", "AAB-1234", "aab-1234"])
def test_good_cins_and_llpins(value):
    assert is_valid_cin(value)


@pytest.mark.parametrize("value", ["", "X12345MH2020PTC123456", "U12345MH2020PTC12345", "AAB1234", "AB-12345"])
def test_bad_cins_and_llpins(value):
    assert not is_valid_cin(value)


@pytest.mark.parametrize("value", ["UDYAM-MH-12-1234567", "udyam-dl-01-0000001"])
def test_good_udyam(value):
    assert is_valid_udyam(value)


@pytest.mark.parametrize("value", ["", "UDYAM-MH-1-1234567", "UDYAM-MH-12-123456", "MH-12-1234567"])
def test_bad_udyam(value):
    assert not is_valid_udyam(value)


def test_masking_keeps_the_ends_and_hides_the_middle():
    assert _mask("ABCDE1234F") == "AB*******F"
    assert _mask("") == ""
    assert _mask("AB") == "AB"

