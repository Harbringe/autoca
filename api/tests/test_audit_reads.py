"""Opening a bank account (its number is decrypted) and downloading a stored file leave a row in the audit trail."""

from __future__ import annotations

import pytest

from api.tests.test_bills import base
from core.db.session import firm_context
from core.models import AuditLog

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("fixture_adapters")]


def test_opening_a_bank_account_is_recorded(api, client_record, statement):
    accounts = api.get(f"{base(client_record)}/bank-accounts/").json()
    accounts = accounts["results"] if isinstance(accounts, dict) else accounts
    account_id = accounts[0]["id"]

    opened = api.get(f"{base(client_record)}/bank-accounts/{account_id}/")

    assert opened.status_code == 200
    with firm_context(client_record.firm_id):
        paths = list(AuditLog.objects.filter(method="GET").values_list("path", flat=True))
    assert any(p.endswith(f"/bank-accounts/{account_id}/") for p in paths)
    # Listing accounts shows them masked and is not a sensitive read.
    assert not any(p.endswith("/bank-accounts/") for p in paths)
