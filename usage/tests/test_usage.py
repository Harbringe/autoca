"""What a model call costs, that it is recorded without ever breaking the work, and what the owner's page reads from it."""

from __future__ import annotations

import datetime
import uuid
from decimal import Decimal
from types import SimpleNamespace
from unittest import mock

import pytest
from django.utils import timezone

from api.tests.conftest import sign_in
from core.models import User
from usage import pricing
from usage.models import Outcome, Purpose, UsageEvent
from usage.recorder import record
from usage.summary import summary

pytestmark = pytest.mark.django_db


def reply(model="gpt-6-luna", input_tokens=2000, cached=1000, output=1000):
    return SimpleNamespace(
        model=model, input_tokens=input_tokens, cached_tokens=cached, output_tokens=output
    )


# -- the price ---------------------------------------------------------------------------------------------------------


def test_a_call_is_priced_in_whole_millionths_of_a_dollar_with_cached_input_at_its_own_rate():
    # 1,000 fresh x $0.10 + 1,000 cached x $0.01 + 1,000 out x $0.50 per million = 100 + 10 + 500 micro-dollars.
    assert pricing.cost_micro_usd("gpt-6-luna", 2000, 1000, 1000) == (610, True)


def test_a_model_with_no_price_is_unpriced_not_free():
    assert pricing.cost_micro_usd("some-other-model", 5000, 0, 5000) == (0, False)


def test_cached_tokens_can_never_exceed_the_input():
    assert pricing.cost_micro_usd("gpt-6-luna", 100, 900, 0) == (
        1,
        True,
    )  # 100 cached tokens at $0.01 per million


# -- recording ---------------------------------------------------------------------------------------------------------


def test_a_call_is_recorded_with_its_tokens_and_cost():
    firm, client = uuid.uuid4(), uuid.uuid4()

    record(
        purpose=Purpose.CLASSIFY,
        response=reply(),
        firm_id=firm,
        client_id=client,
        latency_ms=1500,
        rows=10,
    )

    event = UsageEvent.objects.get()
    assert (event.input_tokens, event.cached_tokens, event.output_tokens) == (2000, 1000, 1000)
    assert event.cost_micro_usd == 610 and event.priced and event.outcome == Outcome.OK
    assert (event.firm_id, event.client_id, event.rows, event.latency_ms) == (
        firm,
        client,
        10,
        1500,
    )


def test_a_failed_call_is_recorded_with_no_tokens():
    record(purpose=Purpose.SCAN, outcome=Outcome.RATE_LIMITED, model="gpt-6-luna", pages=3)

    event = UsageEvent.objects.get()
    assert event.outcome == Outcome.RATE_LIMITED and event.input_tokens == 0 and event.pages == 3


def test_a_failure_to_record_never_breaks_the_caller_or_its_transaction():
    with mock.patch.object(UsageEvent.objects, "create", side_effect=RuntimeError("boom")):
        record(purpose=Purpose.CLASSIFY, response=reply())  # must not raise

    # The caller's own transaction is still usable afterwards.
    record(purpose=Purpose.CLASSIFY, response=reply())
    assert UsageEvent.objects.count() == 1


# -- the summary -------------------------------------------------------------------------------------------------------


def make(
    when, *, firm=None, purpose=Purpose.CLASSIFY, outcome=Outcome.OK, cost=1000, rows=10, **tokens
):
    return UsageEvent.objects.create(
        at=when,
        purpose=purpose,
        model="gpt-6-luna",
        outcome=outcome,
        firm_id=firm,
        input_tokens=tokens.get("input_tokens", 1000),
        cached_tokens=tokens.get("cached_tokens", 500),
        output_tokens=tokens.get("output_tokens", 100),
        cost_micro_usd=cost,
        rows=rows,
    )


def test_the_summary_adds_up_today_and_this_month():
    now = timezone.now().replace(hour=12, minute=0, second=0, microsecond=0)
    make(now, cost=2_000_000)
    make(now - datetime.timedelta(hours=1), cost=1_000_000, outcome=Outcome.ERROR)
    last_month = now.replace(day=1) - datetime.timedelta(days=3)
    make(last_month, cost=9_000_000)

    result = summary(now)

    assert result["today"]["calls"] == 2 and result["today"]["failed"] == 1
    assert result["today"]["cost_usd"] == 3
    assert result["month"]["calls"] == 2  # last month's call is not in this month
    assert result["month"]["cache_hit_percent"] == 50
    assert result["month"]["usd_per_row"] == pytest.approx(3 / 20)


def test_the_daily_series_has_thirty_days_and_fills_quiet_days_with_zero():
    now = timezone.now()
    make(now, cost=5_000_000)

    daily = summary(now)["daily"]

    assert len(daily) == 30 and daily[-1]["calls"] == 1 and daily[-1]["percent_of_peak"] == 100
    assert daily[0]["calls"] == 0 and daily[0]["percent_of_peak"] == 0


def test_the_firms_that_spend_the_most_come_first():
    now = timezone.now()
    small, big = uuid.uuid4(), uuid.uuid4()
    make(now, firm=small, cost=1_000_000)
    make(now, firm=big, cost=8_000_000)
    make(now, firm=big, cost=1_000_000)

    firms = summary(now)["by_firm"]

    assert [f["firm_id"] for f in firms] == [str(big), str(small)]
    assert firms[0]["calls"] == 2


def test_the_budget_bar_and_the_over_budget_flag(settings):
    settings.LLM_MONTHLY_BUDGET_USD = 5
    now = timezone.now()
    make(now, cost=6_000_000)

    result = summary(now)

    assert result["budget_used_percent"] == 100 and result["budget_over"] is True


def test_no_budget_means_no_bar(settings):
    settings.LLM_MONTHLY_BUDGET_USD = 0

    assert summary()["budget_used_percent"] is None


def test_unpriced_calls_are_counted_so_zero_is_never_mistaken_for_free():
    now = timezone.now()
    event = make(now, cost=0)
    event.priced = False
    event.save()

    assert summary(now)["month"]["unpriced"] == 1


# -- the page ----------------------------------------------------------------------------------------------------------


def test_the_platform_owner_can_open_the_usage_page_and_sees_the_summary():
    operator = User.objects.create_user(
        email="op@example.test", password="x" * 20, is_superuser=True, is_staff=True
    )
    make(timezone.now(), cost=1_500_000)

    response = sign_in(operator).get("/admin/usage/usageevent/")

    assert response.status_code == 200
    assert "Model spend" in response.content.decode()


def test_nothing_on_the_usage_page_can_be_added_changed_or_deleted():
    from django.contrib import admin

    model_admin = admin.site._registry[UsageEvent]
    request = SimpleNamespace()

    assert not model_admin.has_add_permission(request)
    assert not model_admin.has_change_permission(request)
    assert not model_admin.has_delete_permission(request)


# -- how the page shows its figures ------------------------------------------------------------------------------------


def test_figures_are_shown_as_short_plain_strings():
    from usage.summary import compact, money_inr, money_usd

    assert (compact(999), compact(12_345), compact(4_500_000)) == ("999", "12.3k", "4.5M")
    assert (money_usd(0), money_usd(Decimal("0.0123")), money_usd(Decimal("1234.5"))) == (
        "$0.00",
        "$0.0123",
        "$1,234.50",
    )
    assert money_inr(Decimal("165.6")) == "₹165.60"


def test_the_chart_is_empty_until_something_is_spent_and_then_draws_a_bar_a_day():
    from usage.summary import build_chart

    day = datetime.date(2026, 10, 1)
    quiet = [
        {
            "date": day + datetime.timedelta(days=i),
            "calls": 0,
            "cost_micro": 0,
            "cost_usd": Decimal(0),
        }
        for i in range(30)
    ]
    assert build_chart(quiet)["empty"] is True

    quiet[29] = {**quiet[29], "calls": 4, "cost_micro": 2_000_000, "cost_usd": Decimal(2)}
    chart = build_chart(quiet)
    assert chart["empty"] is False and len(chart["bars"]) == 30
    assert (
        chart["bars"][29]["is_last"]
        and float(chart["bars"][29]["h"]) > float(chart["bars"][0]["h"]) == 0
    )


def test_the_summary_carries_the_display_strings_the_template_uses():
    now = timezone.now()
    make(now, cost=2_000_000)

    result = summary(now)

    assert result["month"]["l"]["usd"] == "$2.00" and result["today"]["l"]["calls"] == "1"
    assert result["chart"]["empty"] is False


def test_the_page_has_its_stylesheet():
    from django.contrib.staticfiles import finders

    assert finders.find("usage/usage.css")
