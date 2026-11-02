"""Does the TDS on the bills agree with the TDS in the books, and is what was deducted deposited?

Per quarter of a financial year: what the bills say was deducted, what was credited to ``TDS Payable`` (from bills, and from anything
else such as salary or a journal), what was debited to it, and how much of that debit has a challan recorded behind it. The year's
balance still owed is what the ledger carries. Salary TDS shares the ledger, so credits that do not come from a bill are shown on
their own line instead of being counted as a difference. It writes nothing.
"""

from __future__ import annotations

from ledger import tds
from ledger.models import Bill, Direction, JournalLine, TdsChallan
from ledger.tds_return import _deposit_amount

QUARTERS = (1, 2, 3, 4)


def _fy_of(day) -> int:
    return day.year if day.month >= 4 else day.year - 1


def build(client, fy: int) -> dict:
    ledger = tds.payable_ledger(client)
    rows = {q: {"quarter": q, "bills_paise": 0, "credited_from_bills_paise": 0, "credited_other_paise": 0, "deposited_paise": 0, "with_challan_paise": 0} for q in QUARTERS}
    unsectioned = 0

    for bill in Bill.objects.filter(firm_id=client.firm_id, client=client, financial_year=fy, tds_paise__gt=0):
        rows[tds.quarter_of(bill.bill_date.month)]["bills_paise"] += bill.tds_paise

    if ledger is not None:
        lines = JournalLine.objects.filter(firm_id=client.firm_id, ledger_account=ledger).select_related("entry")
        for line in lines:
            entry = line.entry
            if _fy_of(entry.entry_date) != fy:
                continue
            row = rows[tds.quarter_of(entry.entry_date.month)]
            if line.direction == Direction.CREDIT:
                if getattr(entry, "bill", None) is not None:
                    row["credited_from_bills_paise"] += line.amount_paise
                    if not line.tds_section:
                        unsectioned += line.amount_paise
                else:
                    row["credited_other_paise"] += line.amount_paise
            else:
                row["deposited_paise"] += line.amount_paise
        # A challan is counted in the quarter of the bank entry it explains, the same as the deposit it covers.
        for challan in TdsChallan.objects.filter(firm_id=client.firm_id, client=client).select_related("entry"):
            if _fy_of(challan.entry.entry_date) == fy:
                rows[tds.quarter_of(challan.entry.entry_date.month)]["with_challan_paise"] += _deposit_amount(challan, ledger)

    quarters = []
    for q in QUARTERS:
        r = rows[q]
        r["bills_difference_paise"] = r["credited_from_bills_paise"] - r["bills_paise"]
        r["without_challan_paise"] = max(r["deposited_paise"] - r["with_challan_paise"], 0)
        r["deducted_paise"] = r["credited_from_bills_paise"] + r["credited_other_paise"]
        quarters.append(r)
    deducted = sum(r["deducted_paise"] for r in quarters)
    deposited = sum(r["deposited_paise"] for r in quarters)
    return {
        "fy": fy,
        "quarters": quarters,
        "deducted_paise": deducted,
        "deposited_paise": deposited,
        "still_to_deposit_paise": deducted - deposited,
        "without_section_paise": unsectioned,
        "agrees": all(r["bills_difference_paise"] == 0 and r["without_challan_paise"] == 0 for r in quarters) and not unsectioned,
        "has_ledger": ledger is not None,
    }
