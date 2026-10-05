"""What the settlement endpoints share: building the question for the screen, and reading a person's answer.

Not a viewset. The endpoints themselves sit beside the things they belong to (a classification, a posted entry, the batch
approval), and all of them need the same two things from here.
"""

from __future__ import annotations

from rest_framework import serializers

from api.serializers.settlement import OpenBillSerializer
from core.money import format_inr
from ledger import billing
from ledger import settlement as settling
from ledger.models import Bill
from ledger.settlement import Settlement


def build_context(party, direction: str, amount_paise: int, *, already: int = 0) -> dict:
    """The party's open bills for this payment, and what the matcher would settle. A suggestion, not a decision."""
    bills, proposal = settling.propose_for(party, direction, amount_paise)
    return {
        "party": {"id": party.pk, "name": party.canonical_name},
        "amount_paise": amount_paise,
        "amount_display": format_inr(amount_paise),
        "direction": direction,
        "bills": OpenBillSerializer(bills, many=True).data,
        "proposal": {
            "allocations": [
                {"bill": bill_id, "amount_paise": paise, "amount_display": format_inr(paise)}
                for bill_id, paise in proposal.allocations
            ],
            "remainder_paise": proposal.remainder_paise,
            "remainder_display": format_inr(proposal.remainder_paise),
            "basis": proposal.basis,
        },
        "already_allocated_paise": already,
    }


def settlement_from(client, firm_id, data) -> Settlement:
    """A person's decision, with its bills looked up in this client's books. Another client's bill is not found."""
    wanted = {allocation["bill"] for allocation in data["allocations"]}
    found = {bill.pk: bill for bill in Bill.objects.filter(firm_id=firm_id, client=client, pk__in=wanted)}
    missing = wanted - set(found)
    if missing:
        raise serializers.ValidationError(
            {"allocations": f"Not bills of this client: {', '.join(sorted(str(pk) for pk in missing))}."}
        )
    return Settlement(
        allocations=tuple((found[allocation["bill"]], allocation["amount_paise"]) for allocation in data["allocations"]),
        remainder=data.get("remainder"),
    )


def party_line_of(entry):
    """The line of a posted entry that sits on a party's own account, and how much of it is not yet allocated."""
    line = next(
        (
            candidate
            for candidate in entry.lines.select_related("ledger_account__party_record", "party")
            if candidate.ledger_account.is_party_account and candidate.party_id
        ),
        None,
    )
    if line is None:
        raise billing.BillingError("This entry is not on a party's account, so there is nothing to settle.")
    return line, billing.line_unallocated(line)
