"""A re-match runs after a person's own action; whatever goes wrong in it must never fail that action. No database needed."""

import contextlib
from types import SimpleNamespace

from django.db import DatabaseError

from ledger import billing, matching


def _no_transaction(monkeypatch):
    monkeypatch.setattr(matching.transaction, "atomic", lambda *a, **k: contextlib.nullcontext())


def test_it_returns_how_many_pairs_were_settled(monkeypatch):
    _no_transaction(monkeypatch)
    monkeypatch.setattr(matching, "match_client", lambda client: 3)
    assert matching.rematch(SimpleNamespace(pk=1)) == 3


def test_a_database_or_billing_error_is_swallowed(monkeypatch):
    _no_transaction(monkeypatch)
    for error in (DatabaseError("locked"), billing.BillingError("no")):
        def boom(client, error=error):
            raise error

        monkeypatch.setattr(matching, "match_client", boom)
        assert matching.rematch(SimpleNamespace(pk=1)) == 0
