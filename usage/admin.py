"""The usage and cost page of the platform admin: a summary on top of the list of every recorded model call.

Read-only in every way. Nothing is added, changed or deleted here, and the page says nothing about what any call contained
because nothing about that is recorded.
"""

from __future__ import annotations

from django.contrib import admin

from usage.models import UsageEvent
from usage.pricing import inr, usd
from usage.summary import summary


@admin.register(UsageEvent)
class UsageEventAdmin(admin.ModelAdmin):
    change_list_template = "admin/usage/usageevent/change_list.html"
    list_display = (
        "at",
        "purpose",
        "model",
        "outcome",
        "tokens_in",
        "cached",
        "tokens_out",
        "latency_ms",
        "rows",
        "pages",
        "cost_usd",
        "cost_inr",
    )
    list_filter = ("purpose", "outcome", "model", "at")
    date_hierarchy = "at"
    ordering = ("-at",)
    list_per_page = 50

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description="Input tokens", ordering="input_tokens")
    def tokens_in(self, obj):
        return f"{obj.input_tokens:,}"

    @admin.display(description="Cached", ordering="cached_tokens")
    def cached(self, obj):
        return f"{obj.cached_tokens:,}"

    @admin.display(description="Output tokens", ordering="output_tokens")
    def tokens_out(self, obj):
        return f"{obj.output_tokens:,}"

    @admin.display(description="Cost (USD)", ordering="cost_micro_usd")
    def cost_usd(self, obj):
        return f"${usd(obj.cost_micro_usd):.6f}" if obj.priced else "unpriced"

    @admin.display(description="Cost (INR, estimate)", ordering="cost_micro_usd")
    def cost_inr(self, obj):
        return f"₹{inr(obj.cost_micro_usd):.4f}" if obj.priced else "unpriced"

    def changelist_view(self, request, extra_context=None):
        extra = {**(extra_context or {}), "usage": summary()}
        return super().changelist_view(request, extra_context=extra)
