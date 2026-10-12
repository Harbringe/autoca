"""``POST /clients/{id}/books/mark-reviewed/``: clear the assistant marker on every entry, or only on the ones named."""

from __future__ import annotations

import pytest

from classify.treatment import ReviewBand
from core.db.session import firm_context
from ledger.models import EntryMarker, JournalEntry

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("fixture_adapters")]

V1 = "/api/v1"


def _marked_entries(api, client_record, firm):
    posted = api.post(f"{V1}/clients/{client_record.pk}/approvals/", {"band": ReviewBand.HIGH}, format="json")
    assert posted.status_code == 201
    with firm_context(firm.pk):
        ids = list(JournalEntry.objects.filter(client=client_record).values_list("pk", flat=True)[:2])
        assert len(ids) == 2
        JournalEntry.objects.filter(pk__in=ids).update(marker=EntryMarker.AI_POSTED)
    return ids


def _marked(firm, ids):
    with firm_context(firm.pk):
        return set(JournalEntry.objects.filter(pk__in=ids).exclude(marker=EntryMarker.NONE).values_list("pk", flat=True))


def test_only_the_named_entries_are_marked_as_checked(api, client_record, statement, firm):
    first, second = _marked_entries(api, client_record, firm)
    response = api.post(f"{V1}/clients/{client_record.pk}/books/mark-reviewed/", {"entries": [str(first)]}, format="json")
    assert response.status_code == 200, response.content
    assert _marked(firm, [first, second]) == {second}


def test_without_a_list_every_entry_is_marked_as_checked(api, client_record, statement, firm):
    ids = _marked_entries(api, client_record, firm)
    assert api.post(f"{V1}/clients/{client_record.pk}/books/mark-reviewed/", {}, format="json").status_code == 200
    assert _marked(firm, ids) == set()


def test_an_empty_list_is_refused_rather_than_clearing_everything(api, client_record, statement, firm):
    ids = _marked_entries(api, client_record, firm)
    response = api.post(f"{V1}/clients/{client_record.pk}/books/mark-reviewed/", {"entries": []}, format="json")
    assert response.status_code == 400
    assert _marked(firm, ids) == set(ids)
