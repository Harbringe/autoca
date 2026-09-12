"""Bank account identifiers are encrypted at rest, and still findable.

RLS is the wall; this is the lock behind it. A row is already inside the tenant
boundary, so this is not what stops a cross-firm read -- it is what limits the
damage of a database dump, a misconfigured backup, or a bug in a future query
that forgets its firm filter.
"""

from __future__ import annotations

import datetime

import pytest
from django.db import connection

from banking.models import BankAccount
from banking.tests.support import ingest_fixture_statement
from core.db.session import firm_context
from core.provisioning import create_client, create_firm
from integrations.kms.base import EnvelopeError

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("fixture_adapters")]

ACCOUNT = "911010000004321"


@pytest.fixture
def client():
    firm = create_firm("Privacy Test Firm")
    return create_client(firm, "Ramesh Deshmukh", datetime.date(2025, 4, 1))


def test_the_account_number_is_not_stored_in_the_clear(client):
    """The assertion that matters: read the raw column, find no account number."""
    with firm_context(client.firm_id):
        ingest_fixture_statement(client)

        with connection.cursor() as cursor:
            cursor.execute("SELECT account_number_enc, account_holder_enc FROM banking_bank_account")
            stored = cursor.fetchall()

    assert stored
    for number_blob, holder_blob in stored:
        assert ACCOUNT.encode() not in bytes(number_blob)
        assert b"RAMESH" not in bytes(holder_blob).upper()


def test_the_number_reads_back_intact(client):
    with firm_context(client.firm_id):
        account = ingest_fixture_statement(client).bank_account

        assert account.account_number == ACCOUNT
        assert account.account_holder == "RAMESH GOPAL DESHMUKH"


def test_the_last_four_are_kept_for_display_without_decrypting(client):
    """"Axis ••••4321" on a list screen should not cost a KMS call per row."""
    with firm_context(client.firm_id):
        account = ingest_fixture_statement(client).bank_account

        assert account.account_last4 == "4321"
        assert str(account) == "Axis Bank A/c 911010000004321"


def test_an_account_is_found_again_by_its_number(client):
    """The blind index earning its place: a second statement finds the same row."""
    with firm_context(client.firm_id):
        first = ingest_fixture_statement(client, filename="one.pdf")
        again = ingest_fixture_statement(client, data=b"%PDF second file", filename="two.pdf")

        assert again.bank_account.pk == first.bank_account.pk
        assert BankAccount.objects.count() == 1


def test_a_ciphertext_cannot_be_read_under_another_firms_context(client):
    """A second, cryptographic boundary beneath the RLS one.

    Even if a bug handed firm B the bytes belonging to firm A, the firm id is
    bound into the ciphertext as authenticated data and the decryption fails.
    """
    other = create_firm("Other Firm")

    with firm_context(client.firm_id):
        account = ingest_fixture_statement(client).bank_account
        blob = bytes(account.account_number_enc)

    smuggled = BankAccount(firm_id=other.pk, account_number_enc=blob)
    with firm_context(other.pk), pytest.raises(EnvelopeError):
        assert smuggled.account_number
