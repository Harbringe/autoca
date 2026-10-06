# Hand-over: alerts UI work (branch `wip/alerts-ui`, head 50ad0f6)

For the local session picking this up. Read `docs/HANDOVER.md` first for the standing rules (never push to `prod`
without being told in that message, no `git stash`, no secrets in chat, push to `dev` or a feature branch).

## State

- Branch `wip/alerts-ui` is pushed to origin and checked out here. Nothing was pushed to `prod`, `dev` or `main`.
- `cd web; npm run typecheck; npm run lint; npm test` all pass: 38 files, 276 tests.
- Not yet looked at in a real browser at any width. Do that next (see "Next steps").

## What the cloud session did (3 commits on top of fba30c9)

1. **9f136ad (earlier work, reviewed)**: alerts bell as a dropdown (`web/src/features/alerts/AlertBell.tsx`), one
   de-duplicated sidebar (`web/src/lib/sidebarNav.ts`, `web/src/features/shell/Shell.tsx`, `ClientSection.tsx`),
   compact in-page banner, `web/src/components/ui/popover.tsx`.
2. **9bd0dec, mobile fixes**: 44px touch targets for the bell and account buttons below `sm`, filter chips 40px on
   phones, tighter top-bar padding and gaps, narrower financial-year select on phones (`w-[5.75rem]`), more padding on
   the bell panel footer.
3. **50ad0f6, Concur-style "View alerts" button**: `ModuleAlerts` in `web/src/features/alerts/AlertList.tsx` is no longer
   a collapsible banner. It is one right-aligned "View alerts (N)" button (icon red when any alert is urgent) that opens
   a popover: title with count and urgent count, a close (X) button, a scrollable list of `AlertRow`s most serious
   first (each row links to where it is fixed and closes the panel), and an "All alerts" link scoped by module/client.
   It renders nothing when there are no alerts. Call sites are unchanged: `features/shell/ModuleClientTable.tsx` (firm
   scope) and `features/clients/Workspace.tsx` (client scope). New test: `features/alerts/ModuleAlerts.test.tsx`.

## Why (the user's request)

The user showed screenshots of SAP Concur: a single "View Alerts" button on the page opens a panel of all alerts for that
page, each with a "View" link, plus a close button; the claim header also lists the alerts inline. They want the same:
click one thing for all alerts, easy to navigate, and "the place of the alert will of course show the alert as well".

## Next steps

1. Run the web app locally and check the bell panel and the View alerts panel at 360px, 768px and desktop widths, in
   light and dark. Check the top bar at 360px (menu, client picker, FY select, bell, account) does not overflow.
2. **Not done: in-place markers.** The alert should also show at the exact spot of the problem (a warning on the bank
   review row, the GST return, the field) and not only in the panel. This needs per-screen work. Ask the user which
   screen to start with; bank review rows and GST returns are the likeliest. Reuse `SeverityMark` and the alert `kind`.
3. Not reviewed: `ClientSection.tsx` and `sidebarNav.ts` were not read in the cloud session (only their tests pass).
4. Decide with the user whether to merge into `dev`. Deploying to `prod` only on their explicit word.
5. Wider open work is unchanged and listed in `docs/HANDOVER.md` (role-based dashboards are the top priority).
