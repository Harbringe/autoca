"""Approval, corrections, reports and reconciliation."""

from __future__ import annotations

import datetime
import uuid

from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework import mixins, serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response

from api.pagination import DefaultPagination
from api.permissions import CanApprove, HasFirmPermission
from api.serializers.analysis import GroupSummarySerializer, LedgerMonthlySerializer
from api.serializers.classify import ApproveSerializer
from api.serializers.inventory import (
    Gstr1FileSerializer,
    Gstr1Serializer,
    Gstr3bEntriesSerializer,
    Gstr3bSerializer,
    GstTieOutSerializer,
    InventorySerializer,
    StockReconciliationSerializer,
    inventory_payload,
)
from api.serializers.ledger import (
    BalanceCheckSerializer,
    BalanceSheetSerializer,
    CorrectionSerializer,
    EntryChangeSerializer,
    JournalEntrySerializer,
    ProfitAndLossSerializer,
    RectifySerializer,
    RemoveEntrySerializer,
    TrialBalanceSerializer,
)
from api.serializers.nce import StatementSettingsSerializer, StatementsSerializer
from api.serializers.openitems import BillStatusSerializer
from api.serializers.settlement import (
    SettledSerializer,
    SettleEntrySerializer,
    SettlementContextSerializer,
)
from api.views.settlement import build_context, settlement_from
from banking.models import BankAccount
from classify.engine import pending_approval
from classify.models import LedgerAccount, Party
from classify.treatment import Treatment
from core.access import can_post, get_visible_client, posting_refusal, visible_client_ids
from core.fy import financial_year
from core.money import format_inr
from ledger import billing, nce, nce_export
from ledger import rectify as rectifying
from ledger import settlement as settling
from ledger.approval import approve_many, correct
from ledger.editing import remove_entry, require_bank_entry
from ledger.models import EntryChange, JournalEntry
from ledger.reconciliation import check_balance
from ledger.reports import balance_sheet, profit_and_loss, trial_balance
from ledger.settlement import party_line_of

FY_PARAM = OpenApiParameter(
    "fy", int, description="Financial year by its starting year: 2025 means FY2025-26."
)


@extend_schema(tags=["ledger"])
class JournalEntryViewSet(
    mixins.RetrieveModelMixin, mixins.ListModelMixin, viewsets.GenericViewSet
):
    """The permanent record.

    Read-only over HTTP, and read-only in PostgreSQL too -- the journal tables
    carry no UPDATE or DELETE grant and triggers that raise. Entries are created
    by approval, never by a POST to a collection: there is a permission to check
    and a voucher number to allocate under a lock.
    """

    serializer_class = JournalEntrySerializer
    permission_classes = [HasFirmPermission]
    pagination_class = DefaultPagination
    required_permission = "journal.view"
    queryset = JournalEntry.objects.all()

    def get_queryset(self):
        queryset = (
            JournalEntry.objects.filter(
                firm_id=self.request.firm.pk,
                client__in=visible_client_ids(self.request.membership),
            )
            .select_related("approved_by", "client", "bill", "tally_voucher")
            .prefetch_related("lines__ledger_account", "lines__party", "superseded_by_set")
        )
        client_id = self.request.query_params.get("client")
        if client_id:
            try:
                queryset = queryset.filter(client_id=uuid.UUID(client_id))
            except ValueError as exc:
                raise serializers.ValidationError({"client": "Not a client id."}) from exc
        if self.request.query_params.get("live") == "true":
            queryset = queryset.filter(superseded_by_set__isnull=True)
        return queryset

    @extend_schema(
        parameters=[
            OpenApiParameter("client", str, description="Filter to one client."),
            OpenApiParameter(
                "live",
                str,
                enum=["true"],
                description=(
                    "Only entries that have not been corrected. A superseded entry "
                    "stays in the record permanently, so it is included by default."
                ),
            ),
        ]
    )
    def list(self, request, *args, **kwargs):
        return super().list(request, *args, **kwargs)

    @extend_schema(
        summary="Correct a posted entry",
        description=(
            "The original is not edited -- it cannot be. A correction is a new "
            "entry carrying a reversal of the original's lines plus the corrected "
            "ones, linked back to it. The original stays visible, which is what "
            "company law expects, and the two together net to the corrected "
            "position so the trial balance is right at every point in the chain.\n\n"
            "Requires `journal.correct` (staff and above, on their assigned clients). Once the entry is inside signed-off books only the client's lead or a firm administrator may adjust it; anyone else is told it is locked (409 `entry_locked`)."
        ),
        request=CorrectionSerializer,
        responses={201: JournalEntrySerializer},
    )
    @action(detail=True, methods=["post"], permission_classes=[CanApprove])
    def correct(self, request, pk=None):
        entry = self.get_object()
        payload = CorrectionSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        treatment_data = payload.validated_data["treatment"]

        client = entry.client
        ledger = get_object_or_404(
            LedgerAccount, pk=treatment_data["ledger"], firm_id=request.firm.pk, client=client
        )
        party = (
            get_object_or_404(
                Party, pk=treatment_data["party"], firm_id=request.firm.pk, client=client
            )
            if treatment_data.get("party")
            else None
        )

        corrected = correct(
            entry,
            membership=request.membership,
            treatment=Treatment(
                ledger=ledger,
                party=party,
                rcm=treatment_data["rcm"],
                tds_section=treatment_data.get("tds_section", ""),
            ),
            narration=payload.validated_data.get("narration") or None,
            learn=treatment_data.get("learn", True),
        )
        return Response(
            JournalEntrySerializer(corrected).data, status=status.HTTP_201_CREATED
        )

    @extend_schema(
        summary="Rectify an entry inside signed-off books",
        description=(
            "Sealed books are not edited. This posts a journal, dated after the sign-off, that moves an amount from the wrong "
            "ledger to the right one; the original stays as it was and its change log records the rectification. Only the "
            "client's lead or a firm administrator may do it, a reason is required, and party and bank/cash ledgers are "
            "refused (those are put right through allocations or the statement)."
        ),
        request=RectifySerializer,
        responses={201: JournalEntrySerializer},
    )
    @action(detail=True, methods=["post"], permission_classes=[CanApprove])
    def rectify(self, request, pk=None):
        entry = self.get_object()
        payload = RectifySerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        data = payload.validated_data
        scope = {"firm_id": request.firm.pk, "client": entry.client}
        journal = rectifying.rectify(
            entry,
            from_ledger=get_object_or_404(LedgerAccount, pk=data["from_ledger"], **scope),
            to_ledger=get_object_or_404(LedgerAccount, pk=data["to_ledger"], **scope),
            amount_paise=data["amount_paise"],
            reason=data["reason"],
            membership=request.membership,
            on=data.get("date"),
        )
        return Response(JournalEntrySerializer(journal).data, status=status.HTTP_201_CREATED)

    @extend_schema(
        summary="Remove an entry from the working books",
        description=(
            "Only while the entry's period is not signed off. The transaction it came "
            "from goes back to the queue, and the entry is kept in the change log."
        ),
        request=RemoveEntrySerializer,
        responses={204: None},
    )
    @action(detail=True, methods=["post"], permission_classes=[CanApprove])
    def remove(self, request, pk=None):
        entry = self.get_object()
        payload = RemoveEntrySerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        if not can_post(request.membership, entry.client):
            raise PermissionDenied(posting_refusal(entry.client))
        remove_entry(entry, actor=request.user, note=payload.validated_data["note"])
        return Response(status=status.HTTP_204_NO_CONTENT)

    @extend_schema(
        summary="Which bills the unallocated part of this payment could settle",
        description=(
            "For a payment on a party's account that is posted but not fully allocated: the party's open bills and a "
            "suggestion of how the rest would clear them. Only a suggestion."
        ),
        responses={200: SettlementContextSerializer},
    )
    @action(detail=True, methods=["get"], pagination_class=None)
    def settlement(self, request, pk=None):
        entry = self.get_object()
        line, left = party_line_of(entry)
        if left <= 0:
            raise billing.BillingError("This entry is already fully allocated.")
        return Response(build_context(line.party, line.direction, left, already=line.amount_paise - left))

    @extend_schema(
        summary="Settle the unallocated part of a posted payment",
        description=(
            "Allocates what is not yet allocated on a payment's party line: to bills, and the rest held on account or "
            "as an advance. A person decides; nothing is matched on its own. Needs `journal.approve`."
        ),
        request=SettleEntrySerializer,
        responses={200: SettledSerializer},
    )
    @action(detail=True, methods=["post"], permission_classes=[CanApprove])
    def settle(self, request, pk=None):
        entry = self.get_object()
        payload = SettleEntrySerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        settled = settling.settle_entry(
            entry, settlement_from(entry.client, request.firm.pk, payload.validated_data), membership=request.membership
        )
        _, left = party_line_of(JournalEntry.objects.get(pk=entry.pk))
        return Response(
            {"settled_paise": settled, "settled_display": format_inr(settled), "fully_allocated": left <= 0}
        )

    @extend_schema(
        summary="The party's open bills for a posted payment that is not on their account yet",
        description=(
            "For a posted bank payment booked to some head (Sales, an expense) whose party is recorded: the party's open "
            "bills and a suggestion of how the payment would clear them. Only a suggestion; nothing moves."
        ),
        responses={200: SettlementContextSerializer},
    )
    @action(detail=True, methods=["get"], url_path="move-to-party", pagination_class=None)
    def move_to_party_context(self, request, pk=None):
        entry = self.get_object()
        party = settling.party_of_posted_payment(entry)
        txn = entry.source_transaction
        return Response(build_context(party, settling.line_direction_for(txn), txn.amount_paise))

    @extend_schema(
        summary="Move a posted payment onto its party's account and settle it",
        description=(
            "Corrects the posted entry so it sits on the party's own account instead of the head it was booked to, and "
            "allocates it to the bills a person names (the rest held on account or as an advance), in one step. If the "
            "settlement is refused nothing moves. A person decides every time. Refused inside signed-off books. Needs "
            "`journal.approve`."
        ),
        request=SettleEntrySerializer,
        responses={200: SettledSerializer},
    )
    @move_to_party_context.mapping.post
    def move_to_party(self, request, pk=None):
        entry = self.get_object()
        payload = SettleEntrySerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        moved = settling.move_to_party_account(
            entry, settlement_from(entry.client, request.firm.pk, payload.validated_data), membership=request.membership
        )
        return Response({"settled_paise": moved, "settled_display": format_inr(moved), "fully_allocated": True})

    @extend_schema(
        summary="Say why a payment to a party with bills has no invoice against it",
        description=(
            "A payment booked to an expense head, to a party that has bills, goes round those bills; until someone says why "
            "it is an open item. `NO_INVOICE_EXPECTED` marks a direct expense, `NEEDS_INVOICE` keeps it listed as waiting "
            "for one. A note about the document trail: it changes nothing that is posted, so it may be set at any time. "
            "Bank entries only. Needs `journal.approve`."
        ),
        request=BillStatusSerializer,
        responses={200: BillStatusSerializer},
    )
    @action(detail=True, methods=["post"], url_path="bill-status", permission_classes=[CanApprove])
    def bill_status(self, request, pk=None):
        entry = self.get_object()
        if not can_post(request.membership, entry.client):
            raise PermissionDenied(posting_refusal(entry.client))
        require_bank_entry(entry)
        payload = BillStatusSerializer(data=request.data)
        payload.is_valid(raise_exception=True)
        classification = entry.source_transaction.classification
        classification.bill_status = payload.validated_data["status"]
        classification.save(update_fields=["bill_status"])
        return Response({"status": classification.bill_status})

    @extend_schema(
        summary="What this entry used to be",
        description="Every change made to the entry while it was a working draft, oldest first.",
        responses={200: EntryChangeSerializer(many=True)},
    )
    @action(detail=True, methods=["get"], pagination_class=None)
    def changes(self, request, pk=None):
        entry = self.get_object()
        rows = EntryChange.objects.filter(
            firm_id=request.firm.pk, client_id=entry.client_id, entry_id=entry.pk
        ).select_related("actor")
        return Response(EntryChangeSerializer(rows, many=True).data)


@extend_schema(tags=["ledger"])
class ApprovalView(viewsets.GenericViewSet):
    """Turn reviewed rows into permanent entries."""

    serializer_class = ApproveSerializer
    permission_classes = [CanApprove]

    @extend_schema(
        summary="Approve classified rows",
        description=(
            "The moment a suggestion becomes a ledger entry. Any role that prepares "
            "books (staff and above) may post on the clients it is assigned to; the "
            "entry stays a working draft, changeable and logged, until a senior signs "
            "the books off. Checked server-side, not by a hidden button.\n\n"
            "Send either an explicit list of classification ids, or a whole "
            "confidence band. `band=HIGH` is the one-click bulk approval for "
            "everything the system is sure about.\n\n"
            "**All or nothing.** One unapprovable row fails the batch rather than "
            "leaving it half-posted, which would be worse -- the reviewer would "
            "have to work out which half."
        ),
        request=ApproveSerializer,
        responses={201: JournalEntrySerializer(many=True)},
    )
    def create(self, request, client_id=None):
        client = get_visible_client(request, client_id)
        if not can_post(request.membership, client):
            raise PermissionDenied(posting_refusal(client))
        payload = self.get_serializer(data=request.data)
        payload.is_valid(raise_exception=True)

        rows = list(pending_approval(client))
        if payload.validated_data.get("band"):
            band = payload.validated_data["band"]
            # A row on a party's account needs a person to say which bills it settles, so a whole band never sweeps it
            # in. The review screen shows those rows apart, each with its own settlement.
            rows = [row for row in rows if row.review_band == band and not row.ledger.is_party_account]
        else:
            wanted = {str(pk) for pk in payload.validated_data["classifications"]}
            rows = [row for row in rows if str(row.pk) in wanted]
            missing = wanted - {str(row.pk) for row in rows}
            if missing:
                raise serializers.ValidationError(
                    {
                        "classifications": (
                            f"{len(missing)} of these {'is' if len(missing) == 1 else 'are'} not awaiting "
                            f"approval -- already posted, or not yet placed in a ledger."
                        )
                    }
                )

        settlements = {
            item["classification"]: settlement_from(client, request.firm.pk, item)
            for item in payload.validated_data.get("settlements", [])
        }
        stray = set(settlements) - {row.pk for row in rows}
        if stray:
            raise serializers.ValidationError(
                {"settlements": f"{len(stray)} of these are for rows that are not being approved here."}
            )

        results = approve_many(rows, membership=request.membership, settlements=settlements)
        return Response(
            JournalEntrySerializer([r.entry for r in results], many=True).data,
            status=status.HTTP_201_CREATED,
        )


@extend_schema(tags=["reports"])
class ReportView(viewsets.GenericViewSet):
    """Trial Balance, P&L and Balance Sheet.

    Every one states the year it covers, how many entries are behind it, and how
    many rows are still unposted. A report over incomplete books is not wrong,
    but handing one to a client without knowing that is.
    """

    permission_classes = [HasFirmPermission]
    required_permission = {"GET": "report.view", "POST": "ledger.manage", "PUT": "ledger.manage"}
    serializer_class = TrialBalanceSerializer

    def _client_and_year(self, request, client_id):
        client = get_visible_client(request, client_id)
        raw = request.query_params.get("fy")
        if raw:
            try:
                year = int(raw)
            except ValueError as exc:
                raise serializers.ValidationError(
                    {"fy": "Give the financial year by its starting year, e.g. 2025 for FY2025-26."}
                ) from exc
            if not 2000 <= year <= 2100:
                raise serializers.ValidationError(
                    {"fy": "Give the financial year by its starting year, e.g. 2025 for FY2025-26."}
                )
        else:
            year = financial_year(datetime.date.today())
        return client, year

    @extend_schema(
        summary="Trial balance",
        parameters=[FY_PARAM],
        responses=TrialBalanceSerializer,
    )
    @action(detail=False, methods=["get"], url_path="trial-balance")
    def trial_balance(self, request, client_id=None):
        client, year = self._client_and_year(request, client_id)
        return Response(TrialBalanceSerializer(trial_balance(client, year)).data)

    @extend_schema(
        summary="Profit and loss", parameters=[FY_PARAM], responses=ProfitAndLossSerializer
    )
    @action(detail=False, methods=["get"], url_path="profit-and-loss")
    def profit_and_loss(self, request, client_id=None):
        client, year = self._client_and_year(request, client_id)
        return Response(ProfitAndLossSerializer(profit_and_loss(client, year)).data)

    @extend_schema(
        summary="Inventory: stock by item and month",
        description=(
            "Inwards, outwards and closing stock for each item, month by month, with the earlier years as the opening. Taken "
            "from the lines of the invoices behind the booked purchases (stock in) and sales (stock out), valued at weighted "
            "average cost. Purchases and sales with no invoice lines are counted and named as left out."
        ),
        parameters=[FY_PARAM, OpenApiParameter("godown", OpenApiTypes.STR, description="A godown's id, or `none` for the main location; leave out for the whole business."), OpenApiParameter("as_at", OpenApiTypes.DATE, description="Stock as it stood on this day: movements after it are left out.")],
        responses=InventorySerializer,
    )
    @action(detail=False, methods=["get"], url_path="inventory")
    def inventory(self, request, client_id=None):
        from ledger import inventory as stock
        from ledger.reports import _footer

        client, year = self._client_and_year(request, client_id)
        godown = request.query_params.get("godown") or None
        as_at = request.query_params.get("as_at")
        try:
            as_at_date = datetime.date.fromisoformat(as_at) if as_at else None
        except ValueError as exc:
            raise serializers.ValidationError({"as_at": "A date as YYYY-MM-DD."}) from exc
        report = stock.build(client, year, godown=godown, as_at=as_at_date)
        footer = _footer(client, year, datetime.date(year, 4, 1), datetime.date(year + 1, 3, 31))
        return Response(InventorySerializer(inventory_payload(report, footer)).data)

    @extend_schema(
        summary="Stock against the books",
        description=(
            "Reads the stock register, the Stock-in-Hand ledgers, the bills and the item list and says where they part: closing stock "
            "value against the books, items sold before bought, items missing from the list, units that differ, purchases and sales that "
            "move no stock. Writes nothing."
        ),
        parameters=[FY_PARAM],
        responses=StockReconciliationSerializer,
    )
    @action(detail=False, methods=["get"], url_path="stock-reconciliation")
    def stock_reconciliation(self, request, client_id=None):
        from ledger import stock_recon

        client, year = self._client_and_year(request, client_id)
        return Response(StockReconciliationSerializer(stock_recon.build(client, year)).data)

    @extend_schema(
        summary="GST on the invoices against GST in the books",
        description=(
            "For each tax head (CGST, SGST, IGST, Cess), the output and input tax on the year's sales, purchases and their notes "
            "against what the Output and Input GST ledgers moved, with the month-by-month outward and inward working a 3B return starts "
            "from. Reverse-charge purchases are left out of both sides. Writes nothing."
        ),
        parameters=[FY_PARAM],
        responses=GstTieOutSerializer,
    )
    @action(detail=False, methods=["get"], url_path="gst-tieout")
    def gst_tieout(self, request, client_id=None):
        from ledger import gst_tieout

        client, year = self._client_and_year(request, client_id)
        return Response(GstTieOutSerializer(gst_tieout.build(client, year)).data)

    @extend_schema(
        summary="GSTR-3B working for a month",
        description=(
            "The figures a GSTR-3B return is filled from for one month: outward taxable supplies (3.1(a)), the exempt, nil, zero-rated "
            "and non-GST supplies entered for the month (3.1(b), (c), (e)), reverse-charge inward supplies (3.1(d)), input credit "
            "(4(A)), credit reversed (4(B)), the tax payable (6.1) paid by credit and in cash, interest and late fee, and the credit "
            "carried forward. Credit carries from April of the year and is applied in the order section 49A sets."
        ),
        parameters=[OpenApiParameter("month", OpenApiTypes.STR, description="YYYY-MM", required=True)],
        responses=Gstr3bSerializer,
    )
    @action(detail=False, methods=["get"], url_path="gstr3b")
    def gstr3b(self, request, client_id=None):
        from ledger import gstr3b

        client = get_visible_client(request, client_id)
        month = self._month(request)
        return Response(Gstr3bSerializer(gstr3b.build(client, month)).data)

    @extend_schema(
        summary="Enter what the invoices do not hold for a GSTR-3B month",
        description=(
            "Exempt, nil-rated, zero-rated and non-GST supplies, credit reversed, interest, late fee, and an opening credit that puts "
            "the carried-forward credit right. Replaces the month's entries; recorded in the audit trail. Requires `ledger.manage`."
        ),
        parameters=[OpenApiParameter("month", OpenApiTypes.STR, description="YYYY-MM", required=True)],
        request=Gstr3bEntriesSerializer,
        responses=Gstr3bSerializer,
    )
    @gstr3b.mapping.put
    def gstr3b_entries(self, request, client_id=None):
        import uuid

        from ledger import gstr3b
        from ledger.audit import record_master_change

        client = get_visible_client(request, client_id)
        month = self._month(request)
        body = Gstr3bEntriesSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        before = gstr3b.read_entries(client, month)
        stored = dict(client.gst_return_entries or {})
        stored[month] = gstr3b.normalise_entries(body.validated_data)
        client.gst_return_entries = stored
        client.save(update_fields=["gst_return_entries"])
        record_master_change(
            client, "SETTING", uuid.uuid4(), "EDITED", label=f"GSTR-3B entries for {month}",
            before=before, after=gstr3b.read_entries(client, month), actor=request.user,
        )
        return Response(Gstr3bSerializer(gstr3b.build(client, month)).data)

    @extend_schema(
        summary="GSTR-1 working for a month",
        description=(
            "The tables a GSTR-1 return is filled from, from the booked sales invoices and credit notes: B2B (4), B2C large (5), B2C other "
            "by rate and inter/intra-state (7), credit notes (9B), exempt, nil and non-GST from the month's GSTR-3B entries (8), the HSN "
            "summary from invoices with item lines (12) and documents issued (13). Place of supply is not recorded, so B2C is not by state."
        ),
        parameters=[OpenApiParameter("month", OpenApiTypes.STR, description="YYYY-MM", required=True)],
        responses=Gstr1Serializer,
    )
    @action(detail=False, methods=["get"], url_path="gstr1")
    def gstr1(self, request, client_id=None):
        from ledger import gstr1

        client = get_visible_client(request, client_id)
        return Response(Gstr1Serializer(gstr1.build(client, self._month(request))).data)

    @extend_schema(
        summary="Group summary",
        description="Each group's opening, debit, credit and closing for the year, with the ledgers under it. Read from the same balances as the Trial Balance.",
        parameters=[FY_PARAM],
        responses=GroupSummarySerializer,
    )
    @action(detail=False, methods=["get"], url_path="group-summary")
    def group_summary(self, request, client_id=None):
        from ledger import analysis

        client, year = self._client_and_year(request, client_id)
        return Response(GroupSummarySerializer(analysis.group_summary(client, year)).data)

    @extend_schema(
        summary="A ledger month by month",
        description="One ledger through the twelve months of the year: debit, credit and the balance after each, ending at the Trial Balance closing.",
        parameters=[FY_PARAM, OpenApiParameter("ledger", OpenApiTypes.UUID, required=True)],
        responses=LedgerMonthlySerializer,
    )
    @action(detail=False, methods=["get"], url_path="ledger-monthly")
    def ledger_monthly(self, request, client_id=None):
        from ledger import analysis

        client, year = self._client_and_year(request, client_id)
        try:
            ledger_id = uuid.UUID(request.query_params.get("ledger", ""))
        except ValueError:
            raise serializers.ValidationError({"ledger": "Give the ledger's id."}) from None
        ledger = LedgerAccount.objects.filter(firm_id=client.firm_id, client=client, pk=ledger_id).first()
        if ledger is None:
            from rest_framework.exceptions import NotFound

            raise NotFound("No such ledger for this client.")
        return Response(LedgerMonthlySerializer(analysis.ledger_monthly(client, year, ledger)).data)

    @extend_schema(
        summary="GSTR-1 as an offline-tool JSON file",
        description=(
            "The month's GSTR-1 working in the shape of the GST portal's offline-tool JSON, with what the books cannot say (place of "
            "supply of unregistered buyers, aggregate turnover, the split of nil and exempt supplies) listed as missing. Run it through the "
            "offline tool before filing. Nothing is sent to the portal."
        ),
        parameters=[OpenApiParameter("month", OpenApiTypes.STR, description="YYYY-MM", required=True)],
        responses=Gstr1FileSerializer,
    )
    @action(detail=False, methods=["get"], url_path="gstr1/file")
    def gstr1_file(self, request, client_id=None):
        from ledger import gstr1_file

        client = get_visible_client(request, client_id)
        return Response(Gstr1FileSerializer(gstr1_file.build(client, self._month(request))).data)

    @staticmethod
    def _month(request) -> str:
        from ledger import gstr3b

        month = request.query_params.get("month", "")
        if not gstr3b.MONTH.match(month):
            raise serializers.ValidationError({"month": "A month as YYYY-MM."})
        return month

    @extend_schema(
        summary="Use the register's closing stock for the year",
        description=(
            "Sets the year's closing stock in the statement settings to what the stock register holds at the year's end, so the "
            "profit and the balance sheet agree with the register. Replaces any figure entered before, and says what it replaced. "
            "Requires `ledger.manage`."
        ),
        parameters=[FY_PARAM],
        request=None,
        responses=StockReconciliationSerializer,
    )
    @action(detail=False, methods=["post"], url_path="stock-reconciliation/use-register")
    def use_register_stock(self, request, client_id=None):
        import uuid

        from ledger import nce, stock_recon
        from ledger.audit import record_master_change

        client, year = self._client_and_year(request, client_id)
        register = stock_recon.build(client, year)["register_value_paise"]
        current = nce.read_settings(client)
        before = current["years"].get(str(year), {}).get("closing_stock_paise")
        year_body = current["years"].setdefault(str(year), {"partners": []})
        year_body["closing_stock_paise"] = register
        client.nce_settings = nce.normalise_settings(current)
        client.save(update_fields=["nce_settings"])
        record_master_change(
            client, "SETTING", uuid.uuid4(), "EDITED",
            label=f"Closing stock {year}-{str(year + 1)[2:]} taken from the stock register",
            before={"closing_stock_paise": before}, after={"closing_stock_paise": register}, actor=request.user,
        )
        return Response(StockReconciliationSerializer(stock_recon.build(client, year)).data)

    @extend_schema(
        summary="Balance sheet", parameters=[FY_PARAM], responses=BalanceSheetSerializer
    )
    @action(detail=False, methods=["get"], url_path="balance-sheet")
    def balance_sheet(self, request, client_id=None):
        client, year = self._client_and_year(request, client_id)
        return Response(BalanceSheetSerializer(balance_sheet(client, year)).data)


    @extend_schema(
        summary="Financial statements in the ICAI non-corporate format",
        description=(
            "The vertical Balance Sheet and the Statement of Profit and Loss of ICAI's Guidance Note on Financial Statements "
            "of Non-Corporate Entities, the previous year beside the current one, the notes behind every line, and any "
            "ledger whose balance changed sign between the years and so moved from one line to another (a regrouping, with "
            "its disclosure drafted). Where a ledger sits is worked out each year from its group, its name and its balance, "
            "unless the ledger's `nce_line` says."
        ),
        parameters=[FY_PARAM],
        responses=StatementsSerializer,
    )
    @action(detail=False, methods=["get"], url_path="financial-statements")
    def financial_statements(self, request, client_id=None):
        client, year = self._client_and_year(request, client_id)
        return Response(StatementsSerializer(nce.build(client, year)).data)

    @extend_schema(
        summary="Download the financial statements as an Excel workbook",
        description=(
            "The Balance Sheet, Statement of Profit and Loss and the notes of the ICAI non-corporate format as an .xlsx, "
            "in the unit the client's statements are rounded to."
        ),
        parameters=[FY_PARAM],
        responses={(200, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"): OpenApiTypes.BINARY},
    )
    def financial_statements_export(self, request, client_id=None):
        client, year = self._client_and_year(request, client_id)
        response = HttpResponse(
            nce_export.workbook(client, year, nce.build(client, year)),
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response["Content-Disposition"] = f'attachment; filename="financial-statements-FY{year}-{(year + 1) % 100:02d}.xlsx"'
        return response


@extend_schema(tags=["reports"])
class StatementSettingsView(viewsets.GenericViewSet):
    """What the financial statements need that no ledger holds."""

    permission_classes = [HasFirmPermission]
    required_permission = {"GET": "report.view", "PUT": "ledger.manage"}
    serializer_class = StatementSettingsSerializer

    @extend_schema(summary="Statement settings", responses=StatementSettingsSerializer)
    def retrieve(self, request, client_id=None):
        client = get_visible_client(request, client_id)
        return Response(StatementSettingsSerializer(nce.read_settings(client)).data)

    @extend_schema(
        summary="Change the statement settings",
        description=(
            "Notes 1 and 2, the units the statements are rounded to, and for each financial year the closing stock and the "
            "partners with their shares and movements (Note 3). Years not sent are kept as they are; a year that is sent "
            "replaces everything entered for that year. Requires `ledger.manage`."
        ),
        request=StatementSettingsSerializer,
        responses=StatementSettingsSerializer,
    )
    def update(self, request, client_id=None):
        client = get_visible_client(request, client_id)
        body = StatementSettingsSerializer(data=request.data)
        body.is_valid(raise_exception=True)
        current = nce.read_settings(client)
        for key in ("about", "policies", "rounding", "entity_type", "size", "bank_or_insurer", "non_msme_group"):
            if key in body.validated_data:
                current[key] = body.validated_data[key]
        for fy, year in body.validated_data.get("years", {}).items():
            current["years"][fy] = {**year, "partners": year.get("partners", [])}
        client.nce_settings = nce.normalise_settings(current)
        client.save(update_fields=["nce_settings"])
        return Response(StatementSettingsSerializer(nce.read_settings(client)).data)


@extend_schema(tags=["reports"])
class ReconciliationView(viewsets.GenericViewSet):
    """Does the bank ledger agree with the bank?"""

    permission_classes = [HasFirmPermission]
    required_permission = "journal.view"
    serializer_class = BalanceCheckSerializer
    #: Declared so the schema knows the path parameter is a bank account id and
    #: types it as a uuid rather than falling back to an untyped string.
    queryset = BankAccount.objects.none()

    @extend_schema(
        summary="Month-end balance check",
        description=(
            "Compares the computed bank-ledger balance against the statement's own "
            "closing figure. One subtraction that catches what every other check "
            "misses -- a row posted twice, a correction reversed the wrong way, an "
            "entry approved against the wrong account.\n\n"
            "`can_close` is the one to act on: it requires both that the figures "
            "agree *and* that nothing up to that date is still unposted. A period "
            "that does not reconcile is not finished."
        ),
        parameters=[
            OpenApiParameter(
                "as_of", str, required=True, description="Date to reconcile at, as YYYY-MM-DD."
            )
        ],
        responses=BalanceCheckSerializer,
    )
    @action(detail=True, methods=["get"])
    def reconciliation(self, request, pk=None):
        account = get_object_or_404(
            BankAccount,
            pk=pk,
            firm_id=request.firm.pk,
            client__in=visible_client_ids(request.membership),
        )
        raw = request.query_params.get("as_of")
        if not raw:
            raise serializers.ValidationError({"as_of": "Required, as YYYY-MM-DD."})
        try:
            as_of = datetime.date.fromisoformat(raw)
        except ValueError as exc:
            raise serializers.ValidationError({"as_of": f"Not a date: {raw!r}."}) from exc

        return Response(BalanceCheckSerializer(check_balance(account, as_of)).data)
