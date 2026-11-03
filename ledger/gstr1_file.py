"""The GSTR-1 working in the shape of the GST portal's offline-tool JSON, for a person to check and upload.

Built from ``ledger.gstr1.build``, so it is exactly the figures on the working. What the books cannot say is left empty and listed under
``missing``: the place of supply of an unregistered buyer, the taxpayer's aggregate turnover (``gt``, ``cur_gt``), and the split of nil-rated,
exempt and non-GST supplies by who they were made to. The portal's offline tool validates the file; run it through that before filing.
"""

from __future__ import annotations

import datetime

from gst.models import GstRegistration
from ledger import gstr1

RATE_KEYS = ("igst", "cgst", "sgst", "cess")


def _rs(paise: int) -> float:
    return round(abs(paise) / 100, 2)


def _dmy(iso: str) -> str:
    return datetime.date.fromisoformat(iso).strftime("%d-%m-%Y")


def _item(num: int, rate: str, taxable: int, row: dict) -> dict:
    return {
        "num": num,
        "itm_det": {
            "rt": float(rate), "txval": _rs(taxable), "iamt": _rs(row["igst_paise"]), "camt": _rs(row["cgst_paise"]),
            "samt": _rs(row["sgst_paise"]), "csamt": _rs(row["cess_paise"]),
        },
    }


def build(client, month: str) -> dict:
    work = gstr1.build(client, month)
    year, mon = (int(p) for p in month.split("-"))
    reg = GstRegistration.objects.filter(firm_id=client.firm_id, client=client, is_active=True).first()
    seller = reg.gstin if reg else ""
    seller_state = seller[:2]
    missing: list[str] = []
    if not seller:
        missing.append("The client's GSTIN: no active GST registration is recorded.")
    missing.append("Aggregate turnover (gt) and the current year's turnover (cur_gt): the books cannot say what the taxpayer's was.")

    b2b: dict[str, list] = {}
    for r in work["b2b"]["rows"]:
        b2b.setdefault(r["gstin"], []).append(
            {
                "inum": r["number"], "idt": _dmy(r["date"]), "val": _rs(r["value_paise"]), "pos": r["gstin"][:2], "rchrg": "N", "inv_typ": "R",
                "itms": [_item(1, r["rate"], r["taxable_paise"], r)],
            }
        )

    b2cl: list[dict] = []
    if work["b2cl"]["rows"]:
        missing.append("The place of supply of each B2C large invoice (pos): the books do not record it.")
    for r in work["b2cl"]["rows"]:
        b2cl.append({"pos": "", "inv": [{"inum": r["number"], "idt": _dmy(r["date"]), "val": _rs(r["value_paise"]), "itms": [_item(1, r["rate"], r["taxable_paise"], r)]}]})

    b2cs: list[dict] = []
    for r in work["b2cs"]["rows"]:
        inter = r["supply"] == "Inter-state"
        if inter:
            missing.append(f"The place of supply of the inter-state B2C sales at {r['rate']}% (pos): the books do not record it.")
        b2cs.append(
            {
                "sply_ty": "INTER" if inter else "INTRA", "rt": float(r["rate"]), "typ": "OE", "pos": "" if inter else seller_state,
                "txval": _rs(r["taxable_paise"]), "iamt": _rs(r["igst_paise"]), "camt": _rs(r["cgst_paise"]), "samt": _rs(r["sgst_paise"]), "csamt": _rs(r["cess_paise"]),
            }
        )

    cdnr: dict[str, list] = {}
    for r in work["credit_notes_registered"]["rows"]:
        cdnr.setdefault(r["gstin"], []).append(
            {
                "ntty": "C", "nt_num": r["number"], "nt_dt": _dmy(r["date"]), "val": _rs(r["value_paise"]), "pos": r["gstin"][:2], "rchrg": "N", "inv_typ": "R",
                "itms": [_item(1, r["rate"], r["taxable_paise"], r)],
            }
        )
    cdnur = []
    if work["credit_notes_unregistered"]["rows"]:
        missing.append("The place of supply of credit notes to unregistered buyers (pos).")
    for r in work["credit_notes_unregistered"]["rows"]:
        cdnur.append({"ntty": "C", "nt_num": r["number"], "nt_dt": _dmy(r["date"]), "val": _rs(r["value_paise"]), "typ": "B2CS", "itms": [_item(1, r["rate"], r["taxable_paise"], r)]})

    hsn = [
        {
            "num": i, "hsn_sc": h["hsn"] if h["hsn"] != "—" else "", "desc": "", "uqc": (h["unit"] or "OTH").upper()[:3], "qty": h["quantity"],
            "val": _rs(h["taxable_paise"] + h["igst_paise"] + h["cgst_paise"] + h["sgst_paise"] + h["cess_paise"]), "txval": _rs(h["taxable_paise"]),
            "iamt": _rs(h["igst_paise"]), "camt": _rs(h["cgst_paise"]), "samt": _rs(h["sgst_paise"]), "csamt": _rs(h["cess_paise"]),
        }
        for i, h in enumerate(work["hsn"], 1)
    ]
    if work["hsn_bills_without_items"]:
        missing.append(f"{work['hsn_bills_without_items']} invoice(s) have no item lines, so the HSN table leaves them out.")
    if any(not h["hsn_sc"] for h in hsn):
        missing.append("An HSN code on every HSN line.")

    docs = []
    for d in work["documents"]:
        docs.append({"doc_num": 1 if "Invoices" in d["label"] else 5, "docs": [{"num": 1, "from": d["from"], "to": d["to"], "totnum": d["count"], "cancel": 0, "net_issue": d["count"]}]})

    ex = work["exempt_nil_non_gst"]
    if ex["zero_rated_paise"] or ex["exempt_paise"] or ex["non_gst_paise"] or ex["untaxed_sales_paise"]:
        missing.append("Whether nil-rated, exempt and non-GST supplies went to registered or unregistered buyers, inside or outside the state (table 8).")

    payload = {
        "gstin": seller, "fp": f"{mon:02d}{year}", "gt": 0, "cur_gt": 0, "version": "GST3.1.6", "hash": "hash",
        "b2b": [{"ctin": c, "inv": inv} for c, inv in b2b.items()], "b2cl": b2cl, "b2cs": b2cs,
        "cdnr": [{"ctin": c, "nt": nt} for c, nt in cdnr.items()], "cdnur": cdnur,
        "hsn": {"data": hsn}, "doc_issue": {"doc_det": docs},
    }
    return {"json": {k: v for k, v in payload.items() if v not in ([], {"data": []}, {"doc_det": []})}, "missing": list(dict.fromkeys(missing))}
