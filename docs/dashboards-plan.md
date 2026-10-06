# AutoCA dashboards: layout proposal (planning only, nothing built)

## 0. What I read

- References: `analytics.webp` (dark; hero multi-line chart, three ranked tables, gauge-donut with legend rows of count and %), `sales.webp` (pastel, decorative dot-matrix chart, "16/30 finished tasks" tile), `staff.webp` (four big KPIs, bar+line combo, donut, top-5 bars, detail table with inline bars).
- Existing: `styles.css` tokens (ivory/graphite, emerald `--primary`, champagne `--accent*` = "a person must look", red only for non-tallying/failed, green only for finished/matching, `--info` blue); `StatCard`/`StatGrid`, `Card`, `PeriodPicker` (in features/work, `lib/period.ts`), `DataTable`, `Badge`, `EmptyState`/`ErrorState`, `FinancialSnapshot` (hand-rolled `MonthBars`), `MeasuredFigures`, `PortfolioView`, `DashboardScreen` (tabs Portfolio / Operations, today).
- Endpoints in use: `GET /firm/portfolio/`, `/firm/metrics/?from&to` (firm, clients, turnaround), `/clients/:id/dashboard/?fy=` (snapshot), `firmOverview`, `teamEvents`.
- **`recharts` is not in `web/package.json`.** The decision is made, but installing a dependency needs the user's explicit OK (frontend-dev rule). Step 0 of the build order is that approval. Bundle note: import per-chart and lazy-load the chart module (`React.lazy`) so the login and clients screens do not pay for it.

## 1. What to copy, what to refuse (clashes with this app)

| Reference trait | Verdict |
|---|---|
| One hero chart, four KPIs, question-titled cards | Copy. |
| Donut + legend rows with count and % (analytics, staff) | Copy; the legend rows ARE the accessible data. |
| Ranked rows with inline bar; table with inline progress bars | Copy. |
| Three or four saturated series colours (analytics lines, staff teal/green/yellow) | Refuse. Max two series colours per chart: `--primary` (done / good) and `--accent-foreground` champagne (needs a person). Red only for "does not tally / overdue / failed", as the palette comment in `styles.css` says. Others become neutral ink tints (`--muted-foreground`, `--border`). |
| Rainbow per-category donut slices | Refuse. Use one hue stepped in lightness plus patterned/labelled legend; the slices are states (done / waiting on us / waiting on client) so colour carries meaning once. |
| Gauge/half-donut (sales, analytics) | Refuse. Hard to read, can't be done accessibly; use a full donut or a progress bar. |
| Dot-matrix, world map, gradient mesh, glass cards, avatars (sales.webp) | Refuse. Decorative, no information; AutoCA cards are flat with a 1px warm edge, no shadow. |
| Dark-only canvas (analytics) | Refuse; tokens drive both themes. |
| "Top 5 users with highest idle time" and ranked leaderboards by person (staff.webp) | Refuse for people. Per-person rows are alphabetical or by "needs a look", never ranked by output, never a score, no "top"/"best". Ranked bars are fine for CLIENTS and EXPENSE HEADS, not for people. |
| Western grouping and `$` / `K` / `M` (analytics, sales) | Refuse. Money via `formatCompact` (lakh/crore) with `formatPaise` in the title; dates DD-MM-YYYY; FY April to March; weekly bucket labels as "6 Oct". |
| "Create Report" primary button, Aggregate/Individual toggle | Not needed. |
| Icon-in-a-tile on KPIs (staff.webp) | Skip; label + number is cleaner and our `StatCard` has no icons. |
| Pagination-free long tables inside cards | Our `DataTable` already has sort + priority columns; reuse it. |
| Seconds/idle-time framing | Not applicable; also avoid anything that reads as surveillance of staff. |

## 2. Principles applied to all four

1. Top-left is the reader's question as the page `h1` subtitle, answered in one sentence in plain words ("3 clients need you today").
2. Row 1 = four KPIs (`StatCard`, 28px figure). Row 2 = one hero. Rows below = question-titled cards. Max 8 cards above the fold on a 1440 laptop; the rest is "More" below.
3. Every card title is a question or a plain noun phrase a business owner would say. No jargon in titles ("Unresolved" becomes "Entries not yet placed in a ledger").
4. Every number is a link to the screen that lists exactly those items (filters pass via `search`).
5. One period picker per page (top right), reused by every card; per-card pickers are banned. Default "This month". Period applies to flows (finished, received); stock figures (open now, overdue now) say "right now" and ignore it, and the card says so.
6. A comparison line on every KPI: "vs last month" (flows) or "since yesterday" (stock) with an arrow glyph AND words; direction colour only when direction has meaning (more overdue = red, more finished = green; neutral count changes stay ink).
7. Empty state text is written per card (below), never a blank chart.
8. All figures are server-computed integers/paise; the client never sums `*_display` strings and never uses floats on paise. Percentages are computed from integer counts with one rounding function in `lib/`.

Grid: 12 columns, gap `gap-4` (16px), page padding existing. Cards `p-5`. Phone (<640px): one column; KPI row becomes 2x2; hero chart keeps full width at 220px tall with fewer ticks; tables use `DataTable` priority columns (hide low priority, as `PortfolioView` already does); donut stacks above its legend.

---

## 3. Dashboard A: Owner (FIRM_ADMIN)

**(a) Question:** "Is my firm on track, who is carrying what, and which clients are in trouble?"

**(b) Wireframe (desktop, 12 col)**

```
 Dashboard                                         [This month v] [Last month][This FY][Custom]
 Your firm, 6 Oct 2026 · 41 clients · 9 people
+---------------+---------------+---------------+---------------+
| A1 Clients    | A2 Work done  | A3 Waiting on | A4 Overdue    |   3 cols each
|  on track     |  this month   |  someone      |  right now    |
|  31 of 41     |  412 entries  |  118 items    |  14 items     |
| +2 vs last mo |  +9% vs last  |  -6 vs last wk|  +3 vs last wk|
+---------------+---------------+---------------+---------------+
+------------------------------------------------------------+---------------------------+
| A5 Is work being finished as fast as it arrives?     (8)   | A6 Where are the client   |
|   hero: weekly bars RECEIVED vs line FINISHED, 12 weeks    |    books today?  (4)      |
|   (two series: ink-grey bars, emerald line)                |   donut + legend rows:    |
|                                                            |   Signed off   9   22%    |
|                                                            |   In review   11   27%    |
|                                                            |   Being worked 14  34%    |
|                                                            |   Not started  7   17%    |
+------------------------------------+-----------------------+---------------------------+
| A7 What does each person have on?  (7)                      | A8 Which clients need me   |
|  ProgressTable: Person | Assigned | Open | Done this period | |    first?  (5)             |
|  | Overdue | Waiting on others | [done / (done+open) bar]   |  ranked rows, inline bars  |
|  alphabetical, sortable, no rank, no total score           |  (by overdue + blocked)    |
|                                                            |  Acme Traders  7 overdue   |
+------------------------------------------------------------+---------------------------+
| A9 What falls due in the next 30 days? (6)  | A10 Money the firm's clients are owed / owe (6)|
|  list of Deadline rows w/ date, client      |  receivables vs payables, aging bars, top 5   |
+---------------------------------------------+------------------------------------------------+
```

Below 1024px: A5 and A6 stack; A7 and A8 stack; A9 and A10 stack. Phone: A1..A4 2x2, then A5, A6, A8, A7 (the "who needs me" list before the people table), A9, A10.

**(c) Cards**

| Id | Title | Headline | Comparison | Chart | Click-through | Empty state |
|---|---|---|---|---|---|---|
| A1 | Clients with books on track | "31 of 41" | "2 more than last month" | none (number + thin progress bar `31/41`) | `/clients?health=on_track` | "No clients yet. Add a client and upload its bank statement." (CTA if `client.create`) |
| A2 | Entries finished this period | count of entries posted+approved in range | "+9% vs the same days last month" | none | `/pipeline?done=period` | "Nothing finished in this period yet." |
| A3 | Items waiting on someone | open items not overdue (waiting on client, waiting on approval, waiting to be sealed) | "6 fewer than a week ago" | none; note shows split "58 on clients, 40 to approve, 20 to seal" | `/pipeline?waiting` | "Nothing is waiting. Every queue is clear." |
| A4 | Overdue right now | overdue items (seal date passed, months missing past schedule, TDS undeposited past due) | "3 more than a week ago" | none; tone attention when > 0 | `/clients?overdue=1` | "Nothing is overdue." |
| A5 | Is work being finished as fast as it arrives? | "Finished 412, received 388 in 12 weeks" | text line: "You are clearing more than arrives" / "A backlog is building" (derived from the two sums, words not colour) | Recharts `ComposedChart`: `Bar` received (muted ink), `Line` finished (`--primary`); weekly x-axis DD Mon; y integer ticks | click a week bar opens `/pipeline?week=2026-09-29` | "No work received yet in this period." |
| A6 | Where are my clients' books today? | "9 of 41 fully signed off" | "up 2 since last month" | `Pie` donut, 4 states, legend rows count + % | each legend row to `/clients?stage=...` | same as A1 |
| A7 | What does each person have on? | rows = people | per row facts only | `ProgressTable` with inline `done/(done+open)` bar (no colour judgement; bar is primary tint) | row opens `/team/:memberId` (a person's own factual page; see section 8) or `/pipeline?person=` | "Nobody has been assigned work yet." |
| A8 | Which clients need me first? | top 8 rows | per row "7 overdue, 2 blocked" | `RankedBars` horizontal; bar length = number of overdue + blocked items | row to `/clients/:id` | "No client needs attention. Good." |
| A9 | What falls due in the next 30 days? | count | "next: GSTR-3B, 20-10-2026, 6 clients" | list (no chart) | `/clients/:id/tds` or gst | "Nothing falls due in the next 30 days." |
| A10 | What clients are owed and owe | receivables, payables | aging split | `RankedBars` stacked 0-30/31-60/60+ days (one hue stepped, label values) | `/reports/aging` per client | "No invoices or bills posted yet." |

**(d) New backend data (owner)**
- A1, A6: exists (`by_stage`, portfolio health). Needs a rule "on track" = `stage` not blocked and no overdue; today derivable client-side from `PortfolioClient`; better server-side so one definition exists.
- A2, A5: NEW `weekly_flow` series `[{week_start, received, finished}]` for the firm (received = statement rows uploaded; finished = entries approved; from `approved_at` and upload timestamps) plus period totals with prior-period totals.
- A3, A4: partly exists (open items, seal due, TDS overdue). NEW comparison values ("a week ago") need a daily snapshot table or can be omitted; **recommend omitting the "vs last week" for stock figures in v1** and showing only the split. Say so in the note, do not fake it.
- A7: NEW `people` array: `{member_id, name, role, assigned_clients, open_items, finished_in_period, overdue, waiting_on_others}`. Existing `turnaround` per person is reused as an optional column "Typical turnaround (days)" only inside the person page, not here.
- A8: exists (`attention` in portfolio).
- A9: exists (`deadlines`).
- A10: exists per client; NEW firm roll-up (sum + aging buckets, top 5 clients). Gated by `journal.view` like the portfolio.

---

## 4. Dashboard B: Senior CA

**(a) Question:** "What do I have to approve or seal today, and which of my clients are at risk?"

**(b) Wireframe**

```
 Dashboard                                         [This month v]
 Your team, 6 Oct 2026 · 12 clients · 3 people
+---------------+---------------+---------------+---------------+
| B1 Waiting for| B2 Ready to   | B3 At risk    | B4 Finished   |
|  my approval  |  seal         |  right now    |  this month   |
|  23 entries   |  4 clients    |  5 clients    |  96 entries   |
+---------------+---------------+---------------+---------------+
+----------------------------------------+-------------------------------------------+
| B5 What is waiting on me?  (7)         | B6 Is my team keeping up?  (5)            |
|  action list, grouped:                 |  hero: weekly received vs finished (team) |
|   Approve entries - Acme (9), ...      |  (same chart as A5, scoped to my team)    |
|   Seal books - Rao & Sons, ...         |                                           |
|  each row = a button to the work       |                                           |
+----------------------------------------+------------------+------------------------+
| B7 Which clients are at risk and why? (7)                 | B8 Where are my clients' |
|  RankedBars: client, reasons as text chips                |    books? (5) donut +    |
|  ("2 months missing", "3 checks failing", "seal late")    |    legend                |
+-----------------------------------------------------------+--------------------------+
| B9 What is each person on my team doing? (12)                                         |
|  ProgressTable (same as A7, scoped)                                                   |
+---------------------------------------------------------------------------------------+
```

Hero is B5, not a chart: a Senior's day is a queue. The chart is secondary (B6). That deliberately departs from "hero time-series first"; justified because the reader's question is an action list.

**(c) Cards**

| Id | Title | Headline | Comparison | Chart | Click-through | Empty state |
|---|---|---|---|---|---|---|
| B1 | Entries waiting for my approval | count | "oldest has waited 4 days" | none | `/pipeline?stage=approval` | "Nothing waits for your approval." |
| B2 | Books ready to seal | clients where seal conditions are met | "next seal date 15-10-2026" | none | `/clients?ready=seal` | "No books are ready to seal yet." |
| B3 | Clients at risk | clients with failing controls, missing months or overdue seal | "of 12" | none, tone attention | `/clients?risk=1` | "No client is at risk." |
| B4 | Entries finished this period | count | vs last period | none | `/pipeline?done=period` | "Nothing finished yet." |
| B5 | What is waiting on me? | list of up to 8 actions | "+ 11 more" link | grouped list, button per row (Approve / Seal / Review) | each row to the exact screen via `nextTarget()` | "Nothing is waiting on you. Next seal due 15-10-2026." |
| B6 | Is my team keeping up? | "Finished 96, received 88" | words as A5 | `ComposedChart` as A5 | `/pipeline?team=mine` | "No work received yet." |
| B7 | Which clients are at risk and why? | up to 8 | reasons text | `RankedBars` + reason text (not colour only) | `/clients/:id/close` | "None at risk." |
| B8 | Where are my clients' books? | "3 of 12 signed off" | | donut | per row to `/clients?stage=` | "No clients assigned to you or your team." |
| B9 | What is each person on my team doing? | table | facts only | `ProgressTable` | row to person page | "No one is on your team yet. Add people in Team." |

**(d) New backend data:** B1 oldest-waiting age (new field: min `submitted_at` of pending approvals), B2 "ready to seal" flag (exists as rule in `core/access.py`/close report; needs exposing per client), B3 derivable from portfolio scoped by team (scoping must be server-side by lead/assignments: `GET /firm/portfolio/` already filters by role, confirm; ask backend-dev), B6 and B9 need the same `weekly_flow` and `people` endpoints as Owner with a `scope=team` filter. Everything else exists.

---

## 5. Dashboard C: Staff

**(a) Question:** "What do I do next, and how am I doing against what I was given?"

**(b) Wireframe**

```
 Dashboard                                         [This week v]
 Good morning, Meera · Tuesday 6 Oct 2026
+---------------+---------------+---------------+---------------+
| C1 Assigned   | C2 Still open | C3 Overdue    | C4 Finished   |
|  to me        |   now         |   (red if >0) |  this week    |
|  34 entries   |   19          |   3           |   15          |
+---------------+---------------+---------------+---------------+
+--------------------------------------------+------------------------------------------+
| C5 What should I do next?   (8)  HERO LIST | C6 How much of my work is done? (4)       |
|  1. Acme: place 9 entries in a ledger  [Go]|   donut or single big bar:                |
|  2. Rao: upload March statement        [Go]|   Done 15 / Open 19 / Waiting 4          |
|  3. ...                                    |   "44% of what you were given"            |
+--------------------------------------------+------------------------------------------+
| C7 How much did I finish each day? (7)        | C8 My clients (5)                      |
|  hero-ish: daily bars for the period, one hue | list: client, my open count, inline bar|
+-----------------------------------------------+----------------------------------------+
```

Phone: C1..C4 2x2, C5 first (the task list is the product), then C6, C8, C7.

**(c) Cards**

| Id | Title | Headline | Comparison | Chart | Click-through | Empty state |
|---|---|---|---|---|---|---|
| C1 | Work given to me | assigned entries/steps | "5 new since Monday" | none | `/work/mine` | "Nothing has been assigned to you yet. Ask your Senior CA." |
| C2 | Still to do | open now | "9 are due this week" | none | `/work/mine?open` | "You are all caught up." |
| C3 | Overdue | overdue now | "oldest is 3 days late" | none, tone attention | `/work/mine?overdue` | "Nothing is overdue." |
| C4 | Finished this period | finished in range | vs previous period, words only | none | `/work/mine?done` | "You have not finished anything yet this week." |
| C5 | What should I do next? | next 5 tasks, ordered overdue first then due date | none | action list; each row = client, task in plain words, due date, Go button via `nextTarget` | the exact screen | "Nothing to do. Check back after your Senior CA assigns work." |
| C6 | How much of my work is done? | "44%" computed from integer counts | "15 of 34" | single-ring donut (done vs open vs waiting) + legend rows with count and % | `/work/mine` | "No work assigned, so there is nothing to measure." |
| C7 | How much did I finish each day? | total | "best day Thu 6" is NOT shown (no ranking of days either, keep it plain) | bars by day, one colour | none | "Nothing finished in this period." |
| C8 | My clients | rows | open count per client | `RankedBars` (inline bar = open items), sorted by due date not by size | `/clients/:id` | "You are not assigned to any client." |

**(d) New backend data:** Staff has no personal-metrics endpoint today (firm metrics are 403 for staff). NEW `GET /me/work/?from&to` returning `{assigned, open, overdue, waiting, finished, daily:[{date, finished}], next_tasks:[...], clients:[{id, name, open}]}`. This is the only dashboard that needs everything new; "assigned" must be defined once (client assignment => items on it). C5 can ship earlier from existing per-client `next_step` filtered to assigned clients.

---

## 6. Dashboard D: Client page (`ClientOverview.tsx`), for the business owner

**(a) Question:** "Are my books up to date, what is still pending, and how is my business doing?"

Language rule: no "unresolved", "ledger", "Dr/Cr" in titles. "Entries not yet sorted into accounts", "Entries waiting for sign-off". Accountant-only terms stay in the detail screens the cards link to.

**(b) Wireframe**

```
 Acme Traders · FY 2026-27 [FY v]            Books: In review · Lead: R. Iyer
+---------------------------------------------------------------------------------+
| D1 How complete are my books?  (12)  one wide progress card                      |
|  ============================------------  7 of 12 months done (58%)            |
|  Apr May Jun Jul Aug Sep | Oct Nov Dec Jan Feb Mar   (month strip, state in text) |
|  Next step: "Confirm opening balances"  [Open]      Still missing: Sep           |
+---------------+---------------+---------------+---------------+
| D2 Money in   | D3 Money out  | D4 Profit /   | D5 Tax to pay |
|  this year    |  this year    |     Loss      |  (TDS, GST)   |
+---------------+---------------+---------------+---------------+
+-------------------------------------------------+-------------------------------+
| D6 How has money moved month by month?   (8)    | D7 What is left to do? (4)    |
|  income bars vs expense bars, 12 FY months      |  checklist w/ counts:         |
|                                                 |  23 entries to sort           |
|                                                 |  9 waiting for sign-off       |
|                                                 |  Sign-off by senior: pending  |
+----------------------------+--------------------+-------------------------------+
| D8 Who owes me / whom do I owe? (4)  | D9 Where is my money? (4) | D10 Biggest costs (4) |
|  receivable vs payable, top 3        | bank, card, loan balances | RankedBars top 5 heads |
+--------------------------------------+---------------------------+----------------+
| D11 Which reports can I open? (12) tiles: Profit & Loss, Balance Sheet, Trial        |
|  Balance, Receivables, Payables, TDS, GST; each tile "Ready" / "Not ready: why"      |
+---------------------------------------------------------------------------------------+
```

Phone: D1 first, KPIs 2x2, D7 before D6 (what to do before history), D8..D10 one column, reports as a 2-column tile grid.

**(c) Cards**

| Id | Title | Headline | Comparison | Chart | Click-through | Empty state |
|---|---|---|---|---|---|---|
| D1 | How complete are my books? | "58% done" = months complete / months elapsed in FY (integers) | "5 months still to do" | segmented progress bar + 12-month strip (each month icon+letter: done / partial / missing, not colour only; existing `COVER_LABEL`) | next-step button via `nextTarget` | "No statements uploaded yet. Upload the first bank statement to begin." |
| D2 | Money in this year | `formatCompact(income)` | "x% more than last year" only if prior FY data exists | none | `/clients/:id/reports/income` | "Nothing has been posted yet." |
| D3 | Money out this year | expense | same | none | expense report | same |
| D4 | Profit (or Loss) | profit | "Income less expense" | none | P&L | same |
| D5 | Tax still to pay | TDS undeposited + GST payable | "due 20-10-2026" | none | `/tds` or `/gst` | "No tax is pending." |
| D6 | How has money moved month by month? | none (chart is the content) | text summary: "Best month Aug" is NOT used; use "Income was higher than expense in 8 of 12 months" | Recharts grouped `BarChart`, income `--success`, expense `--accent-foreground`, FY months Apr to Mar, axis in lakh | month bar to that month's Day Book | "Nothing has been posted in this year yet." (exists) |
| D7 | What is left to do? | total remaining | each line a count + link | checklist (reuse the step list in `ClientOverview`, reworded) | each row | "Nothing is left. Books are signed off to 31-03-2027." |
| D8 | Who owes me, and whom do I owe? | receivable / payable | overdue part in text | paired `RankedBars` top 3 each | aging report | "No unpaid bills or invoices." |
| D9 | Where is my money? | rows of balances | "owed" suffix on card/loan (exists) | list, no chart | account statement | "No bank account yet." |
| D10 | What do I spend the most on? | top 5 heads | % of total | `RankedBars` | expense head ledger | "No expenses posted yet." |
| D11 | Which reports can I open? | tiles | "Ready" or "Not ready yet: 2 months missing" | none | the report | "Reports appear once books are posted." |

**(d) New backend data:** D1 percent and months-complete exist (months missing, coverage); D2/D3 prior-FY comparison NEW optional (`prior_income_paise`, `prior_expense_paise`; if absent omit the line). D5 GST payable: check whether `ClientSnapshot` includes GST balance (the snapshot comment says yes). D11 "ready" flags NEW: a small `reports_ready:[{key, ready, reason}]` derived from close report; a v1 can show all tiles as links with no readiness. Everything else exists in `ClientSnapshot` and `ClientOverview`.

---

## 7. Shared components (all under `src/components/charts/` or `components/ca/`, tokens only)

| Component | Props | Notes |
|---|---|---|
| `KpiCard` | extend existing `StatCard`: add `delta?: {text: string; direction: 'up'\|'down'\|'flat'; good?: boolean\|null}`, `progress?: {value: number; max: number}` | Do not create a second card. Delta renders arrow glyph + words ("up 9% from last month"); colour only when `good` is non-null. |
| `DashCard` | `{title: string; hint?: string; action?: ReactNode; to?: string; children; state: 'ready'\|'loading'\|'error'\|'empty'; empty: ReactNode; onRetry}` | Wraps `Card`; renders the title as `h2` (`CardTitle`), a "See all" link in the header, and the four states so each card handles its own failure (one failing query never blanks the page). |
| `PeriodPicker` | existing one, moved to `components/ca/`; add presets "This week" (staff), keep the four | Page-level, state in the URL search (`?period=&from=&to=`) so a link reproduces the view and the back button works. |
| `DonutLegend` | `{rows: {key, label, count, tone, to?}[]; total; centerLabel; centerValue}` | Recharts `PieChart`/`Pie` (innerRadius 62%, `paddingAngle` 2, `isAnimationActive={false}`). Legend is real HTML rows beside the chart: swatch + label + count + `%`; each row a link when `to`. Centre text is an SVG-free HTML overlay. Percent from one `pct(count,total)` in `lib/`, largest-remainder rounding so rows sum to 100. |
| `RankedBars` | `{rows: {key, label, value, valueLabel, note?, to?, tone?}[]; max?}` | NOT Recharts: plain `div` with `style={{width}}` bars is lighter, wraps text, links, and prints. Bar track `--muted`, fill `--primary` (or `--accent-foreground`). Value shown as text at row end. |
| `ProgressTable` | wraps existing `DataTable` columns + `progressColumn({done, open})` | Inline bar is `div role="img" aria-label="15 done of 34 given"` and the numbers are real cells next to it. Sort default alphabetical for people. |
| `FlowChart` (hero) | `{series: {week: string; received: number; finished: number}[]; onPick?}` | Recharts `ComposedChart` in `ResponsiveContainer`; see below. |
| `MonthBars` | `{trend: {month, income_paise, expense_paise}[]}` | Replace the hand-rolled one in `FinancialSnapshot` with Recharts `BarChart`; tooltip via `formatPaise`; y ticks via `formatCompact`. Values are paise integers, converted to rupees only for the axis scale (divide by 100 for pixel scaling only; label strings come from formatters). |
| `ActionList` | `{items: {key, title, client, due?, to, cta}[]; more?: number}` | The "what next" list (B5, C5). Keyboard: each row's button is the tab stop. |
| `ProgressBar` | `{value, max, label}` | Shared by D1, A1, tables. `role="progressbar"` with `aria-valuenow/max` and visible text. |
| `ChartTable` | `{caption, columns, rows}` visually hidden `<table class="sr-only">` | Mounted with every Recharts chart so screen readers get the data. |

**Recharts usage**
- Always `ResponsiveContainer width="100%" height={n}` inside a fixed-height wrapper; `isAnimationActive={false}` (no motion that explains nothing; also respects reduced-motion).
- Colours from CSS variables: pass `stroke="var(--primary)"`, `fill="var(--muted-foreground)"`; Recharts accepts CSS var strings in SVG attributes, so theme switching is automatic and there is no JS theme object. Grid lines `stroke="var(--border)"`, axis text `fill="var(--muted-foreground)"` at 12px with `className="num"` (tabular).
- Horizontal gridlines only, no vertical; no chart border; max 5 y ticks; y axis integer (`allowDecimals={false}`) for counts.
- Tooltip: custom `content` component styled as our popover (`bg-popover`, `shadow-float`), shows the full figure and period in words. Never the only way to read a value.
- Lazy chunk: `charts/index.ts` re-exports; each dashboard `lazy(() => import(...))` its chart cards, with a skeleton of the same height (no layout shift).

**Accessibility (WCAG 2.2 AA)**
- Each chart: `role="img"` on the wrapper with `aria-label` giving the conclusion ("Finished 412, received 388 over 12 weeks"), plus the `ChartTable` for data, plus the card's text comparison line.
- Never colour alone: legend rows carry labels and counts; deltas carry words; series differ by shape too (bars vs line; stripe pattern via `<pattern>` for the second donut state if two share a hue); status chips have text.
- Contrast: series colours must clear 3:1 against `--card` in both themes (graphics) and text 4.5:1. Emerald `--primary` and champagne `--accent-foreground` pass in the existing palette notes (`docs/design/redesign-r2.md` 2.1); re-measure the lightness steps of the donut hue in both themes with the dataviz skill's validator before shipping.
- Focus: whole `StatCard` is one link (existing); chart elements are not tab stops; interactive elements are the legend rows, bars-as-links in `RankedBars`, and buttons. Focus ring from `--ring`.
- Target size 24x24 minimum for row links and the Go buttons (`size="sm"` already is).
- Reduced motion: no animation anyway. Print: `no-print` on pickers; cards are flat so they print.
- Live regions: the 15-second auto-refresh of today's Operations tab must not announce; keep `aria-live` off for refreshes and only announce load and error.

**Theme tokens.** No new colour values in components. Add at most four chart tokens in `styles.css` as aliases (not new hues): `--chart-1: var(--primary)`, `--chart-2: var(--accent-foreground)`, `--chart-muted: var(--muted-foreground)`, `--chart-grid: var(--border)`, and a 3-step lightness ramp `--chart-seq-1..3` for the donut/aging (derived with `color-mix(in oklab, var(--primary) 100%/65%/35%, var(--card))`), so dark mode follows automatically. Both densities: card padding fixed, table row height from `--row-h`.

**Loading / error / empty**
- Per-card: `DashCard` shows a `skeleton` of the card's real height (existing `.skeleton` class), `aria-busy`, with an `sr-only` "Loading X" like `PortfolioView`.
- Error per card: `ErrorState` compact variant with "Try again"; a 403 (role not allowed) renders nothing for that card, not an error (like `firmMetrics` with `retry:false`).
- Partial data: KPIs render as soon as their own query resolves; the hero chart never blocks the KPI row.
- Stale-while-revalidate via TanStack Query `staleTime: 30_000`; query keys stay under `['clients', ...]` / `['firm', ...]` so existing invalidation after a post/seal refreshes dashboards.
- Money gating: figures that need `journal.view` render "—" with a short "Not available to your role" rather than hiding the card (same as the portfolio today).

**Role routing.** `/dashboard` renders `OwnerDashboard | SeniorDashboard | StaffDashboard` from `me.membership.role`; READ_ONLY gets the Owner layout minus A7 and anything that edits (all links already respect permissions). Keep the Operations tab's live queue view as a "Live queue" link on Owner and Senior (it is useful, but it should not be the landing). The `localStorage` tab choice goes away.

**People rules (all of A7, B9, person page).** Columns are only: Assigned clients, Open, Finished this period, Overdue, Waiting on others (plus "Typical turnaround, days" on the person page). Sorted by name. No score, rank, colour grading, "top/bottom", or percent-of-team. The inline bar is that person's own `finished / (finished + open)` and is labelled so. Add the sentence under the table: "Counts of work, not a rating of people." Overdue is a count in ink, red only if > 0 and only the number. Needs a one-line decision from the user: whether the Owner may see per-person tables on staff-initiated work at all (assumed yes; Staff never see other people's rows).

## 8. Backend summary (what to ask backend-dev for, in this order)

1. `GET /firm/work-flow/?from&to&scope=firm|team` returns `{totals:{received, finished, prev_received, prev_finished}, weekly:[{week_start, received, finished}]}`; scope enforced server-side by role.
2. `GET /firm/people/?from&to&scope` returns the people array (A7/B9) and `GET /me/work/?from&to` (C).
3. Portfolio additions: `health` (on_track/at_risk/overdue), `waiting_breakdown`, `ready_to_seal`, `oldest_pending_approval_days`, firm roll-up of receivables/payables with aging.
4. Client: `prior_income_paise/prior_expense_paise`, `reports_ready[]`.
5. Optional `/team/:memberId` person page (or a drawer) with the same five factual counts and the existing turnaround.
All additive, read-only, no migration expected (derive from timestamps and BooksEvent), so no **MIGRATION**; the contract changes are **CONTRACT CHANGE** notes and need `npm run gen:api`.

## 9. Build order (each ships alone)

0. Approval to add `recharts` (`npm i recharts`); chart tokens; `lib/pct.ts` + test; lazy chart wrapper; decide section 7 `PeriodPicker` move.
1. Shared kit, no screen change: `DashCard`, `ProgressBar`, `RankedBars`, `DonutLegend`, `ChartTable`, `StatCard.delta`; Vitest for `pct` rounding (sums to 100), delta wording, empty/zero cases. Look at each in both themes and 390px via `qa/tools/snap.mjs`.
2. **Client page (D)** first: all data exists; replace `MonthBars` with Recharts, add D1 progress, D7 reworded, D11 tiles (all-links v1). Lowest risk, highest customer-facing value.
3. **Owner (A), version 1** from existing data: A1, A4, A6, A8, A9, A10 (client roll-up client-side only if the API is unchanged), reusing portfolio. Ship with A2/A3/A5/A7 hidden.
4. Backend items 1 and 2; then Owner A2, A3, A5, A7 land.
5. **Senior (B)**: reuse Owner components with `scope=team`; B1/B2 need item 3.
6. **Staff (C)**: needs `/me/work/`; C5 can ship early from existing next steps.
7. Role router on `/dashboard`; retire the tab switch; retire `MeasuredFigures` duplicates or keep it under Reports.
8. Polish: print view, keyboard walkthrough, axe check on each, CA reviewer pass (lakh/crore, DD-MM-YYYY, FY labels, wording).

## 10. Open questions for the user

1. Approve adding `recharts` as a dependency?
2. Is a per-person table acceptable for owners and seniors (counts only, alphabetical)? Is the person page wanted?
3. Definition of "on track" and "at risk" for a client (proposal: at risk = missing month past schedule, failing control, or seal date passed; on track = none of those).
4. "Assigned" for staff: items on clients they are assigned to, or items assigned individually? Today only client assignments exist; the proposal uses client assignments.
5. Is dropping "vs last week" on stock figures (no history stored) acceptable for v1, or should a nightly snapshot table be added (that would be a MIGRATION)?
