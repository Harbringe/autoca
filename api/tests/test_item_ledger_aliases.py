"""A line named by one of an item's other names is booked to that item's ledgers, not to a new item."""

from __future__ import annotations

import pytest

from core.db.session import firm_context
from ledger import item_ledgers
from ledger.models import StockItem

pytestmark = pytest.mark.django_db


def test_an_alias_finds_the_item_instead_of_making_a_new_one(firm, client_record):
    with firm_context(firm.pk):
        item = StockItem.objects.create(firm=firm, client=client_record, name="Mustard Oil 1L", unit="Nos", aliases=["MO 1 ltr"])
        assert item_ledgers.item_for(client_record, "mo 1 LTR").pk == item.pk
        assert StockItem.objects.filter(client=client_record).count() == 1
        assert item_ledgers.item_for(client_record, "Totally Different Thing").pk != item.pk
