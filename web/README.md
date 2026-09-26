# AutoCA web

The web application for chartered-accountant firms: a React single-page app
that talks to the AutoCA backend only through its REST API. It is a separate
project from the backend -- its own dependencies, build and deployment -- and
is written so it can move into a Tauri desktop shell without a rewrite.

## Run it

Two servers, from the repository root:

```bash
python manage.py runserver 127.0.0.1:8000     # the API, and the platform admin at /admin/
cd web && npm ci && npm run dev               # this app, at http://localhost:5173
```

The dev server forwards `/api`, `/auth`, `/healthz`, `/admin` and `/static` to
Django, so the browser only ever talks to one origin. That keeps the session
cookie first-party and CSRF the ordinary same-site flow: there is no CORS in
this project and none should be added.

| Variable | Where | What it does |
|---|---|---|
| `VITE_DEV_API` | dev server | Where Django is, if not `http://127.0.0.1:8000`. |
| `VITE_API_BASE` | build | Prefix for every API call. Leave empty on the web; a desktop shell sets the server's absolute URL. |
| `FRONTEND_URL` | Django | Where this app is served. Django redirects `/` there, and invitation links and the trusted CSRF origin are built from it. |

For local sign-in without an authenticator, run Django with `MFA_DISABLED=1`
(it is honoured only when `DEBUG` is on).

## Scripts

| | |
|---|---|
| `npm run dev` | Dev server with hot reload. |
| `npm run typecheck` | Regenerates the route tree, then `tsc --noEmit`. |
| `npm run lint` | oxlint. |
| `npm test` | Vitest. |
| `npm run build` | Typecheck, then a production build into `dist/`. |
| `npm run gen:api` | Regenerates `openapi.yaml` from Django and `src/api/schema.d.ts` from that. Run it whenever a backend serializer changes; CI fails if the checked-in schema has drifted. |

## Deploy

`npm run build` produces static files. Host them anywhere that can rewrite
paths, with these rules, in this order:

1. `/api/*`, `/auth/*`, `/healthz`, `/admin/*`, `/static/*` -> the Django server
   (a rewrite, not a redirect, so the browser stays on this origin).
2. Everything else -> `index.html` (the router takes it from there).

Then set `FRONTEND_URL` on the Django side to this site's address.

## How it is laid out

```
src/
  platform/    the only place that knows "web page" from "desktop shell"
  api/         the typed client, error model, and query hooks per area
  session/     sign-in as a state machine: password, second factor, ready
  components/  ui/ (shadcn, owned here) and ca/ (Money, page furniture)
  features/    one folder per part of the product
  lib/         formatting (lakh grouping, DD-MM-YYYY, FY), preferences, hotkeys
  routes/      TanStack Router file routes
qa/            the CA reviewer: brief, tools, and findings (see qa/CA_REVIEWER.md)
```

### Types

Almost everything is typed from the backend's OpenAPI schema
(`src/api/schema.d.ts`, generated). Team, firm, audit and the `/auth/*`
endpoints are plain Django views the schema cannot describe; their shapes are
written by hand in `src/api/types.ts`, from the views that produce them.

### Money and dates

Every amount arrives as integer paise with a formatted `*_display` beside it.
Show the display string; do arithmetic on paise; never use floats. Format
anything else with `src/lib/format.ts` (lakh grouping, two decimals, `Dr`/`Cr`
for balances). Dates are `DD-MM-YYYY`, the year is `FY 2025-26`, April to March.

### Moving to Tauri

Only `src/platform/` changes:

- `http.ts`: install the shell's HTTP client with `setTransport` so cookies
  live on the native side, and set `VITE_API_BASE` to the server's URL.
- `download.ts`: install a native "save as" with `setSaver`.
- `links.ts`: open external links with the shell's opener via `setOpener`.

Nothing under `features/` reads cookies, opens windows, or triggers downloads
itself. Add the shell's origin to Django's `CSRF_TRUSTED_ORIGINS`.

## Testing as a chartered accountant

`qa/CA_REVIEWER.md` describes a reviewer who signs in as each role in a
synthetic firm (`python scripts/qa_seed.py`), uses the running app, checks
figures against the API and Indian accounting conventions, and writes findings
to `qa/findings/`. Developers fix; the reviewer re-verifies.
