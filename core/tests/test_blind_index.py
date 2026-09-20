"""The blind index: matching on an encrypted identifier without decrypting it.

Encrypting an account number protects it and destroys what the column was for.
AES-GCM is randomised, so the same account encrypts differently every time and
no index, join or uniqueness constraint can touch it. These tests pin the
properties that make the companion hash column safe to rely on.
"""

from __future__ import annotations

import uuid

import pytest
from django.core.exceptions import ImproperlyConfigured

from core.crypto import blind_index

FIRM_A = uuid.UUID("11111111-1111-1111-1111-111111111111")
FIRM_B = uuid.UUID("22222222-2222-2222-2222-222222222222")
ACCOUNT = "123456789012345"


def test_the_same_value_indexes_the_same_way():
    """Without this, lookup does not work at all."""
    assert blind_index(ACCOUNT, FIRM_A) == blind_index(ACCOUNT, FIRM_A)


def test_different_values_index_differently():
    assert blind_index(ACCOUNT, FIRM_A) != blind_index("318010100007276", FIRM_A)


def test_two_firms_banking_with_the_same_account_do_not_collide():
    """Equal fingerprints across the tenant boundary would leak a correlation.

    That two firms hold the same account number is exactly the kind of fact RLS
    otherwise prevents either of them from learning.
    """
    assert blind_index(ACCOUNT, FIRM_A) != blind_index(ACCOUNT, FIRM_B)


def test_purposes_are_separated():
    """An account-number index and a GSTIN index of the same digits must differ."""
    assert blind_index(ACCOUNT, FIRM_A, "banking.account") != blind_index(
        ACCOUNT, FIRM_A, "gst.gstin"
    )


def test_indexing_is_insensitive_to_the_formatting_of_the_value():
    assert blind_index(" 27aaapa1234c1zv ", FIRM_A) == blind_index("27AAAPA1234C1ZV", FIRM_A)


def test_the_index_is_not_the_plaintext():
    digest = blind_index(ACCOUNT, FIRM_A)
    assert ACCOUNT not in digest
    assert len(digest) == 64


def test_a_missing_key_fails_loudly_rather_than_producing_a_weak_index(settings):
    """A default key would silently make every index forgeable."""
    settings.BLIND_INDEX_KEY = ""

    with pytest.raises(ImproperlyConfigured, match="BLIND_INDEX_KEY"):
        blind_index(ACCOUNT, FIRM_A)
