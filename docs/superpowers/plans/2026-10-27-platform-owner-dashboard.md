# Platform Owner Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give the platform owner a home page at `/admin/` that shows every firm at a glance and what needs doing today, and restyle the firm page and the add-a-firm page to match, in the web app's own look.

**Architecture:** Keep Django admin and the Jazzmin shell (sidebar, search, login, second factor). Add one stylesheet that paints the shell in the web app's palette and fonts, a pure data function that turns the existing gated platform views into the home page's numbers, and three template changes (home, firm page, add page). No new database views and no new JavaScript: filters are links, actions are links to existing admin pages.

**Tech Stack:** Django admin with Jazzmin, one app stylesheet served by WhiteNoise, pytest with the existing platform-admin fixtures.

**Spec:** The approved design canvas, https://claude.ai/artifact/7dMzCtrfud62xAx9ULkWvs (three artboards: Home, A firm, Add a firm), plus the scope calls below.

## Scope calls (made while planning; the canvas shows more than v1 builds)

- The Jazzmin sidebar stays; it is restyled, not replaced.
- Headline numbers: firms (with "new this week", from `created_at`), people, statements this month, model spend 30 days, needs-you count. No trend lines in v1: the views hold no history. Add trend lines only after a history table exists.
- "Recent activity" on home is assembled from three existing sources: firms created, invitations created or accepted, failed jobs. It is not the request audit log.
- The firm page's "What changed here" history is not in v1 (team events are not exposed through a platform view). Everything else on that artboard is.
- Dark mode is not in v1.
- The "Needs you" action buttons are links to the existing pages that already do the action (firm page, invitations list, jobs list). No new write paths.

## Global Constraints

- The admin is served under `_CSP_ADMIN`: `style-src 'self' 'unsafe-inline'`, `font-src` falls back to `default-src 'self'`. No Google Fonts link. Fonts are shipped as static files.
- Never open or source `.env*`. No real firm, payee or person names in code, tests, templates or sample data (public repo): use made-up names.
- No emoji, and no symbol characters used as icons. Icons are inline stroke SVG or Jazzmin's Font Awesome classes. Plain words for status ("Done", "Next").
- Only the platform owner sees any of it: reads go through the existing gated models (`PlatformFirmStats`, `PlatformInvite`, `PlatformJob`, `PlatformFirm`); nothing reads firm tables directly.
- Stage explicit paths only (never `git add -A`); never `git stash`; push to `dev` from `E:\autoca-merge` with `git push origin HEAD:dev`; deploy only when the user says so after CI is green.
- Rupees are shown as `Rs 1,120` (no decimals), computed with `usage.pricing.inr`.

## Review Focus

- No firms at all (fresh install): home renders with zeros and an "Add your first firm" prompt, no division by zero in usage bars.
- A firm with no limits (`max_members`/`max_clients` null): shows the count alone, no bar, never "of None".
- A firm name containing `<script>` or `&`: appears escaped everywhere on home.
- More firms than the table's page size (100): the table stops at 100 and says "Showing 100 of N, see all firms" linking to the full list.
- A firm with no model spend or never active: shows "-" and "never", not "Rs 0" or an error.
- A signed-in firm administrator (not the platform owner) opening `/admin/`: refused exactly as today.
- Trial ended/ending, quiet, at a limit and failed jobs each raise one attention item, and a healthy firm raises none.

---

## File Structure

- Create `superadmin/static/superadmin/platform.css`: palette variables, Jazzmin overrides, and every class the three templates use.
- Create `superadmin/static/superadmin/fonts/` : Inter and Fraunces variable woff2 (latin), with their licence files.
- Create `superadmin/home.py`: `build_home(now) -> Home`, pure over the gated models; no HTML.
- Create `templates/admin/superadmin/home.html`: the home page.
- Modify `core/adminsite.py`: `PlatformAdminSite.index` renders the home page.
- Modify `templates/admin/superadmin/platformfirm/change_form.html`: the onboarding stepper and limits cards.
- Create `templates/admin/superadmin/platformfirm/add_form.html` and modify `superadmin/admin.py` `PlatformFirmAdmin`: the three-section add page.
- Modify `templates/admin/base_site.html`: link the stylesheet, drop the old inline palette.
- Tests: `superadmin/tests/test_home.py` (new), additions to `superadmin/tests/test_superadmin.py`.

---

### Task 1: Theme and fonts

**Files:**
- Create: `superadmin/static/superadmin/platform.css`, `superadmin/static/superadmin/fonts/*.woff2` (copy from `web/node_modules/@fontsource-variable/inter` and `.../fraunces`, latin subset, plus their `LICENSE` files)
- Modify: `templates/admin/base_site.html`
- Test: `superadmin/tests/test_home.py`

**Interfaces:**
- Produces: CSS custom properties on `:root` (`--bg --fg --heading --card --surface-2 --primary --primary-fg --muted --muted-fg --faint --accent --accent-fg --border --border-strong --input --link --destructive --destructive-bg --success --success-bg --info --info-bg --warning-bg`, `--font-display`, `--font-sans`) with the exact light values from `web/src/styles.css`; and these classes used by later tasks: `.pf-card`, `.pf-kpi`, `.pf-chip` with `.pf-chip--good|warn|bad|info|mute`, `.pf-bar` (an element containing a `<meter>`-styled child), `.pf-btn`, `.pf-btn--primary`, `.pf-steps`, `.pf-grid`.

- [ ] **Step 1: Write the failing test** `test_the_admin_loads_the_platform_stylesheet_and_no_third_party_fonts`: sign in as the platform owner (fixtures `views`, `operator` imported from `superadmin.tests.test_superadmin`), GET `/admin/login/` is not enough (signed out), so GET `/admin/` and assert `superadmin/platform.css` is in the page and `fonts.googleapis.com` is not.
- [ ] **Step 2: Run it** `pytest superadmin/tests/test_home.py::test_the_admin_loads_the_platform_stylesheet_and_no_third_party_fonts --noconftest` is not possible (needs the DB); run in CI. Expected locally: not run; in CI before the change: FAIL.
- [ ] **Step 3: Implement** the stylesheet with `@font-face` rules pointing at `fonts/` by relative URL (so WhiteNoise's hashed names resolve), the variables above, Jazzmin overrides (navbar and sidebar `#161619`, active item `#22332f`, body `var(--bg)`, headings in `--font-display`), and the component classes. In `base_site.html` replace the inline `<style>` palette with `<link rel="stylesheet" href="{% static 'superadmin/platform.css' %}">` and `{% load static %}`.
- [ ] **Step 4: Verify** `python manage.py collectstatic --noinput --dry-run` lists the css and fonts; CI test passes.
- [ ] **Step 5: Commit** `git add superadmin/static templates/admin/base_site.html superadmin/tests/test_home.py` then `git commit -m "Platform admin: the web app's palette and fonts, self-hosted"`.

### Task 2: The home page's data

**Files:**
- Create: `superadmin/home.py`
- Test: `superadmin/tests/test_home.py`

**Interfaces:**
- Consumes: `PlatformFirmStats`, `PlatformInvite`, `PlatformJob` (`superadmin.models`); `QUIET_DAYS`, `TRIAL_WARNING_DAYS`, `_spend_by_firm` (`superadmin.admin`); `usage.pricing.inr`.
- Produces: `build_home(now: datetime) -> Home`, where `Home` is a dataclass with `kpis: list[Kpi]`, `attention: list[Attention]`, `rows: list[FirmRow]`, `total_firms: int`, `spend: list[SpendBar]`, `activity: list[ActivityItem]`; `Attention(firm_id, firm_name, tone, what, age_days, action_label, action_url)`; `FirmRow(firm_id, name, people_text, people_pct, clients_text, clients_pct, statements, last_seen, spend_text, status, tone)`; `tone` is one of `good|warn|bad|info|mute`; `*_pct` is `None` when the firm has no limit.

- [ ] **Step 1: Write the failing tests** (database, in CI), using the fixtures from `test_superadmin` and made-up firms: `test_an_empty_platform_gives_zeros_and_no_rows`; `test_each_attention_reason_raises_one_item` (trial ended, quiet 14+ days, at the people limit, a failed job, owner invite unopened for 7+ days) with the exact `what` wording; `test_a_healthy_firm_raises_nothing`; `test_a_firm_without_limits_has_no_percentage`; `test_rows_stop_at_100_and_report_the_total`; `test_spend_is_rupees_without_decimals_and_dash_when_none`.
- [ ] **Step 2: Run** in CI; expected FAIL (module missing).
- [ ] **Step 3: Implement** `build_home` in `superadmin/home.py`. Attention order: oldest first. Tone: `bad` for an ended trial or a failed job, `warn` for at-limit and unopened invite, `mute` for quiet. Action links use `reverse("admin:superadmin_platformfirm_change", args=[firm_id])` and the invitations and jobs changelists with `?q=<firm name>`. Must tolerate being called with the gated views empty.
- [ ] **Step 4: Run** CI; expected PASS.
- [ ] **Step 5: Commit** `superadmin/home.py superadmin/tests/test_home.py`.

### Task 3: The home page

**Files:**
- Create: `templates/admin/superadmin/home.html`
- Modify: `core/adminsite.py` (`PlatformAdminSite.index`)
- Test: `superadmin/tests/test_home.py`

**Interfaces:**
- Consumes: `build_home` and the `Home` shape from Task 2; classes from Task 1.
- Produces: `/admin/` renders `admin/superadmin/home.html` with context key `home`; tabs are links `?tab=all|attention|trial|healthy` that filter `rows` server-side.

- [ ] **Step 1: Write the failing tests:** `test_home_shows_the_headline_numbers_the_attention_list_and_every_firm`; `test_a_tab_narrows_the_firm_table` (`?tab=attention` hides a healthy firm); `test_a_firm_name_is_escaped_on_home` (name `<b>x</b> & Co`); `test_a_firm_administrator_still_cannot_open_admin` (existing behaviour, same status as today).
- [ ] **Step 2: Run** in CI; expected FAIL.
- [ ] **Step 3: Implement** `PlatformAdminSite.index(request, extra_context=None)` to add `home=build_home(timezone.now())` and render the new template, extending `admin/base_site.html`. Layout per the canvas: greeting header with "Add a firm" button, KPI strip, "Needs you today" card, firms table with tabs, right rail with spend bars and activity. Usage bars use `<meter>` or a width class from `platform.css` (`.pf-w-0` to `.pf-w-100` in steps of 5), never per-row inline math in the template.
- [ ] **Step 4: Run** CI; expected PASS. Compare against the canvas at 1440 px and at phone width (columns stack, table scrolls inside its box).
- [ ] **Step 5: Commit** `templates/admin/superadmin/home.html core/adminsite.py superadmin/tests/test_home.py`.

### Task 4: The firm page

**Files:**
- Modify: `templates/admin/superadmin/platformfirm/change_form.html`
- Test: `superadmin/tests/test_superadmin.py`

**Interfaces:**
- Consumes: existing context keys `onboarding`, `owner_link`, `onboarding_error`; classes from Task 1.
- Produces: the same panel restyled as the five-step tracker (each step labelled "Done" or "Next") and the limits card with usage bars.

- [ ] **Step 1: Write the failing test** `test_the_firm_page_shows_five_steps_with_done_and_next`: after creating a firm with an owner invite, the page contains "Owner invited", "Owner joined", "Authenticator set up", "First client added", "First statement uploaded", and exactly one more "Done" per completed step; the existing link-shown-once tests keep passing.
- [ ] **Step 2: Run** in CI; expected FAIL.
- [ ] **Step 3: Implement** the template changes only; no view changes except passing the people and clients usage figures if not already in `onboarding`.
- [ ] **Step 4: Run** CI; expected PASS.
- [ ] **Step 5: Commit.**

### Task 5: The add-a-firm page

**Files:**
- Create: `templates/admin/superadmin/platformfirm/add_form.html`
- Modify: `superadmin/admin.py` (`PlatformFirmAdmin.add_form_template`)
- Test: `superadmin/tests/test_superadmin.py`

**Interfaces:**
- Consumes: the existing `FirmForm` fields (`name`, `owner_name`, `owner_email`, `max_members`, `max_clients`, `trial_ends_on`, `is_active`) and the `response_add` redirect to the firm's page.
- Produces: the same form rendered as three numbered sections with a "what happens next" panel; field names and POST behaviour unchanged.

- [ ] **Step 1: Write the failing test** `test_the_add_page_has_three_sections_and_the_same_fields`: GET `/admin/superadmin/platformfirm/add/` contains the three section headings and the form still posts successfully (reuse the existing creation test).
- [ ] **Step 2: Run** in CI; expected FAIL.
- [ ] **Step 3: Implement** the template extending Jazzmin's change form and rendering each form field by name inside its section; keep CSRF and error display.
- [ ] **Step 4: Run** CI; expected PASS.
- [ ] **Step 5: Commit.**

### Task 6: Release check

**Files:** none new.

- [ ] **Step 1:** Run the full suite in CI on `dev`; all three jobs green.
- [ ] **Step 2:** Hand the user the deploy command; after deploy, check `/admin/` as the owner against the canvas, open a firm, open the add page, and confirm a signed-in firm administrator still gets refused.
- [ ] **Step 3:** If `collectstatic` ran in the image build, nothing else is needed; there are no migrations in this plan.
