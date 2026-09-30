# Redesign r2 progress log (frontend-dev)

Spec: redesign-r2.md; overrides: web/qa/findings/r1/BOARD.md "Redesign decisions". Branch team/r1, nothing committed.

## Log
- [start] Read spec, TEAM.md. Installed @fontsource-variable/inter and @fontsource-variable/fraunces (package.json/lock only).
  Next: wave 1 tokens (styles.css), primitives.
- [wave 1 done] styles.css tokens (light+dark, fonts self-hosted via fontsource), Button (loading), Badge (tone+auto icon, CountChip), Card (tone), Input/Select/Textarea, Field (error icon, `mask` -> 2nd render arg), Dialog (fade only, sheet under 640), DropdownMenu, ui/table.tsx (DataTable), ui/stat-card.tsx, Money (dash for muted zero, compact), format.formatCompact, lib/masks.ts (+tests). Old amber/navy classes recoloured in screens (bg-warning/10 -> bg-accent etc.).
  typecheck/lint/test pass. Next: wave 2 shell.
  Deviations so far: Money `symbol` default not changed per-DataTable (server strings are shown as sent).
- [wave 2 code written] lib/modules.ts (+tests: moduleOf, switchClientPath), Shell.tsx rewritten (grouped sidebar, Soon chips, bank count, top bar with client picker (opens palette) + FY picker (client: useFy; All clients: `?fy=`), palette trigger, assistant slot = null, drawer on Radix Dialog under 1024, skip link, landmarks), ui/tabs.tsx, Workspace module tab rows, routes: / -> /dashboard -> /clients, /soon/$module, /pipeline, /bookkeeping /bank /reports (Pick a client), /gst -> /soon/gst, /staff (+/work redirect keeping search), /settings/{team,firm} (+/team,/firm redirects), palette Go-to modules + All clients + module-preserving client switch.
  Deviations: GST shown as "Soon" until wave 6 (/gst redirects to /soon/gst). Client picker reuses the palette (no separate combobox, no recents/lead rows). Hotkeys g w/g t/g f retargeted to /staff, /settings/team, /settings/firm; no new global g d/g s (wave 7).
  Next: verify with snaps (admin, staff; light, dark, 390 + drawer), fix issues, final checks.
