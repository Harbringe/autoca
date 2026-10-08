"""The financial statements in the ICAI format for non-corporate entities."""

from __future__ import annotations

from rest_framework import serializers

from api.fields import PaiseField
from api.serializers.ledger import ReportFooterSerializer
from core.money import MAX_PAISE
from ledger import nce


class StatementRowSerializer(serializers.Serializer):
    key = serializers.CharField()
    label = serializers.CharField()
    kind = serializers.ChoiceField(choices=["heading", "line", "subtotal", "total"])
    level = serializers.IntegerField(help_text="Indentation, from 0.")
    note = serializers.IntegerField(allow_null=True, help_text="The note this line is explained in.")
    current_paise = PaiseField(allow_null=True)
    previous_paise = PaiseField(allow_null=True)


class NoteRowSerializer(serializers.Serializer):
    label = serializers.CharField()
    ledger = serializers.UUIDField(source="ledger_id", allow_null=True, help_text="The ledger, to open it.")
    current_paise = PaiseField()
    previous_paise = PaiseField()
    section = serializers.CharField(allow_blank=True, help_text="The sub-head of the note this row is listed under; blank where the note has none.")
    guessed = serializers.BooleanField(help_text="The sub-head is a catch-all the name fell through to; a person should look.")


class NoteSerializer(serializers.Serializer):
    number = serializers.IntegerField()
    title = serializers.CharField()
    rows = NoteRowSerializer(many=True)
    choices = serializers.ListField(child=serializers.CharField(), help_text="The sub-heads a ledger in this note can be pinned to.")
    total_current_paise = PaiseField()
    total_previous_paise = PaiseField()


class RegroupingSerializer(serializers.Serializer):
    ledger = serializers.UUIDField(source="ledger_id")
    name = serializers.CharField()
    previous_line = serializers.CharField()
    current_line = serializers.CharField()
    previous_paise = PaiseField()
    current_paise = PaiseField()
    text = serializers.CharField(help_text="The disclosure, drafted: where it was shown, where it is shown now, and why.")


class StatementScheduleRowSerializer(serializers.Serializer):
    label = serializers.CharField()
    values = serializers.ListField(child=PaiseField(allow_null=True), help_text="One figure per column; null for a heading.")
    kind = serializers.ChoiceField(choices=["line", "heading", "total"])


class StatementScheduleSerializer(serializers.Serializer):
    note = serializers.IntegerField()
    title = serializers.CharField()
    columns = serializers.ListField(child=serializers.CharField())
    rows = StatementScheduleRowSerializer(many=True)


class PartnerRowSerializer(serializers.Serializer):
    name = serializers.CharField()
    share_bp = serializers.IntegerField(help_text="Share of profit in basis points: 5000 is 50%.")
    opening_paise = PaiseField()
    introduced_paise = PaiseField()
    remuneration_paise = PaiseField()
    interest_paise = PaiseField()
    withdrawals_paise = PaiseField()
    profit_share_paise = PaiseField(help_text="The partner's share of the year's profit or loss.")
    closing_paise = PaiseField()


class CapitalTableSerializer(serializers.Serializer):
    rows = PartnerRowSerializer(many=True)
    previous = PartnerRowSerializer(many=True, help_text="The year before, partner by partner.")
    owners_funds_paise = PaiseField(help_text="Capital and reserves on the balance sheet.")
    difference_paise = PaiseField(help_text="Owners' funds on the balance sheet less the partners' closing balances; nil when they agree.")


class StatementsSerializer(serializers.Serializer):
    balance_sheet = StatementRowSerializer(many=True)
    profit_and_loss = StatementRowSerializer(many=True)
    notes = NoteSerializer(many=True)
    regroupings = RegroupingSerializer(many=True)
    footer = ReportFooterSerializer()
    has_previous = serializers.BooleanField(help_text="False for the first year of books: there is nothing to compare with.")
    balances = serializers.BooleanField(help_text="Total liabilities equal total assets.")
    suspense_paise = PaiseField(help_text="What sits in Suspense, shown on Other current assets or liabilities and warned about.")
    unit_paise = serializers.IntegerField(help_text="Paise in one unit of the figures: 100 for rupees, 10000000 for lakhs. Figures are already rounded to it.")
    unit_label = serializers.CharField(help_text="How the statements state the unit, e.g. 'Rs. in lakhs'.")
    about = serializers.CharField(allow_blank=True, help_text="Note 1.")
    policies = serializers.CharField(allow_blank=True, help_text="Note 2.")
    capital = CapitalTableSerializer(allow_null=True, help_text="Note 3's partner-wise table; null until partners are entered.")
    warnings = serializers.ListField(child=serializers.CharField(), help_text="What to settle before the statements go out.")
    schedules = StatementScheduleSerializer(many=True, help_text="Tables that belong to a note: payables by kind of supplier, receivables by age, the asset block.")
    entity_type = serializers.CharField(allow_blank=True, help_text="proprietor, partnership or other; blank until said.")
    size = serializers.ChoiceField(choices=["msme", "large"], help_text="The entity's size under the accounting standards: the person's choice, else the suggestion.")
    size_suggested = serializers.ChoiceField(choices=["msme", "large"])
    size_reason = serializers.CharField(help_text="Why the books suggest that size.")
    size_statement = serializers.CharField(help_text="The disclosure that goes with the size, drafted for Note 2.")
    capital_title = serializers.CharField(help_text="What Note 3 and the capital line are called for this kind of entity.")


class PartnerInputSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=120)
    share_bp = serializers.IntegerField(min_value=0, max_value=10_000, help_text="Share of profit in basis points.")
    opening_paise = serializers.IntegerField(min_value=0, max_value=MAX_PAISE, allow_null=True, required=False, help_text="Leave empty to carry the previous year's closing balance.")
    introduced_paise = serializers.IntegerField(min_value=0, max_value=MAX_PAISE, default=0)
    remuneration_paise = serializers.IntegerField(min_value=0, max_value=MAX_PAISE, default=0)
    interest_paise = serializers.IntegerField(min_value=0, max_value=MAX_PAISE, default=0)
    withdrawals_paise = serializers.IntegerField(min_value=0, max_value=MAX_PAISE, default=0)


class YearSettingsSerializer(serializers.Serializer):
    closing_stock_paise = serializers.IntegerField(min_value=0, max_value=MAX_PAISE, allow_null=True, required=False)
    receivables_doubtful_paise = serializers.IntegerField(min_value=0, max_value=MAX_PAISE, required=False, help_text="Of the receivables outstanding for over six months, the part that is doubtful.")
    msme_interest_due_paise = serializers.IntegerField(min_value=0, max_value=MAX_PAISE, required=False, help_text="Interest remaining unpaid to MSMED Act suppliers.")
    msme_interest_paid_paise = serializers.IntegerField(min_value=0, max_value=MAX_PAISE, required=False, help_text="Interest paid under section 16, with payments made beyond the appointed day.")
    msme_delay_interest_paise = serializers.IntegerField(min_value=0, max_value=MAX_PAISE, required=False, help_text="Interest due for the delay on payments made late, without the interest under the Act.")
    msme_further_interest_paise = serializers.IntegerField(min_value=0, max_value=MAX_PAISE, required=False, help_text="Further interest remaining due in the succeeding years.")
    partners = PartnerInputSerializer(many=True, max_length=50, required=False)

    def validate_partners(self, value):
        if value and sum(p["share_bp"] for p in value) > 10_000:
            raise serializers.ValidationError("The partners' shares add up to more than 100%.")
        return value


class StatementSettingsSerializer(serializers.Serializer):
    """What the statements need that no ledger holds. Years not sent are left as they are."""

    about = serializers.CharField(allow_blank=True, max_length=8000, required=False, help_text="Note 1: a brief about the entity.")
    policies = serializers.CharField(allow_blank=True, max_length=8000, required=False, help_text="Note 2: significant accounting policies.")
    rounding = serializers.ChoiceField(choices=list(nce.UNITS), required=False)
    entity_type = serializers.ChoiceField(choices=["", *nce.ENTITY_TYPES], required=False, allow_blank=True, help_text="Proprietorship, partnership or another kind of non-corporate entity.")
    size = serializers.ChoiceField(choices=["", "msme", "large"], required=False, allow_blank=True, help_text="Blank follows the suggestion from the books.")
    bank_or_insurer = serializers.BooleanField(required=False, help_text="The entity is a bank, financial institution or insurance company.")
    non_msme_group = serializers.BooleanField(required=False, help_text="The entity is a holding or subsidiary of an entity that is not an MSME.")
    years = serializers.DictField(child=YearSettingsSerializer(), required=False, help_text="By starting year of the financial year, e.g. '2025'.")

    def validate_years(self, value):
        for key in value:
            if not (key.isdigit() and 2000 <= int(key) <= 2100):
                raise serializers.ValidationError(f"'{key}' is not a financial year; use its starting year, e.g. 2025.")
        return value
