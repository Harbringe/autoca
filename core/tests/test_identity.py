"""One definition of "the same invoice", shared by the books and by GST.

The books and ``gst/`` reconcile only if they recognise an invoice identically. These tests pin that the key is built
in one place, that it is the very key GST decisions were already stored under, and that an unregistered supplier is
handled without ever colliding with a real GSTIN.
"""

from __future__ import annotations

import uuid

import pytest

from core import identity
from core.crypto import blind_index


def test_invoice_numbers_that_differ_only_in_punctuation_case_or_padding_are_one_invoice():
    assert identity.normalise_invoice_no("INV/0042") == identity.normalise_invoice_no("inv-42")
    assert identity.normalise_invoice_no("INV 042") == identity.normalise_invoice_no("INV42")
    assert identity.normalise_invoice_no("0042") == "42"


def test_different_invoice_numbers_stay_different():
    assert identity.normalise_invoice_no("A1") != identity.normalise_invoice_no("A10")


def test_a_gstin_is_compared_in_upper_case_without_surrounding_space():
    assert identity.normalise_gstin("  27aaacr5055k1z7 ") == "27AAACR5055K1Z7"


def test_gst_uses_the_shared_functions_not_its_own_copies():
    from gst import matching

    assert matching.normalise_invoice_no is identity.normalise_invoice_no
    assert matching.normalise_gstin is identity.normalise_gstin


def test_the_key_is_exactly_the_one_gst_decisions_were_stored_under():
    """Any key already stored must keep matching, so the formula is part of the contract."""
    firm = uuid.uuid4()
    legacy = blind_index("27AAACR5055K1Z7|INV42", firm, "gst.match")

    assert identity.invoice_key(firm, "27aaacr5055k1z7", "INV/0042") == legacy


def test_gst_services_delegate_to_the_shared_key():
    from gst import services

    firm = uuid.uuid4()
    assert services.match_key(firm, "27AAACR5055K1Z7", "INV-42") == identity.invoice_key(
        firm, "27AAACR5055K1Z7", "INV-42"
    )


def test_the_same_invoice_in_two_firms_has_two_keys():
    """A shared key across firms would be a cross-tenant link."""
    assert identity.invoice_key(uuid.uuid4(), "27AAACR5055K1Z7", "INV42") != identity.invoice_key(
        uuid.uuid4(), "27AAACR5055K1Z7", "INV42"
    )


@pytest.mark.parametrize("gstin", ["27AAACR5055K1Z7", " 27aaacr5055k1z7"])
def test_a_registered_supplier_is_identified_by_gstin(gstin):
    assert identity.supplier_identity(gstin, party_id=uuid.uuid4()) == "27AAACR5055K1Z7"


def test_an_unregistered_supplier_is_identified_by_the_party_and_never_equals_a_gstin():
    party = uuid.uuid4()
    who = identity.supplier_identity("", party_id=party)

    assert who == f"PARTY:{party}"
    assert not identity.normalise_gstin(who).isalnum()  # the colon and hyphens keep it from being a GSTIN


def test_no_supplier_at_all_gives_an_empty_identity():
    assert identity.supplier_identity("", party_id=None) == ""
