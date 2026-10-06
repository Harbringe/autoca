---
name: web-frontend-and-ca-reviewer
description: "The rebuilt web frontend (web/, separate from Django, Tauri-portable) and the CA reviewer agent loop used to QA it; how to run both"
metadata:
  node_type: memory
  type: project
---

On 2026-09-24 the old `frontend/` was deleted and a new app is being built in `web/` (React 19 + Vite + TanStack Router/Query + shadcn/Tailwind, TypeScript 5.9 — TS 7 breaks openapi-typescript). Django no longer serves any frontend; `FRONTEND_URL` (env, required in prod) says where it lives. Only `web/src/platform/` may know about Tauri. Plan: `<local path>`, milestones M1 (shell/auth/clients) to M7 (Tauri spike).

**Why:** user wanted a CA-friendly UI (Tally-style keyboard use, lakh grouping, Dr/Cr, DD-MM-YYYY, FY Apr-Mar), fully decoupled from the backend, portable to Tauri.

**How to apply:**
- QA loop: `python scripts/qa_seed.py` makes a synthetic firm (admin/senior/staff, password in the script; `--teardown` removes it). The dev DB is the shared Supabase project and there is no local Postgres/Docker, so keep it tidy with `--reset` after test rounds. The `ca-reviewer` agent (`.claude/agents/ca-reviewer.md`, brief in `web/qa/CA_REVIEWER.md`) drives headless Playwright against http://<ip>:5173, writes `web/qa/findings/<milestone>.md`; devs fix, reviewer re-verifies. Run it at each milestone gate; new agent files need a session restart to register, else spawn general-purpose with the brief.
- Never run two pytest processes at once: the test DB is shared and concurrent runs corrupt each other.
- Check in with the advisor at milestone boundaries; ask the user before committing each milestone (work is on branch `web-frontend`, uncommitted).
- Decisions (2026-09-26): staff may post and correct on assigned clients; only lead/admin sign off, return, reopen. Auto-posting on upload stays, but the CA must be able to unpost assistant-posted entries (per entry and in bulk) back to Review. The model may auto-post too (user chose "AI too, with guards" on 2026-09-26, after it posted 14 UPI self-transfers as cash): never an electronic-channel row to a CASH ledger, never to a model-opened ledger no person has posted to yet (`ledger/approval.py` auto_post). Commit on branch `web-frontend` after each review round is fixed.
- Run Python as `.venv/Scripts/python` from E:/autoca (plain `python` lost Django after a restart). Upload only synthetic PDFs from `web/qa/tools/make-statement.mjs` (distinct --holder/--account per client); never re-upload the user's real statement: removals leave its narrations in append-only audit tables. Exception: on 2026-09-26 the user explicitly chose to upload `<a real statement file>` to client "QA Statement Review" (Groq on) for a full-flow test; ask again before any further real upload.

