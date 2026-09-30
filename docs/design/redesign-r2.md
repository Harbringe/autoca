# AutoCA redesign r2: the mockup as base, built on our stack

Status: design spec for `frontend-dev`. Written by the UX designer role, 30-09-2026.
Evidence: `web/qa/screenshots/r2-mock-*.png` (17 mockup pages + phone), `web/qa/screenshots/r2-ours-*.png` (12 of our screens).
Read time: about an hour. Sections 3 and 5 are the ones you build from; section 2 is the token file.

Ground rules that decide everything below:

1. The mockup is the look and the layout of the shell. Our API is the truth for content. Nothing on a page may show a number the API cannot back.
2. This is a re-theme plus a new shell, not a new stack. Tailwind v4 + shadcn-style components in `web/src/components/ui` stay; `web/src/styles.css` gets new tokens.
3. Every URL that works today keeps working (section 3.4).

---

## 1. The mockup, assessed

### 1.1 Keep

| Keep | Why |
|---|---|
| Palette: graphite chrome, ivory page, emerald action, champagne accent | Calm, warm, distinct from every blue SaaS tool. Long sessions on ivory (`#f7f5ef`) are easier than on white. |
| Serif display type (Fraunces) for page titles | It is the one memorable thing. Keep it, and ration it (2.3). |
| Grouped dark sidebar (Overview, Workflow, Accounting, Assurance, Intelligence, Management) | The cofounder's map of the whole product. Phase 1 fills the first half of each group; the rest is "Coming soon". |
| Top bar: firm name, FY picker, client picker ("All clients" or one), search | The right model: one place that says "whose books am I in". |
| Cards with a 1px warm border, generous padding | Fine for summaries. Not for ledgers (see 1.2). |
| Dashboard idea: one screen that says what needs a person today | Keep the idea, replace every number with a real one (3.5). |
| Client profile as header card + tabs + checklist-like "current work" | Becomes our overview checklist (3.6). |

### 1.2 Improve (measured on the running mockup at 1440 x 900)

| Problem in the mockup | Measured | What we do |
|---|---|---|
| Tiny text: `text-[9px]`, `text-[10px]`, `text-[11px]` used 7, 37 and 34 times; 12 uppercase tracked labels | Sidebar group label `#56565d` on `#161619` is **2.48:1**; card labels `#7a7a82` on ivory **3.90:1**; champagne `#b8924a` text on ivory **2.66:1** (all fail 4.5:1) | Floor of **12 px** everywhere, sentence case, no tracked uppercase. New muted text `#5a5a62` = 6.2:1 on ivory. |
| Borders too faint to see | Card border `#efece2` on white **1.18:1**; input border `#e4e0d2` **1.27:1** (WCAG 1.4.11 wants 3:1 for a control's edge) | Card edges may stay decorative; **input and select borders `#8a8574` = 3.4:1**. |
| Table rows 80 px tall (Bookkeeping: wrapped date, voucher, narration, "Bank AI" chip) | 7 vouchers fill a screen | Dense table: 32 px rows, single-line narration with truncation and a way to see all. |
| Single "Amount" column, no Dr/Cr; ISO dates `2026-07-03` | Accountants read Debit and Credit columns | Debit / Credit columns, DD-MM-YYYY (3.2). |
| KPI numbers in the serif (`47` renders with descending old-style figures) | Figures in a display serif do not line up and read like decoration | Figures are Inter, tabular, always. Serif never touches a number. |
| Fake metrics: "68% AI automation", "Time saved 126 hrs", "Accuracy 53.7%", risk scores (Healthy / High Risk / Critical), `Prototype` badge | None exists in the API | Removed. Real counts replace them (3.5). |
| No focus states (0 `focus-visible` rules), 0 `aria-` attributes, sidebar items are `div onClick` | Keyboard user cannot leave the sidebar | Real `<a>` links, `aria-current`, 2 px focus ring `#2f6f62` (5.4:1), skip link. |
| No dark theme; no `prefers-reduced-motion` handling; 5 keyframe animations incl. infinite shimmer | | Dark theme designed (2.1). Motion is opacity-only, 120 ms, and off under reduced motion. |
| 390 px: sidebar stays fixed at 240 px, content squeezed to 150 px (see `r2-mock-phone.png`) | Unusable | Drawer sidebar under 1024 px, cards not tables under 640 px (3.3). |
| Bell with a red "4" and an "AI Assistant" button that do nothing real | Dead controls make an accountant distrust live ones | Removed from phase 1. The top bar shows the real assistant queue state instead (3.7). |
| Text wraps in the client table (name in 3 lines), PAN/GSTIN in mono, 9 columns | | 7 columns, one line per row, PAN and GSTIN only when the API has them (gap B3). |

### 1.3 Where our app is today, so the redesign is honest about the delta

Ours: navy `#14213d` sidebar with an amber `#fca311` accent and Segoe UI. Four nav items (Clients, Work, Team & roles, Firm settings); the client's nine tabs are a second navigation on every client screen. Strengths to keep: real Dr/Cr and lakh formatting (`lib/format.ts`, `ca/Money.tsx`), Withdrawal/Deposit columns, the checklist, the review keyboard model, honest "Provisional" banners. Weaknesses this redesign fixes: two competing navigations, no firm-level view of anything except `/work`, no GST screen although the GST API exists, dense information in small grey text on white.

---

## 2. Design system

### 2.1 Colour tokens (drop into `web/src/styles.css`)

Same variable names as today (`--background`, `--primary`...) so every existing component re-themes without edits. New names are marked (new). Contrast is measured (WCAG relative luminance), not estimated.

| Token | Light | Dark | Use |
|---|---|---|---|
| `--background` | `#f7f5ef` | `#0f0f11` | page |
| `--card` | `#ffffff` | `#161619` | cards, tables, dialogs body |
| `--popover` | `#ffffff` | `#1f1f23` | menus, palette |
| `--surface-2` (new) | `#fbfaf7` | `#1f1f23` | table header, inset panels |
| `--hover` | `#f1eee5` | `#232328` | row and item hover |
| `--foreground` | `#1f1f23` | `#ece9df` | body text (13.1:1 / 15.8:1 on page) |
| `--heading` (new) | `#161619` | `#f6f4ee` | titles |
| `--muted-foreground` | `#5a5a62` | `#a3a3a9` | secondary text: 6.2:1 on page, 6.8 on card / 7.2 on dark card |
| `--faint` (new) | `#6b6b73` | `#8a8a92` | placeholders, disabled hints: 4.8:1 / 5.3:1 (the lowest text grey allowed) |
| `--border` | `#e4e0d2` | `#2a2a2e` | dividers, card edges (decorative, 1.3:1) |
| `--input` | `#8a8574` | `#74747d` | edge of inputs, selects, checkboxes: 3.4:1 / 3.9:1 |
| `--ring` | `#2f6f62` | `#7fbab0` | focus ring: 5.4:1 / 8.2:1 |
| `--primary` | `#265a50` | `#4d9a8e` | the one primary button per surface |
| `--primary-hover` (new) | `#1f4840` | `#7fbab0` | |
| `--primary-foreground` | `#ffffff` (7.9:1) | `#0f0f11` (5.8:1) | |
| `--link` (new) | `#1f4840` | `#7fbab0` | text links (9.4:1 / 8.2:1) |
| `--accent` (champagne bg) | `#f5ecd9` | `#2a2413` | "needs attention" fills, the next-step row |
| `--accent-foreground` | `#7a5a1c` (5.4:1 on fill) | `#dcc488` (9.0:1) | text on the above; also `--warning` text |
| `--accent-edge` (new) | `#dcc488` | `#5a4a22` | border of attention panels |
| `--destructive` | `#a32020` (7.5:1 on white) | `#f08a80` (7.4:1) | errors, mismatches, delete |
| `--destructive-bg` (new) | `#fbeaea` | `#2b1614` | |
| `--success` | `#1f6b4a` (5.7:1 on `#e6f3ed`) | `#5fc39a` (8.4:1) | done, matches, signed off |
| `--success-bg` (new) | `#e6f3ed` | `#12241d` | |
| `--info` | `#2b5a8a` (6.2:1 on `#e8f0f8`) | `#8ab4e6` (8.4:1) | in review, assistant, neutral news |
| `--info-bg` (new) | `#e8f0f8` | `#13202e` | |
| `--sidebar` | `#161619` | `#0a0a0c` | sidebar bg |
| `--sidebar-foreground` | `#c9c9cd` (10.9:1) | same | nav text |
| `--sidebar-muted` | `#9a9aa2` (6.5:1) | same | group labels, "Soon" chips, footer |
| `--sidebar-active` | `#22332f` | `#1a2724` | active item bg, with a 2 px `#7fbab0` left bar (8.2:1) |

Rule of colour roles: **emerald acts, champagne asks, red stops.** Emerald = the primary action and the selected thing. Champagne = "a person must decide or look" (Provisional, opening balance not confirmed, assistant entries unchecked, the next step). Red = only for a figure that does not tally or a failed operation. Green = only a completed state or a matching figure. Never use colour alone: every status badge carries text and an icon (2.4).

The old amber (`#fca311`) and navy (`#14213d`) are retired everywhere, including the dark theme's amber primary. Data-viz (the only chart is the daily-activity bar chart): one series in `--primary` at 70% fill; no rainbow.

### 2.2 Spacing, radius, elevation, motion

- Spacing: 4 px base. Page gutter 24 px (16 px under 640). Between cards 16 px. Card padding 20 px comfortable, 16 px dense. Section gap in a page 24 px.
- Radius (not one radius for everything): controls 8 px, badges 6 px (pill only for count chips), cards 12 px, dialogs and sheets 16 px, table container 12 px.
- Elevation: cards are flat (1 px `--border`, no shadow). Only popovers, menus, dialogs, toasts float: `0 8px 24px rgb(22 22 25 / .12)` light; dark uses a lighter surface step and a 1 px border, no shadow. The mockup's three shadow sizes and the hover-lift on every card go.
- Motion: none by default. Dialogs, menus and toasts fade in 120 ms (opacity only). No translate, scale, shimmer, pulse or infinite animation. The whole block sits inside `@media (prefers-reduced-motion: no-preference)`. Skeletons are static tinted blocks (`--hover`).
- Target size: 24 x 24 px minimum on desktop (WCAG 2.5.8), 44 px under `(pointer: coarse)`. Dense rows are 32 px, so row actions must be at least 24 px hit areas.

### 2.3 Type

Fonts, self-hosted with `@fontsource-variable/inter` and `@fontsource-variable/fraunces` (Latin subset, `font-display: swap`; no Google request, so it works offline and on Render/Vercel). This needs a package install: frontend-dev's call. If they refuse, fall back to `system-ui` for Inter and Georgia for Fraunces; the scale below still holds.

| Role | Font | Size / line | Weight | Where |
|---|---|---|---|---|
| Page title (h1) | Fraunces, `opsz` 36, `SOFT` 0, `WONK` 0 | 26/32 (28/34 from 1280) | 600, tracking -0.01em | one per page: module name, or client name on the profile |
| Empty/Coming-soon headline | Fraunces | 22/28 | 600 | |
| Section title (h2) | Inter | 15/22 | 600 | card titles |
| Sub-title (h3) | Inter | 13/20 | 600 | |
| Body | Inter | 14/20 | 400 | |
| Dense table text | Inter | 13/18 | 400 | when density = compact |
| Column header, caption, hint | Inter | 12/16 | 600 (header), 400 (caption) | sentence case, `--muted-foreground` |
| Figures (KPI, money) | Inter, `font-variant-numeric: tabular-nums` | KPI 28/32, table 13-14 | 600 KPI, 400 table | |
| Narration, cheque no., IFSC | `--font-mono` | 12/16 | 400 | only bank-supplied strings |

Serif is allowed in exactly three places: h1, the empty-state/Coming-soon headline, and the sign-in title. It is never used in a table, a card body, a badge, a button, a dialog or on any number. Line length under 80 characters for prose (`max-w-prose`). Minimum size 12 px, no exceptions.

### 2.4 Components

Map onto existing files in `web/src/components/ui/`. "Change" says what to edit; "New" is a file to add.

**Button** (`button.tsx`; change variants). One `primary` per surface (page header OR dialog footer OR the current checklist step), never two. `secondary` = white with `--input` border. `ghost` for icon and tertiary. `destructive` is an outlined red button that opens a confirm; solid red exists only inside the confirm dialog. Sizes: `sm` 32, `md` 36, `lg` 44. Loading: spinner replaces the icon, label stays, `aria-busy`, disabled, so a double click cannot submit twice. Keyboard hints render as `<Kbd>` inside the button (already the pattern: "Post entry P").

**Input, select, textarea** (`input.tsx`, `controls.tsx`, `field.tsx`). Label above, 13 px/500 sentence case (the mockup's 12 px uppercase label goes), hint below in `--muted-foreground`, error below in `--destructive` with an icon and `aria-describedby`; on submit failure focus moves to the first invalid field. Height 36, radius 8, border `--input`, focus: ring 2 px + 2 px offset. Masks (`Field` gets a `mask` prop): PAN `AAAAA9999A` uppercased as typed; GSTIN 15 characters, uppercased, state code check as you type, full validation on blur (the server's rule wins); amount `₹` prefix, lakh grouping as you type, right-aligned, never a minus sign (use a Dr/Cr toggle); date DD-MM-YYYY via the existing `date-input.tsx`.

**Table** (new `components/ui/table.tsx`, `<DataTable>` primitive, used by every list). Props: `density` (from `usePreferences`), `columns` with `align`, `priority` (1 = never hide), `sticky`, `sortable`. Rules:
- Sticky header (`--surface-2`, bottom border), scroll container is the page, not a nested box, except where noted.
- Row height: comfortable 40 px, compact 30 px (`--row-h`, replaces 2.5rem/1.875rem). Default for Day Book, Ledgers, Review, Statements: compact. Default for Clients, Team, Work: comfortable.
- Numeric columns right-aligned, tabular, header right-aligned too. Text left. No centred columns.
- One line per row. Long text truncates with `title` and, where it matters (narration), the row's detail pane or a "Show full" expander shows all of it.
- Selection: leading 40 px checkbox column; when any row is ticked the header row is replaced by a bar "3 selected · Post · Clear" (bulk actions live there, not in the page header).
- Under 640 px: tables with more than 4 columns become a labelled scroll region (`role="region"`, `aria-label`, `tabindex=0`) with a sticky first column; the Review worklist becomes a list plus a full-screen detail (3.7).
- Totals row is `<tfoot>`, 600 weight, top border 2 px `--foreground`, always visible when the table fits, sticky-bottom when it scrolls.
- Real `<table>` markup with `<th scope>`, `<caption class="sr-only">`, `aria-sort`.

**Money cell** (`components/ca/Money.tsx`; change). Rules the whole product follows:
- Indian grouping to crore: `₹1,25,00,000.00`. Two decimals always in tables and reports.
- Dense tables and reports omit the `₹` in cells and put `₹` in the column header ("Debit ₹"); cards, totals lines and prose keep the symbol.
- Two-column convention (Day Book, Trial Balance, ledger): separate **Debit** and **Credit** columns, bare amounts, no signs. Bank rows: **Withdrawal** and **Deposit** (mirrors the statement; keep). One-column balances always carry a side as text: `6,03,490.57 Dr`. Never a negative number, never colour as the only signal.
- A zero in a Dr/Cr column renders `–` in `--faint` (currently 60% opacity, fails contrast). Nil balances in the TB stay `0.00` because auditors expect them.
- Abbreviated amounts (`₹1.25 Cr`, `₹48.5 L`) are allowed in dashboard cards only, always with the full figure in `title` and `aria-label`; never in a table or report.
- Dates: DD-MM-YYYY in tables and inputs; `30 Apr 2025` in sentences and cards (`formatDateLong`). FY label `FY 2025-26`, April to March, named by its starting year (existing `fyLabel`).

**Status badge** (`badge.tsx`; add `tone` and `icon`). Height 22, 12 px/500, radius 6, always icon + text. Tones and icons: `neutral` (dot), `done` (check, success), `attention` (triangle, champagne), `danger` (x-circle), `info` (info circle), `assistant` (sparkle, info tone). Honest status vocabulary, exactly these words:

| Where | Words | Tone |
|---|---|---|
| Books | Working draft; Sent for review; Returned; Signed off to dd-mm-yyyy | neutral; info; attention; done |
| Reports | Provisional (with the count of unposted rows) | attention |
| Bank | Opening balance not confirmed; Opening confirmed | attention; done |
| Entries | Assistant posted (unchecked); Assistant posted (checked); Corrected | assistant; done; neutral |
| Rows | Needs a ledger; Ready to post; Posted | attention; info; done |
| GST run | Draft; Signed off | neutral; done |
| Jobs | Reading; Waiting; Done; Failed | info; neutral; done; danger |

Never invent "Healthy / High risk / Critical", "Active", "Onboarding" until the API has the field (gap B3).

**Card** (`card.tsx`). Flat: `bg-card`, border, radius 12, padding 20. Header slot = h2 + optional right-aligned link. `StatCard` (new): label 12/16 muted, value 28/32 Inter 600, one-line note 12 muted, optional link; whole card is a link when it has a destination. Alert card variant (`attention`, `danger`, `info`): tinted bg, 1 px edge, icon, one sentence, one action.

**Dialog** (`dialog.tsx`). Radix as today. Widths 448 (confirm), 560 (form), 720 (wide). Title Inter 18/600 (no serif). Footer: secondary "Cancel" left of the primary; primary label is the verb ("Sign off books", not "OK"). Esc closes; focus on the first field (confirm dialogs: on the safe button); focus returns to the opener. Destructive dialogs name the object and state the consequence in one sentence (existing `ca/Confirm.tsx`).

**Toast** (Sonner, already in use). Bottom-right desktop, full-width bottom on mobile. Success auto-dismisses at 6 s, pauses on hover and focus, and never carries the only copy of a result (the page also shows it). Errors persist until dismissed, `role="alert"`, and say what failed and what to do. Same verb as the button: button "Post entry" gives toast "Entry posted".

**Empty / loading / error.** Loading: a skeleton with the real table's row height and column widths, static, `aria-busy="true"` on the region, `aria-live="polite"` announcement "Loading day book". Empty: one sentence of what this is and why it is empty, plus the one next action as a primary button ("No statements yet. Upload a bank statement PDF to start."). Error: what failed in plain words, the server's `detail` if present, a Retry button, and the request id if the API sent one. Permission denied: "Your role (Read only) cannot post entries." with no button. Offline: a persistent top strip "You are offline. Changes cannot be saved."; primary buttons disabled.

**Coming soon.** Sidebar: item is a real link, text `--sidebar-muted`, trailing chip "Soon" (12 px, `--accent` tone, radius 6). Never `aria-disabled`; it is reachable. Page (`ComingSoon` component, route `/soon/$module`): serif headline "Documents is coming soon", one sentence saying what it will do, one line "Until then:" with a link to what to use today, nothing else. No fake screenshots, no email capture, no progress bar. Settings > Preferences has "Hide modules that are coming soon" (default off, so the cofounder sees the whole map). Copy per module in 3.2.

**Command palette** (`CommandPalette.tsx`; keep, extend). Ctrl+K opens; groups: Clients (type to filter; picking one switches client and keeps the current module), Go to (every live module), Actions (Upload bank statement, Open review, Post ready rows, Send for review). Alt+C still opens it with "Clients" focused. Footer hints: Enter select, Esc close.

**Density and theme.** Both stay as user preferences (`lib/preferences`), in the user menu and Settings > Preferences. Dark follows `prefers-color-scheme` until the user chooses.

---

## 3. Information architecture

### 3.1 The shell

```
+-------------------+------------------------------------------------------------+
| [CA] AutoCA       | QA Associates | [ QA Sharma Traders   v ] [FY 2025-26 v]   |
|                   |               [ Search or jump  Ctrl K ]  ( assistant: 14 )|
| Overview          |                                             [theme] (AA)   |
|  Dashboard        +------------------------------------------------------------+
|  Clients          |  Bank statements                       [ Upload statement ]|
| Workflow          |  QA Sharma Traders · Working draft                        |
|  Work pipeline    |  [ Statements ] [ Review 16 ]                              |
|  Documents  Soon  |  ...                                                       |
| Accounting        |                                                            |
|  Bookkeeping      |                                                            |
|  Bank statements 16                                                           |
|  GST reconciliation                                                           |
|  Taxation   Soon  |                                                            |
| Assurance         |                                                            |
|  Audit      Soon  |                                                            |
|  Compliance Soon  |                                                            |
| Intelligence      |                                                            |
|  Reports          |                                                            |
|  AI assistant Soon|                                                            |
|  Firm analytics Soon                                                           |
| Management        |                                                            |
|  Staff performance|                                                            |
|  Notifications Soon                                                            |
|  Settings         |                                                            |
| [AA] Anita Admin  |                                                            |
+-------------------+------------------------------------------------------------+
```

- Sidebar 248 px, sticky, full viewport height, scrolls inside if short. Group labels 12 px, sentence case, `--sidebar-muted`. Items 36 px, icon 16 px, active = `--sidebar-active` + 2 px left bar. Counts (real): Bank statements shows rows waiting for the selected client, or the firm total under All clients (`/team/clients/` sum). Footer: user name and role; menu with theme, density, shortcuts, sign out.
- Under 1024 px the sidebar is a drawer opened by a menu button (44 px), focus-trapped, Esc closes, closes on navigate.
- Top bar 56 px, `--background` with a bottom border, not translucent blur. Contents left to right: firm name (text, 13 px), client picker, FY picker, palette trigger (search-styled button "Search or jump" + `Ctrl K`), assistant indicator (shows only while the queue has rows: "Assistant reading 14 rows" / "Assistant paused, 32 s"; click goes to Review), user menu. No bell, no "AI Assistant" button in phase 1.
- **Client picker** = a combobox button (the current "Switch client" opens the palette; keep that mechanism, but restyle and show the current client name, or "All clients"). Listbox: "All clients" first, then recents, then alphabetical; type to filter; shows lead and the next step on each row. Changing client keeps the module and tab: on `/clients/A/daybook` picking B goes to `/clients/B/daybook`. Picking "All clients" goes to that module's firm landing (3.3).
- **FY picker**: active only when a client is selected (the year belongs to one client's books, and clients can start in January). Under All clients it renders as plain text "All years" and is not focusable. It keeps writing `?fy=` and remembering the year per client (`useFy` unchanged).
- Skip link "Skip to content" is the first tab stop. Landmarks: `header`, `nav aria-label="Main"`, `main`, `aside` for detail panes.
- Page header pattern, every page: h1 (serif) = module name; below it one muted line: client name, status badge, FY; right side: the one primary action. Tabs below (2.4 tab style: text tabs with a 2 px `--primary` underline on the active one, 40 px tall).

### 3.2 Modules

Phase 1 (live), with the real screens they map to:

| Sidebar item | All clients | One client | Old screens folded in |
|---|---|---|---|
| Dashboard | the dashboard (3.5) | same page, scoped: that client's numbers (uses profile data) | new |
| Clients | client list (3.6) | the client profile (3.6) | `/clients`, overview |
| Work pipeline | pipeline board and allocation (3.10) | same page filtered to the client | `/work` waiting sections, `ClientTeamScreen` |
| Bookkeeping | client table with books status | tabs: Day Book, Ledgers, Parties & rules, Books & sign-off | daybook, ledgers, masters, books |
| Bank statements | client table with statement and row status | tabs: Statements, Review | statements, review, upload |
| GST reconciliation | client table with the latest run | registrations, runs, one run (3.9) | new screens over the existing API |
| Reports | client table | tabs: Trial Balance, Profit & Loss, Balance Sheet, Bank reconciliation | reports |
| Staff performance | the page | same page, "By client" section pinned to the client | `/work` performance sections |
| Settings | Firm, Team & roles, Activity log, Preferences | same | `/firm`, `/team` |

Coming soon (each a link to `/soon/<slug>`), copy for the page:

| Module | Sentence | "Until then" |
|---|---|---|
| Documents | A shared folder for each client's files, with who uploaded what and when. | Bank statements live under Bank statements. |
| Taxation / ITR | Income-tax and advance-tax workings from the closed books. | Export the books to Tally from Books & sign-off. |
| Audit | Audit programmes and working papers per client. | The Activity log in Settings records every change in the books. |
| Compliance | A calendar of due dates per client, with reminders. | GST working papers are under GST reconciliation. |
| AI assistant | Ask questions across a client's books in plain language. | The assistant already reads bank rows: see Bank statements. |
| Firm analytics | Turnover, realisation and load across the firm. | Staff performance counts what each person did. |
| Notifications | Alerts for returns, sign-off requests and deadlines. | The dashboard lists what is waiting. |

Renames (words wrong for Indian CA practice or for what we built):

| Mockup | We call it | Why |
|---|---|---|
| Bank Statement AI | **Bank statements** | The module is upload, place, post. "AI" is one step and an accountant does not want the module named after a tool. **Decision for the user** (7). |
| Work Management | **Work pipeline** | There are no tasks, priorities or due dates in the API. What exists is where each client's books stand. |
| Work Allocation | **Allocation** (a tab of Work pipeline) | Same screen, one job: who is in charge. |
| Journal Entries | **Day Book** | Tally vocabulary; matches the vouchers we post. |
| General Ledger | **Ledgers** | |
| Cash Book, Receivables, Payables | not built | Not phase 1. Ledger balances by Group cover them. |
| AI Matching, Mismatch Detection (GST) | **Match**, **Differences** | The matching is rules, not a model. Do not claim AI. |
| Staff Performance % bars | counts only | The current page says "Counts only: no rankings"; keep it. |
| Assigned CA | **Senior CA in charge** | Matches the team feature. |
| Entry / New Entry | **Voucher** | Tally. |

Keep everywhere: Day Book, Voucher, Particulars, Contra, Ledger, Group, Withdrawal, Deposit, Debit, Credit, Books & sign-off, Provisional.

### 3.3 Firm-level landings and the "client table"

Any client-scoped module opened under **All clients** shows one shared component, `ModuleClientTable`, instead of an empty state: a `DataTable` of clients with columns specific to the module, a search box, and a row click that selects the client and opens that module for them. Columns:

- Bookkeeping: Client · Senior CA · Books status · Signed off to · Entries waiting · Assistant entries unchecked.
- Bank statements: Client · Latest statement to · Months missing (FY) · Needs a ledger · Ready to post · Action ("Upload").
- GST: Client · GSTINs · Latest run · Differences open · Status.
- Reports: Client · Signed off to · Provisional? · Open Trial Balance.

Data today is the per-client fan-out (3.6). At scale it needs the firm overview endpoint (gap B1).

Mobile (390): sidebar drawer; top bar is menu button, client picker (flexes), user menu; FY becomes a chip in the page-header line; tabs scroll horizontally with edge fade; tables become cards or scroll regions (2.4); primary action becomes a full-width button under the title; KPI cards 2 columns; dialogs full-screen sheets.

### 3.4 Routes: today to new

TanStack Router file routes in `web/src/routes/_app`. Client-scoped URLs do not change, so every existing link, bookmark and `?fy=` still works.

| Today | New | Note |
|---|---|---|
| `/` | redirect to `/dashboard` | today it goes to `/clients` |
| `/clients` | unchanged | list |
| `/clients/:id` | unchanged | now the profile with the checklist on top |
| `/clients/:id/statements` | unchanged | module Bank statements, tab Statements |
| `/clients/:id/review?stage=` | unchanged | module Bank statements, tab Review |
| `/clients/:id/daybook` | unchanged | module Bookkeeping, tab Day Book |
| `/clients/:id/ledgers` | unchanged | Bookkeeping, tab Ledgers |
| `/clients/:id/masters` | unchanged | Bookkeeping, tab Parties & rules |
| `/clients/:id/books` | unchanged | Bookkeeping, tab Books & sign-off |
| `/clients/:id/reports?report=tb\|pl\|bs\|recon` | unchanged | module Reports |
| `/clients/:id/team` | unchanged | shown as the profile's "Team & details" tab |
| any of the above `?fy=2025` | unchanged | still parsed by `parseFy` on `/clients/$clientId` |
| (none) | `/clients/:id/gst` `?run=<id>` | new |
| (none) | `/dashboard`, `/pipeline?view=board\|allocation`, `/bookkeeping`, `/bank`, `/gst`, `/reports` | firm landings (3.3) |
| `/work` | `/staff` (redirect `/work` to `/staff`, keeping `from` and `to`) | performance page moves |
| `/team` | `/settings/team` (redirect) | |
| `/firm` | `/settings/firm` (redirect) | |
| (none) | `/settings/activity`, `/settings/preferences`, `/soon/$module` | new |

The active module in the sidebar is derived from the path, not stored. The selected client is derived from the URL, never from hidden state, so any address reproduces the view.

### 3.5 Dashboard (`/dashboard`)

Purpose: in ten seconds, what needs a person today. Only real numbers.

```
Dashboard                                            FY view: All years
QA Associates · 30 Sep 2026

+-------------+ +-------------+ +--------------+ +----------------+
| Clients     | | Rows to place| | Ready to post| | No Senior CA   |
| 15          | | 11          | | 90            | | 5 clients      |
| 6 have work | | 4 clients   | | 6 clients     | | Allocate       |
+-------------+ +-------------+ +--------------+ +----------------+
 (v2, needs backend B1:) Assistant entries unchecked · Books awaiting sign-off · Statements missing a month

+--------------------------------------------+ +---------------------------+
| Needs attention                            | | This month                |
| Client              Waiting   Senior CA    | | Statements uploaded    23 |
| QA CA Bindal        20 ready  Not assigned | | Rows placed           572 |
| QA Sharma Traders   16 ready  Sanjay Senior| | Entries approved      381 |
| QA API TestCo Two   4 to place Not assigned| | Assistant runs          5 |
| ...                          [All clients] | | (daily bars, 30 days)     |
+--------------------------------------------+ +---------------------------+
| Recent activity                                                          |
| 30-09 11:02  Sanjay Senior signed off QA Gupta Exports through 31-03-2026|
+--------------------------------------------------------------------------+
```

| Block | Endpoint and fields (available now) |
|---|---|
| Clients | `GET /api/v1/clients/` `count`; "have work" = rows of `GET /api/v1/team/clients/` where `unresolved + pending_approval > 0` |
| Rows to place / Ready to post | sum of `unresolved` and `pending_approval` over `GET /api/v1/team/clients/` `results` (fields `id, name, lead, team, unresolved, pending_approval`) |
| No Senior CA | `team/clients` rows with `lead == null` |
| Needs attention | the same rows, sorted by `unresolved` then `pending_approval`, top 8; row click sets the client and opens Review |
| This month | `GET /api/v1/team/members/?from=&to=` summed `work.statements_uploaded, rows_placed, entries_approved, model_runs`; bars from `GET /api/v1/team/members/{id}/work/` `by_day` summed (or gap B2) |
| Recent activity | `GET /api/v1/team/events/` `kind_display, detail, at` (newest 8) |

Under **one client**: the same page turns into a compact version of the profile's "Books at a glance" (3.6), so the dashboard is never empty. Roles: staff see the same cards limited to clients they can see (the server already scopes); reader sees no buttons.

States: loading = four card skeletons and a table skeleton; empty firm = "No clients yet. Add your first client." + primary `New client`; error = alert card with Retry.

Not shown until the API exists (section 6): assistant entries unchecked (firm), books awaiting sign-off, statements missing a month (firm), clients by stage. No compliance-due, risk, department load, hours saved, AI automation %, or staff efficiency %.

### 3.6 Clients and the client profile

**Clients list** (`/clients`)

```
Clients                                              [ Search clients ] [ New client ]
15 clients
+----------------------------------------------------------------------------------+
| Client            Senior CA      FY starts  Statements to  Waiting        Next step |
| QA Sharma Traders Sanjay Senior  01-04-2025 30-04-2025     16 ready      Confirm opening balance |
| QA API TestCo Two Not assigned   01-04-2025 31-03-2026     4 to place    4 rows need a ledger    |
+----------------------------------------------------------------------------------+
```

Columns: Client (truncate, 1 line) · Senior CA ("Not assigned" in attention tone) · FY starts · Statements to (max `period_end` of `statements`) · Waiting (`unresolved`, `pending_approval`) · Next step (same text as today; keep the logic in `ClientsScreen`). Filters as chips: All, Mine, Needs a ledger, Ready to post, Not assigned. Row = one link; comfortable density; sort by client, waiting. Data: `GET /clients/` + per row `statements`, `books`, `review-queue/summary` (today's 3N fan-out: limit to the visible page of 25 until gap B1). PAN, GSTIN, constitution, status and service tags from the mockup are not shown (gap B3). States: empty = "No clients yet"; a search with no result = "No client matches 'xyz'" with Clear.

**Client profile** (`/clients/:id`), the one page a CA opens most.

```
QA Sharma Traders                                          [ Upload bank statement ]
[Working draft] Senior CA: Sanjay Senior · FY 2025-26 (from 01-04-2025)

[ Overview ] [ Team & details ]

+-------------------------------------------------+ +---------------------------+
| What is next                                    | | Client details            |
| (done) Upload bank statements  [Upload the next]| | FY starts   01-04-2025   |
|        1 statement on file, up to 30-04-2025    | | Bank accounts   1        |
| [2] Confirm opening balances    Next step       | | GSTINs   27...  (gst API) |
|     Not confirmed for Generic Bank A/c 3456...  | | Team   Sunita, Rohan     |
|                              [ Confirm ] primary| +---------------------------+
| (done) Place every transaction in a ledger      | | Assistant entries to check|
| [4] Post to the Day Book           [ Post ]     | | 2 entries ... [Open Day Book]
| [5] Send for review                             | +---------------------------+
| [6] Senior CA signs off                         |
+-------------------------------------------------+
Statements by month  Apr May Jun Jul Aug Sep Oct Nov Dec Jan Feb Mar
                      [x] [ ] [ ] ...      x = statement covers the month
Books at a glance:  Rows to place 0 · Ready to post 16 · Assistant entries unchecked 2 · Signed off to: not yet
```

- The checklist is the current `ClientOverview` unchanged in content and order (the six steps, "Next step" badge, the reason line). Only its skin changes: the next step's row gets `--accent` background and `--accent-edge` border, and **its** action is the page's only primary button besides "Upload bank statement" (which becomes secondary when the next step is itself an upload). Done steps: success check icon; future steps: numbered outline circle. The 12-month strip is new and derived from `statements[].period_start/period_end` on the client's FY: filled = every day covered, half = partly covered, empty = none. Text alternative: "Months with a statement: April to June; missing: July to March".
- "Books at a glance" is four `StatCard`s from `books/` (`waiting, ai_posted, ai_revised, signed_off_through, review_pending`) and `review-queue/summary/`.
- Team & details tab = the current `ClientTeamScreen` plus the business profile (`business_profile`, editable by roles that can). "Senior CA in charge" edit uses `POST /team/clients/{id}/lead/`.
- Roles: reader sees no primary button. Staff cannot sign off (existing `can_sign_off`, `can_post` gate).
- Not on the profile: PAN, GSTIN list, constitution, contact, risk badge, services chips, "Current work" tasks, "AI insights", "ITC at risk" (gap B3; GSTINs can show from the GST registrations endpoint).

### 3.7 Bank statements

Tabs: **Statements** and **Review**. Page action: `Upload bank statement` (primary), which opens the existing `UploadDialog`.

**Statements tab** (`/clients/:id/statements`)

```
Bank statements   QA Sharma Traders · Working draft · FY 2025-26        [ Upload bank statement ]
[ Statements ] [ Review 16 ]

Where the rows stand      [#### posted 4 |### ready 16 |  needs ledger 0 ]   total 20 rows
Assistant: idle   (or) Reading 14 of 46 rows · paused, resumes in 32 s

Bank accounts
 Account              IFSC          Ledger in Tally     Opening balance       As at
 Generic Bank A/c 3456 QADB0000123  Generic Bank A/c 3456 (!) Not confirmed  -   [Confirm opening]

Statements on file
 Period                   Account      Rows  Opening  Withdrawals  Deposits  Closing        
 01-04-2025 to 30-04-2025 Generic ... 20  1,25,000.00 1,60,255.02 3,11,034.00 2,75,778.98  [Rows] [Tally XML] [Delete]
```

- Data: `GET /clients/{id}/bank-accounts/`, `GET /clients/{id}/statements/` (`period_start, period_end, opening_balance_display, total_debit_display, transaction_count, bank_account_label`), `GET /clients/{id}/review-queue/summary/` (`unresolved, pending_approval, total, assistant_waiting`), upload `POST /clients/{id}/statements/upload/` then poll `GET /jobs/{id}/`.
- Upload dialog states: drop zone (PDF only, size limit stated), then a determinate progress bar bound to `job.progress` with `job.message` as the label, then the result from `job.result` (`IngestResult`): "20 rows read. 4 placed by rules, 16 ready to post, 0 need a ledger." plus `needs_opening_confirmation` → attention alert "Confirm the opening balance" with a button. No invented pipeline steps (Upload, AI extraction, Recognition, ...) and no accuracy percentage or "time saved".
- The row-standing bar is one `<div role="img" aria-label="4 posted, 16 ready to post, 0 need a ledger">` plus a text legend (colour is never the only signal).
- Delete a statement = destructive confirm naming the period and the number of rows.
- Assistant strip: driven by `assistant_waiting` on the summary and the `POST /clients/{id}/assistant/next-batch/` outcome (`state` working/paused/idle, `waiting`, `retry_after_seconds`, `reason`, `message`, `auto_posted`, `proposed`). Copy uses the server's `message`; `reason = assistant_off` reads "The assistant is off, so rows are placed by rules and by you." It mirrors into the top-bar indicator and `aria-live="polite"`.
- Empty (no statements): "No statements yet. Upload the PDF from net banking, any bank." + primary button. Roles: only `document.upload` roles see Upload.

**Review tab** (`/clients/:id/review?stage=`): the worklist. Layout unchanged from today, re-skinned.

```
Needs a ledger 0 | Ready to post 16 | All waiting 16        Confidence: Any High Check Decide     [Ask assistant to suggest]
[ Search narration, payee, ledger, amount ]
+-------------------------------------------------------+ +------------------------------+
| [] Date       Narration              Withdrawal Deposit  Ledger | | 26-04-2025     Received 61,800.00 |
| [] 26-04-2025 NEFT CR-ICIC...LOTUS   .          61,800.00 Sales | | NEFT CR-ICIC... (mono)           |
| ...                                                       (dot) | | The entry this makes             |
|                                                            | | Dr Generic Bank A/c   61,800.00  |
|                                                            | | Cr Sales              61,800.00  |
|                                                            | | Suggested by a language model    |
|                                                            | |   85% sure. "Sales credit ..."   |
|                                                            | | Ledger [ Sales ]  Party [ ]      |
|                                                            | | TDS [ ]  [ ] Reverse charge      |
|                                                            | | [x] Remember this for similar rows |
|                                                            | | [Confirm ledger Enter] [Post entry P] |
+-------------------------------------------------------+ +------------------------------+
```

- Keyboard model stays exactly: `j`/`k` (and arrows) move, `x` ticks a row, `l` focuses the ledger, `Enter` places in the chosen ledger, `P` posts, `?` opens the shortcut sheet, `Ctrl+K` the palette. Add `/` to focus the search. The shortcut sheet keeps listing only what is registered on this screen.
- Changes: narration is one line (mono only for the bank text, 12 px) with the full text in the detail pane; Withdrawal and Deposit stay separate columns; the confidence dot becomes dot + a word (High / Check / Decide) in the column for the non-colour signal; selected row gets `--accent` background and a 2 px left bar; the detail pane is sticky with its own scroll and its footer buttons pinned; the wording "Remember this" (the learn checkbox) and "Suggested by a language model · 85% sure" stay honest; bulk bar appears on tick: "3 selected · Post · Clear".
- 390 px: the table is a list (date, narration one line, amount with Dr/Cr word, ledger); tapping opens the detail as a full-screen sheet with a sticky action bar (Confirm ledger, Post entry); `j/k` unavailable, swipe not used.
- States: loading skeleton rows; empty "Nothing waiting. Every row is placed and posted." + link "Open Day Book"; a row failing to post shows the server `detail` inline on the row and keeps focus on it.

### 3.8 Bookkeeping

Tabs: **Day Book · Ledgers · Parties & rules · Books & sign-off**.

**Day Book** (`/clients/:id/daybook`)

```
Bookkeeping   QA Sharma Traders · Working draft · FY 2025-26                (no primary)
[ Day Book ] [ Ledgers ] [ Parties & rules ] [ Books & sign-off ]
FY 2025-26 · 4 vouchers   [ Search ledger, party or narration ] (All)(Payment)(Receipt)(Contra)(Journal)  [ ] Assistant entries only   [Unpost 2 assistant-posted]
 Date        Particulars                       Vch type  Vch no.      Debit ₹     Credit ₹
 08-04-2025  Cash-in-Hand                      Contra        2     10,000.00
             Being cash withdrawn from ATM
 28-04-2025  Bank Charges [Assistant posted]   Payment       1         17.70
 Total (4 vouchers)                                              21,437.70       684.00
```

Same data and columns as today (`GET /journal-entries/?client=&live=true`): Date, Particulars (+ narration line 12 px muted, truncated), Vch type, Vch no., Debit, Credit, total row. "Assistant posted" is the `assistant` badge (sparkle + words). Row click opens a right-side drawer with the voucher's lines, `GET /journal-entries/{id}/changes/` history, Correct and Remove actions (existing). `Unpost N assistant-posted` stays secondary and destructive-confirmed. Empty: "No vouchers in FY 2025-26. Post rows from Review."

**Ledgers / Parties & rules**: existing screens, re-skinned with `DataTable` and the `LEDGER_GROUPS` order as group headers (Tally primary groups). **Books & sign-off**: existing `BooksScreen` and the new `SignOffDialog` unchanged in content: the status card (Working draft / Sent for review / Signed off to), the three counts (waiting, assistant entries unchecked, changed after correction), the attention alert for unchecked assistant entries, actions `Send for review` (primary when enabled), `Mark assistant entries as checked`, `Return`, `Reopen`; the history list. The sign-off dialog keeps its rules: "Sign off through" date defaulting to the latest entry, refusal reasons stated ("Reading the entries…", "Enter the date as DD-MM-YYYY."), the list of what will lock, and primary `Sign off books`. Export to Tally moves to a card here with the exact Tally instructions it has now.

### 3.9 GST reconciliation (new screens, existing API)

Phase 1 module with a complete API and no screen today. It is the largest build item.

Endpoints (all under `/api/v1/clients/{client_id}/gst/`): `registrations/` (list, create `gstin`, `registration_type`), `runs/` (list, create `registration`, `period` `YYYY-MM`), `runs/{id}/` (report), `runs/{id}/register/` (upload the purchase register), `runs/{id}/portal/` (upload GSTR-2B JSON or Excel), `runs/{id}/reconcile/`, `runs/{id}/decisions/` (`match`, `kind`, `note`; kinds `accept_match, claim_itc, disallow_itc, defer, note`), `runs/{id}/sign-off/`, `runs/{id}/export/` (Excel working paper).

```
GST reconciliation   QA Sharma Traders                       [ New run ]
Runs   GSTIN 27AABCA1234F1Z5   Period      Status  Differences open   ITC eligible
                                Aug 2026    Draft   6                  1,88,460.00

Run: 27AABCA1234F1Z5 · August 2026 · Draft
Steps  (1) Purchase register  [uploaded] → (2) GSTR-2B [uploaded] → (3) Match [Run match] → (4) Decide → (5) Sign off

+ Eligible ITC 1,88,460.00 + Blocked ... + Ineligible ... + Reverse charge ... + In 2B, not in books ... +

Actions for you (report.actions):  INV/2026/0162 Mahindra Logistics: ask the supplier to file
Groups (order from the API): Amount differences (1) ▸  Missing in GSTR-2B (1) ▸ ... Matched (3) ▸
  Supplier  Invoice  Date   Books taxable | GST     GSTR-2B taxable | GST    Difference   Decision
  Tata Steel INV/..  ...    ...                      ...                       900.00      [Claim] [Disallow] [Defer] [Note]

GSTR-3B Table 4 (indicative, not the return)   4A(5) All other ITC ... IGST CGST SGST Cess        [ Export Excel ]   [ Sign off run ]
```

- Fields used from `run_report`: `id, registration.gstin/state_code, period_start, status, signed_off_at, has_register, has_portal, summary{counts, eligible_paise, blocked_paise, ineligible_paise, rcm_liability_paise, unclaimed_in_2b_paise, unresolved}, gstr3b[{code,label,igst,cgst,sgst,cess}], groups[{kind,title,count,rows[{id,itc_status,eligible_paise,ineligible_paise,cause,action,timing,differences,book,portal,decision}]}], actions[{match,text}]`. Money from paise via `formatPaise`. Use the group `title` strings the server sends; do not rename them.
- The stepper is real state: step 1 done when `has_register`, step 2 when `has_portal`, Match enabled when both, Sign off enabled when `summary.unresolved == 0`. If the sign-off refuses, show the server message.
- The mockup's "AI matching" and "ITC at risk" wording is replaced by "Match" and "In our books, not in GSTR-2B". Sign-off gets the same confirm pattern as book sign-off; a signed run is read-only with a "Signed off dd-mm-yyyy" badge.
- Roles: `report.view` sees, `transaction.classify`-class permission to record decisions and upload (frontend asks `useSession().can(...)`; the exact permission names must be confirmed in `api/views/gst.py`, see gap B6).
- Empty: "No GSTIN yet. Add the client's GSTIN to start a reconciliation." Tables are wide: sticky first two columns, horizontal scroll region at narrow widths.
- The GST API responses are not typed in `openapi.yaml` (RunCreate shows only `registration`); write the types in `web/src/api/types.ts` from the shape above (gap B5).

### 3.10 Work pipeline, Staff performance, Settings

**Work pipeline** (`/pipeline`). Replaces the mockup's task kanban with the only workflow the API knows: where each client's books stand. Two views (tabs): **Board** and **Allocation**.

```
Work pipeline                                                   [ Board ] [ Allocation ]
 Needs a ledger (3)      Ready to post (4)       Ready for review (2)   Signed off (6)
 +-------------------+   +-------------------+   +-----------------+    +----------------+
 | QA SEC Alpha      |   | QA Sharma Traders |   | ...             |    | ...            |
 | 5 to place        |   | 16 ready          |   |                 |    |                |
 | Sanjay Senior     |   | Sanjay Senior     |   |                 |    |                |
```

- Stage per client is derived from `summary` and `books` (needs a ledger: `unresolved > 0`; ready to post: `pending_approval > 0`; ready for review; in review: `review_pending`; signed off). This is computed client-side today (fan-out) and returned by gap B1 as `stage`.
- Cards are links to that client's Review or Books. Drag and drop is not supported: a column is a state the books are in, not a status a person sets. Columns are also a plain list for keyboard and screen-reader users (list per column, headings, counts).
- **Allocation** tab: table Client · Senior CA · Team · Waiting, from `GET /team/clients/`; inline `Assign` opens the existing dialogs (`PUT`/`POST` on `team/clients/{id}/lead/` and `team/clients/{id}/team/`). This is today's `/work` "Waiting now, by client" plus `ClientTeamScreen`, gathered in one place.

**Staff performance** (`/staff`): today's `/work` performance page (period chips This month / Last month / This financial year / Custom dates, firm activity cards, per-person table, waiting-now table, one person's detail with the daily-activity bar chart and by-client table), re-skinned. Keep the line "Counts only: no rankings" and "Not counted yet: books sent for review..." (the honest gap statement). Metric labels come from `metrics[].label`. The bar chart gets a text table alternative (`by_day` in a `<details>`).

**Settings** (`/settings/...`): tabs **Firm** (`/firm`: name, owner, admins, counts; rename/transfer), **Team & roles** (`/team`: members, invites, roles, manager), **Activity log** (`GET /audit/`: who, when, action, client, outcome; read-only; client filter only if the endpoint supports it, see B7), **Preferences** (theme, density, "Hide modules that are coming soon", keyboard shortcuts list). Client-level masters (ledgers, parties, rules) stay inside Bookkeeping because they belong to one client's books; Settings links to them ("Client masters live under Bookkeeping").

### 3.11 Reports (`/clients/:id/reports?report=`)

Tabs: Trial Balance, Profit & Loss, Balance Sheet, Bank reconciliation (as today). Report canvas is a white card with the report head centred (client, report, "as at 31-03-2026"), the **Provisional** alert first when any rows are unposted or an opening balance is unconfirmed (exact words as today: "Provisional. 16 transactions in this period are classified but not yet posted, so they are not in these figures. Opening balance not confirmed for ...: Confirm the opening balance."), Particulars · Group · Opening · Debit · Credit · Closing Dr · Closing Cr columns, `Grand Total` row with a Provisional badge, footer line (client, FY, entries, generated at DD-MM-YYYY HH:MM). `Print` stays and uses the print stylesheet (white background, black text, no chrome). Bank reconciliation shows `BalanceCheck`: statement balance, ledger balance, difference, `matches`, `unapproved_count`. Under All clients: the client table with "Open Trial Balance".

---

## 4. Map onto the current code (what changes where)

| File | Change |
|---|---|
| `web/src/styles.css` | replace the `:root` and `.dark` blocks with 2.1; add the new variables to `@theme inline` (`--color-surface-2`, `--color-heading`, `--color-faint`, `--color-link`, `--color-accent-edge`, `--color-*-bg`); set `--row-h` to `2.5rem` / `1.875rem` (comfortable / compact 30 px); add font imports, the serif class `font-display`, 12 px minimum, reduced-motion block. |
| `components/ui/button.tsx`, `badge.tsx`, `card.tsx`, `input.tsx`, `controls.tsx`, `field.tsx`, `dialog.tsx` | variants and tokens per 2.4; `Badge` gets `tone` + `icon`; `Field` gets `mask`. |
| `components/ui/table.tsx` (new), `stat-card.tsx` (new), `coming-soon.tsx` (new), `tabs.tsx` (new, link-based) | per 2.4. |
| `components/ca/Money.tsx` | zero rendering `–` in Dr/Cr columns; `symbol` default false inside `DataTable`; abbreviated form for dashboard cards only. |
| `features/shell/Shell.tsx` | rewrite the sidebar (modules, groups, Soon chips, counts), top bar (client and FY pickers, assistant indicator), skip link; keep `UserMenu`, theme and density controls. `CommandPalette.tsx` adds Go to and Actions groups. `useFy.ts` unchanged. |
| `features/clients/Workspace.tsx` | its tab row is split: tabs now belong to modules (3.2). The header (name, badges) becomes the page-header pattern. |
| `features/clients/ClientOverview.tsx` | keep step logic; new skin and the month strip. `ClientsScreen.tsx`: new columns. |
| `features/statements/*`, `features/review/*`, `features/daybook/*`, `features/books/*`, `features/masters/*`, `features/reports/*`, `features/team/*`, `features/work/WorkScreen.tsx` | re-skin, apply `DataTable`; behaviour and keyboard maps unchanged. |
| new `features/dashboard`, `features/pipeline`, `features/gst`, `features/settings`, `features/soon` | per 3.5, 3.10, 3.9, 3.10, 2.4. |
| `routes/_app/*` | add the routes in 3.4 and the redirects. |

---

## 5. Build order for frontend-dev

Each wave leaves the app working and testable. Do not start wave N+1 before N runs clean (`tsc`, `vitest`, a manual pass in light and dark).

1. **Tokens and primitives.** New `styles.css`, fonts, `Button`, `Badge`, `Card`, `Input`, `Field`, `Dialog`, `Table`, `StatCard`, `Money` tweaks. No layout change; every screen simply looks different. Check the nine existing tabs in both themes and both densities. (Biggest visual change per hour of work.)
2. **Shell.** Sidebar with modules and Soon chips, top bar with client and FY pickers, drawer under 1024 px, skip link, `/soon/$module`, the redirects, `/dashboard` as a stub that redirects to `/clients` until wave 5. Client-scoped routes stay; the tab bar moves into module tabs.
3. **Clients and the profile.** Clients list columns, profile with the checklist as top section, month strip, Team & details tab.
4. **Bank statements and Bookkeeping.** Statements tab (row-standing bar, assistant strip, upload states), Review re-skin (keyboard tests must still pass: `bulkPost.test.ts`), Day Book, Ledgers, Parties & rules, Books & sign-off.
5. **Reports, module landings, Dashboard, Work pipeline, Staff performance, Settings.** `ModuleClientTable` here. Dashboard v1 with the numbers available now; v2 numbers when gap B1 lands.
6. **GST reconciliation.** Types first (`types.ts`), then registrations and runs list, the run page, decisions dialog, sign-off, export.
7. **Polish and a11y pass.** Dark theme pass on every screen, 390 px pass, zoom 200% and 400% reflow, reduced motion, keyboard-only pass, `g`-prefixed jump keys (g d Dashboard, g c Clients, g b Bookkeeping, g s Bank statements, g r Reports; shown in the shortcut sheet and disabled when a field has focus). Then hand to the review team once ("verify once").

Backend work (section 6) runs in parallel: B1 must land before wave 5's v2 and before the client list is used at scale; B5 before wave 6.

---

## 6. Backend gaps

| # | Endpoint / field | Why | Priority |
|---|---|---|---|
| B1 | `GET /api/v1/firm/overview/` (or fold into `GET /clients/`): per client `{id, name, lead, stage, next_step{code,label,count}, unresolved, pending_approval, assistant_waiting, ai_unchecked (ai_posted + ai_revised), review_pending, signed_off_through, last_statement_end, months_missing[]}` plus firm totals and `by_stage` counts | The client list makes 3 requests per client (45 requests for 15 clients, measured; 384 for 128). The dashboard cannot show unchecked assistant entries, books awaiting sign-off, statements missing a month, or clients by stage without it. Same source feeds the pipeline board and module landings. | high |
| B2 | `GET /api/v1/team/members/` totals by day, or `GET /api/v1/firm/activity/?from&to` returning `by_day` for the whole firm | Dashboard "This month" chart otherwise needs one request per member | medium |
| B3 | Client fields: `pan`, `constitution` (proprietorship, partnership, LLP, company), `contact_name`, `contact_phone/email`, `status` (active, onboarding), and GSTINs in the list response | Mockup's client table and profile header; CAs identify clients by PAN and GSTIN. Not shown in phase 1 until present. | medium |
| B4 | `Statement` list: persisted `rows_posted`, `rows_ready_to_post`, `rows_need_ledger` (today only in the upload job's result) | Statements tab must show where each statement's rows stand after a refresh | medium |
| B5 | OpenAPI response schemas for GST (`RunCreate` documents only `registration`) and for `POST /clients/{id}/assistant/next-batch/` (not in `openapi.yaml`); also `/team/*` (hand-typed in `types.ts`) | Frontend types come from the schema; wave 6 needs them | high for wave 6 |
| B6 | Permission names for GST actions confirmed and exposed in `/me/` permissions | Which roles see Upload, Match, Decide, Sign off | medium |
| B7 | `client` filter on `GET /team/events/` and `GET /audit/` (confirm whether present) | Client profile Activity section; Activity log filter | low |
| B8 | Notifications, documents, tax, audit programme, compliance calendar, firm analytics | Coming soon; no API by design | none |

Not backed, therefore not designed: AI accuracy and time-saved metrics, risk scores, staff efficiency %, task priorities and due dates, compliance deadlines, hours worked.

---

## 7. Decisions the user needs to make

1. **Names.** Bank Statement AI to "Bank statements", Work Management to "Work pipeline". The cofounder's mockup uses the originals. Say if the cofounder insists; the spec works with either label.
2. **GST in phase 1.** The API is complete and has no screen. The spec includes it as wave 6 (largest wave). If phase 1 must ship sooner, GST can be a "Coming soon" item and waves 1 to 5 still stand.
3. **Dropping fake metrics.** The mockup's AI automation %, time saved, accuracy, risk labels and staff efficiency % are removed because nothing backs them. If the cofounder wants them, someone has to define how they are measured first.
4. **Fonts.** Inter and Fraunces need two packages (`@fontsource-variable/*`). Approve, or accept system fonts.
5. **Brand change.** Amber/navy goes; graphite/emerald/champagne replaces it, including the dark theme. The `₹` logo tile in the current sidebar needs a new mark (spec assumes the mockup's "CA" tile in emerald, text "AutoCA").
6. **Dashboard v1.** Ship it without unchecked assistant entries, books awaiting sign-off and missing-month counts until B1 exists, or hold the dashboard until B1?
7. **Coming soon visibility.** Default shown in the sidebar (7 items, muted). Alternative: hidden by default. The spec shows them and adds a preference to hide.
