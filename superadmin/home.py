"""What the platform owner's home page shows: numbers, what needs doing, every firm, spend and recent activity.

Pure data. It reads only the gated platform models (``PlatformFirmStats``, ``PlatformInvite``, ``PlatformJob``) and the spend
estimate the dashboard list already uses, and returns plain dataclasses; the template does the HTML. Nothing a firm wrote is
read here: counts, dates, names of firms and money only.
"""

from __future__ import annotations

import datetime
from dataclasses import dataclass, field
from urllib.parse import quote

from django.urls import reverse
from django.utils import timezone

from superadmin.admin import QUIET_DAYS, TRIAL_WARNING_DAYS, _spend_by_firm
from superadmin.models import PlatformFirmStats, PlatformInvite, PlatformJob

ROW_LIMIT = 100
INVITE_STUCK_DAYS = 7
ACTIVITY_DAYS = 14
ACTIVITY_SHOWN = 8
TABS = ("all", "attention", "trial", "healthy")


@dataclass
class Kpi:
    label: str
    value: str
    note: str = ""
    warn: bool = False


@dataclass
class Attention:
    firm_id: str
    firm_name: str
    tone: str  # bad, warn, mute
    what: str
    age_days: int
    action_label: str
    action_url: str


@dataclass
class FirmRow:
    firm_id: str
    name: str
    people_text: str
    people_pct: int | None
    people_state: str  # "", near or full: picks the bar colour
    clients_text: str
    clients_pct: int | None
    clients_state: str
    statements: int
    last_seen: str
    spend_text: str
    status: str
    tone: str  # good, warn, bad, info, mute
    url: str
    needs_attention: bool
    on_trial: bool


@dataclass
class SpendBar:
    name: str
    text: str
    pct: int


@dataclass
class ActivityItem:
    when: datetime.datetime
    time_text: str
    text: str


@dataclass
class Home:
    kpis: list[Kpi] = field(default_factory=list)
    attention: list[Attention] = field(default_factory=list)
    rows: list[FirmRow] = field(default_factory=list)
    total_firms: int = 0
    shown_firms: int = 0
    tab: str = "all"
    tab_counts: dict[str, int] = field(default_factory=dict)
    spend: list[SpendBar] = field(default_factory=list)
    activity: list[ActivityItem] = field(default_factory=list)


def rupees(amount) -> str:
    return f"Rs {int(round(amount)):,}"


def _pct(used: int, limit: int | None) -> int | None:
    if not limit:
        return None
    return min(100, round(used / limit * 100) // 5 * 5)


def _state(used: int, limit: int | None) -> str:
    if not limit:
        return ""
    if used >= limit:
        return "full"
    return "near" if used / limit >= 0.8 else ""


def _ago(then, now) -> str:
    if then is None:
        return "never"
    days = (now - then).days
    return "today" if days <= 0 else f"{days} day{'s' if days != 1 else ''} ago"


def _days(delta: datetime.timedelta) -> int:
    return max(0, delta.days)


def _firm_url(firm_id) -> str:
    return reverse("admin:superadmin_platformfirm_change", args=[firm_id])


def _invites_url(name: str) -> str:
    return reverse("admin:superadmin_platforminvite_changelist") + "?q=" + quote(name)


def _jobs_url(name: str) -> str:
    return reverse("admin:superadmin_platformjob_changelist") + "?q=" + quote(name)


def _attention_for(firm, stuck_invite: PlatformInvite | None, now) -> list[Attention]:
    items: list[Attention] = []
    fid, name = str(firm.pk), firm.name
    if not firm.is_active:
        return items
    if firm.trial_ends_at is not None and firm.trial_ends_at < now:
        ago = _days(now - firm.trial_ends_at)
        items.append(Attention(fid, name, "bad", f"Trial ended {ago} day{'s' if ago != 1 else ''} ago and the firm is still in service.", ago, "Extend trial", _firm_url(fid)))
    if firm.failed_jobs_30d:
        n = firm.failed_jobs_30d
        items.append(Attention(fid, name, "bad", f"{n} job{'s' if n != 1 else ''} failed in the last 30 days.", 0, "Open jobs", _jobs_url(name)))
    if stuck_invite is not None:
        age = _days(now - stuck_invite.created_at)
        items.append(Attention(fid, name, "warn", "The owner has not opened the invitation link.", age, "New link", _firm_url(fid)))
    if firm.max_members and firm.active_members + firm.pending_invites >= firm.max_members:
        taken = firm.active_members + firm.pending_invites
        items.append(Attention(fid, name, "warn", f"At its people limit ({taken} of {firm.max_members}); the next invitation will be refused.", 0, "Raise limit", _firm_url(fid)))
    if firm.max_clients and firm.clients >= firm.max_clients:
        items.append(Attention(fid, name, "warn", f"At its client limit ({firm.clients} of {firm.max_clients}).", 0, "Raise limit", _firm_url(fid)))
    quiet_since = now - datetime.timedelta(days=QUIET_DAYS)
    quiet = firm.created_at < quiet_since and (firm.last_activity is None or firm.last_activity < quiet_since)
    if quiet and stuck_invite is None:
        age = _days(now - (firm.last_activity or firm.created_at))
        items.append(Attention(fid, name, "mute", f"No activity for {age} days.", age, "Check in", _firm_url(fid)))
    return items


def _status(firm, attention: list[Attention], now) -> tuple[str, str]:
    if not firm.is_active:
        return "Switched off", "mute"
    for item in attention:
        if item.action_label == "Open jobs":
            return f"{firm.failed_jobs_30d} failed job{'s' if firm.failed_jobs_30d != 1 else ''}", "bad"
    for item in attention:
        if item.action_label == "Extend trial":
            return "Trial ended", "bad"
    for item in attention:
        if item.action_label == "New link":
            return "Invite waiting", "warn"
    for item in attention:
        if item.action_label == "Raise limit":
            return "At limit", "warn"
    for item in attention:
        if item.action_label == "Check in":
            return "Quiet", "mute"
    if firm.trial_ends_at is not None and firm.trial_ends_at < now + datetime.timedelta(days=TRIAL_WARNING_DAYS):
        left = _days(firm.trial_ends_at - now)
        return f"Trial, {left} day{'s' if left != 1 else ''} left", "info"
    return "Active", "good"


def _time_text(when, now) -> str:
    local = timezone.localtime(when)
    if (now - when) < datetime.timedelta(days=1) and timezone.localtime(now).date() == local.date():
        return local.strftime("%H:%M")
    return local.strftime("%d %b").lstrip("0")


def _activity(now, firms, invites, jobs) -> list[ActivityItem]:
    since = now - datetime.timedelta(days=ACTIVITY_DAYS)
    events: list[tuple[datetime.datetime, str]] = []
    for f in firms:
        if f.created_at >= since:
            events.append((f.created_at, f"{f.name} was added."))
    for i in invites:
        if i.created_at >= since:
            events.append((i.created_at, f"An invitation was sent to {i.firm_name}."))
        if i.used_at is not None and i.used_at >= since:
            events.append((i.used_at, f"A person joined {i.firm_name}."))
    for j in jobs:
        events.append((j.created_at, f"A job failed for {j.firm_name}."))
    events.sort(key=lambda e: e[0], reverse=True)
    return [ActivityItem(w, _time_text(w, now), text) for w, text in events[:ACTIVITY_SHOWN]]


def build_home(now: datetime.datetime | None = None, tab: str = "all") -> Home:
    from usage.pricing import inr

    now = now or timezone.now()
    tab = tab if tab in TABS else "all"
    firms = list(PlatformFirmStats.objects.order_by("name"))
    stuck_before = now - datetime.timedelta(days=INVITE_STUCK_DAYS)
    stuck = {
        str(i.firm_id): i
        for i in PlatformInvite.objects.filter(state="pending", make_owner=True, created_at__lte=stuck_before).order_by("-created_at")
    }
    spend = {k: inr(v) for k, v in _spend_by_firm().items()}

    home = Home(tab=tab, total_firms=len(firms))
    all_rows: list[FirmRow] = []
    for firm in firms:
        fid = str(firm.pk)
        items = _attention_for(firm, stuck.get(fid) if firm.active_members == 0 else None, now)
        home.attention.extend(items)
        status, tone = _status(firm, items, now)
        all_rows.append(
            FirmRow(
                firm_id=fid,
                name=firm.name,
                people_text=f"{firm.active_members} of {firm.max_members}" if firm.max_members else str(firm.active_members),
                people_pct=_pct(firm.active_members, firm.max_members),
                people_state=_state(firm.active_members, firm.max_members),
                clients_text=f"{firm.clients} of {firm.max_clients}" if firm.max_clients else str(firm.clients),
                clients_pct=_pct(firm.clients, firm.max_clients),
                clients_state=_state(firm.clients, firm.max_clients),
                statements=firm.statements_this_month,
                last_seen=_ago(firm.last_activity, now),
                spend_text=rupees(spend[fid]) if spend.get(fid) else "-",
                status=status,
                tone=tone,
                url=_firm_url(fid),
                needs_attention=bool(items),
                on_trial=firm.trial_ends_at is not None,
            )
        )
    home.attention.sort(key=lambda a: a.age_days, reverse=True)

    home.tab_counts = {
        "all": len(all_rows),
        "attention": sum(r.needs_attention for r in all_rows),
        "trial": sum(r.on_trial for r in all_rows),
        "healthy": sum(r.tone == "good" for r in all_rows),
    }
    keep = {
        "all": lambda r: True,
        "attention": lambda r: r.needs_attention,
        "trial": lambda r: r.on_trial,
        "healthy": lambda r: r.tone == "good",
    }[tab]
    selected = [r for r in all_rows if keep(r)]
    home.shown_firms = len(selected)
    home.rows = selected[:ROW_LIMIT]

    week_ago = now - datetime.timedelta(days=7)
    new_firms = sum(1 for f in firms if f.created_at >= week_ago)
    total_spend = sum(spend.values()) if spend else 0
    over_week = sum(1 for a in home.attention if a.age_days >= 7)
    home.kpis = [
        Kpi("Firms", str(len(firms)), f"{new_firms} new this week" if new_firms else ""),
        Kpi("People", str(sum(f.active_members for f in firms))),
        Kpi("Statements this month", str(sum(f.statements_this_month for f in firms))),
        Kpi("Model spend, 30 days", rupees(total_spend) if total_spend else "-"),
        Kpi("Need you today", str(len(home.attention)), f"{over_week} over a week old" if over_week else "", warn=bool(home.attention)),
    ]

    ranked = sorted(((f.name, spend[str(f.pk)]) for f in firms if spend.get(str(f.pk))), key=lambda p: p[1], reverse=True)[:5]
    top = ranked[0][1] if ranked else 0
    home.spend = [SpendBar(n, rupees(v), round(v / top * 100) // 5 * 5) for n, v in ranked]

    invites = list(PlatformInvite.objects.filter(created_at__gte=now - datetime.timedelta(days=ACTIVITY_DAYS)))
    invites += list(PlatformInvite.objects.filter(used_at__gte=now - datetime.timedelta(days=ACTIVITY_DAYS)).exclude(pk__in=[i.pk for i in invites]))
    jobs = list(PlatformJob.objects.filter(status="FAILED", created_at__gte=now - datetime.timedelta(days=ACTIVITY_DAYS))[:ACTIVITY_SHOWN])
    home.activity = _activity(now, firms, invites, jobs)
    return home
