"""A bank payment file built from what the client owes, and where each party is paid."""

from __future__ import annotations

import csv
import datetime
import io
import re
import uuid

from django.http import HttpResponse
from drf_spectacular.utils import extend_schema
from rest_framework import viewsets
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response

from api.permissions import HasFirmPermission
from api.serializers.payment_files import PayableSerializer, PaymentFileSerializer
from api.views.base import ClientScopedMixin
from banking.models import BankAccount
from classify.models import Party
from ledger import partyreports
from ledger.audit import record_master_change
from ledger.models import Bill

#: Per-transaction limits: RTGS is for large payments only; IMPS has a ceiling.
RTGS_MINIMUM_PAISE = 2_00_000_00
IMPS_MAXIMUM_PAISE = 5_00_000_00
MAX_FILE_TOTAL = 1_000_00_00_000  # a sanity ceiling on one file, in paise (Rs 100 crore)
_FORMULA = re.compile(r"^[=+\-@\t\r]+")


def _safe(text: str) -> str:
    """Text for a spreadsheet cell with nothing a program would run: a leading = + - @ is dropped."""
    return _FORMULA.sub("", (text or "").strip())


@extend_schema(tags=["payment-files"])
class PaymentFileViewSet(ClientScopedMixin, viewsets.GenericViewSet):
    """What is owed, and a file to pay it from. Prepares the file only: nothing is booked, and the money moves when the bank is given the file."""

    permission_classes = [HasFirmPermission]
    required_permission = {"GET": "journal.view", "POST": "journal.approve"}
    queryset = Bill.objects.all()
    serializer_class = PaymentFileSerializer

    @extend_schema(summary="Parties the client owes, and whether each can be paid", responses=PayableSerializer(many=True))
    def list(self, request, client_id=None):
        owed = partyreports.outstanding(self.client, datetime.date.today(), partyreports.PAYABLES)
        rows = []
        for p in owed.parties:
            if p.total_paise <= 0:
                continue
            party = p.party
            rows.append(
                {
                    "party": party.pk, "name": party.canonical_name, "open_paise": p.total_paise, "bills": len(p.bills),
                    "ready": bool(party.pay_account_enc and party.pay_ifsc and party.pay_account_name), "account_last4": party.pay_account_last4,
                }
            )
        return Response(PayableSerializer(rows, many=True).data)

    @extend_schema(
        summary="Prepare a bank payment file",
        description=(
            "A CSV with one line per payee (mode, beneficiary name, account number, IFSC, amount, date, narration) to give the bank. "
            "RTGS needs at least Rs 2,00,000 a payee and IMPS at most Rs 5,00,000; every payee needs bank details saved. The account numbers are "
            "in the file in full, so it should be handled as sensitive. Nothing is booked; the payment is recorded when it shows on the statement. "
            "The columns are generic: banks differ in layout, so check your bank's template before uploading."
        ),
        request=PaymentFileSerializer,
        responses={200: {"type": "string", "format": "binary"}},
    )
    def create(self, request, client_id=None):
        body = PaymentFileSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        data = body.validated_data
        account = BankAccount.objects.filter(firm_id=request.firm.pk, client=self.client, pk=data["bank_account"]).first()
        if account is None:
            raise NotFound("No such bank account for this client.")
        ids = [i["party"] for i in data["items"]]
        if len(set(ids)) != len(ids):
            raise ValidationError({"items": "Name each party once."})
        parties = {p.pk: p for p in Party.objects.filter(firm_id=request.firm.pk, client=self.client, pk__in=ids)}
        mode, problems, total = data["mode"], [], 0
        for item in data["items"]:
            party = parties.get(item["party"])
            if party is None:
                raise ValidationError({"items": f"{item['party']} is not a party of this client."})
            if not (party.pay_account_enc and party.pay_ifsc and party.pay_account_name):
                problems.append(f"{party.canonical_name}: no bank details saved.")
            if mode == "RTGS" and item["amount_paise"] < RTGS_MINIMUM_PAISE:
                problems.append(f"{party.canonical_name}: RTGS is for payments of Rs 2,00,000 or more.")
            if mode == "IMPS" and item["amount_paise"] > IMPS_MAXIMUM_PAISE:
                problems.append(f"{party.canonical_name}: IMPS is for payments up to Rs 5,00,000.")
            total += item["amount_paise"]
        if total > MAX_FILE_TOTAL:
            problems.append("The file's total is more than a payment file can carry.")
        if problems:
            raise ValidationError({"items": problems})

        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(["Payment mode", "Beneficiary name", "Beneficiary account number", "Beneficiary IFSC", "Amount (INR)", "Payment date", "Narration", "Debit account (last 4)"])
        for item in data["items"]:
            party = parties[item["party"]]
            narration = _safe(item.get("narration") or f"Payment to {party.canonical_name}")[:60]
            writer.writerow(
                [mode, _safe(party.pay_account_name), party.pay_account, party.pay_ifsc, f"{item['amount_paise'] // 100}.{item['amount_paise'] % 100:02d}", data["payment_date"].isoformat(), narration, account.account_last4]
            )
        record_master_change(
            self.client, "SETTING", uuid.uuid4(), "CREATED", label=f"Payment file prepared: {len(data['items'])} payees, {mode}",
            before={}, after={"payees": len(data["items"]), "total_paise": total, "mode": mode, "date": data["payment_date"].isoformat()}, actor=request.user,
        )
        response = HttpResponse(buffer.getvalue(), content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="payments-{data["payment_date"].isoformat()}-{mode.lower()}.csv"'
        response["Cache-Control"] = "no-store"
        return response
