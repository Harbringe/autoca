---
name: todo-open-list
description: One consolidated list of everything still open (2026-10-06), with what is stale; start here when asked for todos
metadata:
  type: project
---

**Decided 2026-10-06:** scanned invoices/statements go to the Bedrock vision route (user accepts sending page images there; AWS says no training on inputs); sealed-books correction = reversing journal dated in the open period; payroll + TDS challans + credit-card statements all wanted. Order: asset register, then TDS, then the rest.

**TOP PRIORITY (set 2026-10-06): role-based reporting dashboards.** Owner (FIRM_ADMIN), Senior CA, Staff dashboards on /dashboard by role, plus a plain-language per-client page. Plan: docs/dashboards-plan.md (wireframes, cards, data, build order). Decisions: Recharts approved, match app theme, push to dev only and do NOT deploy (prod) without the user's consent. Awaiting answers on: "on track/at risk" definition, per-person count tables for owner/senior, "assigned" = client assignments, drop "vs last week" on live figures, READ_ONLY gets owner layout without people table, "client dashboard" = internal page not a client login. Build order: chart kit, client page, owner v1, new endpoints (weekly flow, people counts, /me/work), senior, staff, role router. Already live: basic Portfolio tab + client FinancialSnapshot (15421ce), to be replaced.

**Added 2026-10-06 (second half), all on `dev` only, NOT deployed:** assistant strip now reads as live processing (no "paused" wording); sidebar remembers the selected client and lists its screens (lib/selectedClient.ts, ClientSection); alerts system (ledger/alerts.py computed, /firm/alerts + /clients/{id}/alerts, bell, /alerts page, per-module panels, portfolio attention built from it); OpenAI adapter (integrations/llm/openai.py, LLM_API_KEY/LLM_MODEL/LLM_BASE_URL/LLM_TEMPERATURE/LLM_TOKEN_PARAM) and scanned/partial-text PDF reading (banking/scan.py, VISION_READING=0 by default, VISION_PAGES_PER_CALL, VISION_DPI; PipelineTier.VISION, migration documents 0003). Waiting on the user: exact OpenAI model id, the India data-residency base URL from their OpenAI project, key set on the server with deploy/set-env.sh (never in chat). Not built: password-locked PDFs; India storage (S3 ap-south-1) not touched; secrets via GitHub Secrets discouraged for runtime keys (SSM command history), prefer .env.prod / AWS Secrets Manager.

**Building / next (code)**
- DONE + live (40cedda): asset register (API, screen, open item), depreciation booked as one Journal per FY (ledger/assets.py, DepreciationPosting), TDS position + challans + open items (ledger/tds.py, TdsChallan, TDS screen). Not built for TDS: quarterly return file/Form 26Q export, interest on late deposit.
- DONE + live (876275d): payroll (ledger/payroll.py: Employee with own ledger kept from the model, monthly PayrollRun = one journal, PF/ESI/TDS-192 payables; Payroll screen). Not built: settling the salary bank payment against the employee account automatically (a person places it), PF/ESI challan tracking, Form 24Q.
- Credit-card statements: read as a liability; charges become payables on the card account.
- Scanned invoices and scanned statements via Bedrock vision, background job, balance-chain proof still the gate; password-locked PDFs (see [[todo-scanned-and-locked-statement-pdfs]]).
- Correct a payment inside sealed books (reversing entry dated after the seal).
- Remember column choices per bank (parser); matching invoice -> existing bank row on upload is shown as a hint only.
- Speed up statement removal ([[todo-speed-up-statement-removal]]; Render-region worry is obsolete, query count still real).
- Per-party aliases for names sent to the model (A-03 uses a generic label) ([[todo-security-audit-fixes]]).

**Infra / user-side**
- Old AWS account <aws-account>: terminate test server, release Elastic IP, delete bucket. Stop Render/Vercel/Supabase/Upstash; delete the emptied R2 bucket. Remove temporary `autoca-backups-restore` policy if still attached. Confirm keys saved in a password manager.
- AWS KMS instead of the local master key; hash-locked Python deps; SHA-pinned CI actions; IAM/OIDC console checks; shared Redis cache (CACHE_URL) so throttles are not per process; login/MFA events into the per-firm audit table.

**Stale (safe to ignore)**
- [[render-502-upload-hotfix-pending]]: the app moved to AWS. [[todo-import-client-ledgers-from-tally]]: built (Tally chart import + party adoption + opening bills). First-admin question: owner account exists and is in use.
