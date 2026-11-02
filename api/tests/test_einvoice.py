"""The e-invoice and e-way bill drafts: filled from the books as far as they go, with what is still needed listed."""

from __future__ import annotations

import pytest

from api.tests.test_bills import base, make_ledger, make_party, post_bill, valid_gstin

pytestmark = [pytest.mark.django_db, pytest.mark.usefixtures("fixture_adapters")]

BUYER_GSTIN = valid_gstin("27AAAAA0000A1Z")


def invoice(api, client, *, gstin=BUYER_GSTIN, taxable=10_000_000, cgst=900_000, sgst=900_000, igst=0, kind="SALES", ref="S-1"):
    customer = make_party(api, client, "Mehta Stores", role="CUSTOMER", gstin=gstin)
    sales = make_ledger(api, client, "Sales", "SALES")
    body = {
        "kind": kind, "party": customer["id"], "reference": ref, "bill_date": "2025-10-05",
        "heads": [{"ledger": sales["id"], "amount_paise": taxable}], "cgst_paise": cgst, "sgst_paise": sgst, "igst_paise": igst,
    }
    made = post_bill(api, client, body)
    assert made.status_code == 201, made.content
    return made.json()


def draft(api, client, bill, **details):
    done = api.post(f"{base(client)}/bills/{bill['id']}/e-documents/", details, format="json")
    assert done.status_code == 200, done.content
    return done.json()


def test_the_draft_carries_the_invoice_value_tax_and_buyer_and_lists_what_is_missing(api, client_record):
    bill = invoice(api, client_record)
    body = draft(api, client_record, bill)
    ei = body["e_invoice"]["json"]
    assert body["eligible"] is True and "5 crore" in body["note"]
    assert ei["DocDtls"] == {"Typ": "INV", "No": "S-1", "Dt": "05/10/2025"}
    assert ei["BuyerDtls"]["Gstin"] == BUYER_GSTIN and ei["BuyerDtls"]["Stcd"] == "27" and ei["BuyerDtls"]["LglNm"] == "Mehta Stores"
    assert ei["ValDtls"] == {"AssVal": 100000.0, "CgstVal": 9000.0, "SgstVal": 9000.0, "IgstVal": 0.0, "CesVal": 0.0, "RndOffAmt": 0.0, "TotInvVal": 118000.0}
    (item,) = ei["ItemList"]
    assert item["AssAmt"] == 100000.0 and item["GstRt"] == 18.0 and item["CgstAmt"] == 9000.0 and item["TotItemVal"] == 118000.0
    missing = " ".join(body["e_invoice"]["missing"])
    assert "pincode" in missing and "HSN" in missing and "GSTIN" in missing


def test_details_supplied_are_used_and_clear_what_was_missing(api, client_record):
    bill = invoice(api, client_record)
    body = draft(api, client_record, bill, seller_pin="411001", seller_address="12 MG Road", seller_place="Pune", buyer_pin="400001", buyer_address="5 Fort", buyer_place="Mumbai")
    ei = body["e_invoice"]
    assert ei["json"]["BuyerDtls"]["Pin"] == "400001" and ei["json"]["SellerDtls"]["Addr1"] == "12 MG Road"
    assert not any("pincode" in m or "address" in m for m in ei["missing"])


def test_the_eway_bill_is_required_over_fifty_thousand_and_takes_the_transport_details(api, client_record):
    bill = invoice(api, client_record)
    first = draft(api, client_record, bill)["eway_bill"]
    assert first["required"] is True and any("distance" in m for m in first["missing"])
    done = draft(api, client_record, bill, distance_km=150, vehicle_no="mh 12 ab 1234", mode="ROAD", seller_pin="411001", buyer_pin="400001")["eway_bill"]
    entry = done["json"]["billLists"][0]
    assert entry["vehicleNo"] == "MH12AB1234" and entry["transDistance"] == "150" and entry["transMode"] == 1
    assert entry["totInvValue"] == 118000.0 and entry["toGstin"] == BUYER_GSTIN and entry["toStateCode"] == 27
    assert not any("distance" in m or "vehicle" in m for m in done["missing"])


def test_a_small_invoice_does_not_need_an_eway_bill_and_a_buyer_without_a_gstin_is_flagged(api, client_record):
    small = invoice(api, client_record, taxable=2_000_000, cgst=0, sgst=0, igst=0, gstin="", ref="S-2")
    body = draft(api, client_record, small)
    assert body["eway_bill"]["required"] is False
    assert any("has no GSTIN" in m for m in body["e_invoice"]["missing"])


def test_a_purchase_is_not_eligible_and_bad_details_are_refused(api, client_record):
    from api.tests.test_bills import voucher

    vendor = make_party(api, client_record)
    purchases = make_ledger(api, client_record)
    made = post_bill(api, client_record, voucher(vendor, purchases)).json()
    body = draft(api, client_record, made)
    assert body["eligible"] is False and body["e_invoice"] is None
    sale = invoice(api, client_record, ref="S-3")
    assert api.post(f"{base(client_record)}/bills/{sale['id']}/e-documents/", {"buyer_pin": "012345"}, format="json").status_code == 400
