"""A firm's own Tally voucher type kept as its own: posts as its parent, numbers in its own series."""

from __future__ import annotations

import pytest

from core.db.session import firm_context
from ledger.approval import allocate_voucher_number
from ledger.models import CustomVoucherType, JournalEntry
from ledger.tally_voucher_import import confirm_vouchers, normalise_type_map, stage_vouchers
from ledger.tests.tally_voucher_xml import line, voucher, vouchers_xml
from ledger.tests.test_tally_voucher_import import (  # noqa: F401  (fixtures and helpers)
    chart,
    client,
    firm,
    member,
    senior,
)

pytestmark = pytest.mark.django_db


def gst_sale(guid, number, date="20250401"):
    return voucher(
        guid=guid, vtype="GST SALE", number=number, date=date, party="Acme Traders",
        lines=[line("Acme Traders", 1180.0, party=True), line("Sales", -1000.0), line("Output CGST", -90.0), line("Output SGST", -90.0)],
    )


def import_own(client, senior, vouchers):
    run, _ = stage_vouchers(
        client, senior, senior.user, data=vouchers_xml(vouchers), filename="v.xml", voucher_types={"GST SALE": "own:sales"}
    )
    return confirm_vouchers(run, senior, senior.user)


def test_an_own_type_posts_as_its_parent_and_numbers_in_its_own_series(firm, client, senior, chart):
    done = import_own(client, senior, [gst_sale("g1", "11"), gst_sale("g2", "12", "20250402")])
    assert done.result["posted"] == 2
    entries = JournalEntry.objects.filter(client=client).order_by("entry_no")
    assert [(e.voucher_type, e.type_name, e.entry_no) for e in entries] == [("Sales", "GST SALE", 1), ("Sales", "GST SALE", 2)]
    assert allocate_voucher_number(client, 2025, "Sales") == 1, "the standard Sales series is untouched"


def test_the_own_type_is_created_once(firm, client, senior, chart):
    import_own(client, senior, [gst_sale("g1", "11"), gst_sale("g2", "12", "20250402")])
    types = CustomVoucherType.objects.filter(client=client)
    assert [(t.name, t.parent) for t in types] == [("GST SALE", "Sales")]


def test_the_stage_preview_names_nothing_unknown_for_an_own_type(firm, client, senior, chart):
    run, _ = stage_vouchers(
        client, senior, senior.user, data=vouchers_xml([gst_sale("g1", "11")]), filename="v.xml", voucher_types={"GST SALE": "own:sales"}
    )
    assert run.counts["unknown_types"] == {} and run.counts["will_post"] == 1


def test_a_bank_voucher_type_cannot_be_kept_as_its_own():
    assert normalise_type_map({"Bank Payment": "own:payment", "GST SALE": "own:sales", "Odd": "own:nonsense"}) == {"gst sale": "own:sales"}


def test_an_own_type_is_not_made_until_the_import_posts(firm, client, senior, chart):
    stage_vouchers(
        client, senior, senior.user, data=vouchers_xml([gst_sale("g1", "11")]), filename="v.xml", voucher_types={"GST SALE": "own:sales"}
    )
    with firm_context(firm.pk):
        assert not CustomVoucherType.objects.filter(client=client).exists()
