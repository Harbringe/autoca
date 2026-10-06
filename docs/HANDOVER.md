# Hand-over: where AutoCA stands (written 2026-10-07)

For a Claude session picking this up cold (for example a cloud session started with `claude --cloud`). Read this first,
then `docs/dashboards-plan.md`, `docs/SECRETS.md`, `docs/AWS.md`. Your own memory notes do not carry over.

## How to work with this user (standing rules)

- Small steps, one at a time, with detailed instructions; wait for "next" before giving the following step.
- **Never deploy to `prod` (or push to the `prod` branch) without the user explicitly saying so in that message.** `main` and
  `dev` do not deploy; only a green CI run on `prod` triggers the AWS deploy. Push work to `dev` (or a feature branch).
- Never ask for, paste or print secrets. Keys go into AWS (Secrets Manager / Parameter Store) or `deploy/set-env.sh` on the
  server, never into chat or git.
- Never use `git stash`. Do not spawn subagents unless asked. No local database: backend DB tests run only in CI, so push
  to `dev` and read the CI result (`gh run list`, `gh run view <id> --log-failed`). Fix lint (`ruff check .`) before commit;
  regenerate the API schema (`cd web && node scripts/gen-api.mjs`) whenever serializers or model choices change or CI fails
  the "schema is current" step.
- Data privacy: personal data is masked before anything reaches the model. Keep masking, encryption and row-level security.
- AutoCA is the firm's books of record. Every feature must link documents together; no islands.

## Deployed (prod = commit 91f30b0)

Firm portfolio dashboard and client snapshot, alerts system, sidebar remembering the selected client, live-processing wording,
OpenAI adapter (`gpt-6-luna`), scanned-PDF reading (off by default: `VISION_READING`), prompt-cache friendly requests and
identical-row collapsing, Parameter Store / Secrets Manager settings pull (`deploy/pull-secrets.sh`).

## On `dev` only (not deployed)

- Usage and cost tracking (`usage/` app, admin page at `/admin/usage/usageevent/`). CI green at a990133. Adds a migration.
- UI work in progress on branch `wip/alerts-ui` (if present): a Concur-style alerts bell dropdown, a de-duplicated sidebar, a
  compact "needs attention" banner. Unfinished; check `git diff dev..wip/alerts-ui`.

## Server setup state (the user does these in the AWS console; confirm before assuming)

1. IAM inline policy `autoca-read-parameters` on role `autoca-ec2-role` (ssm read on `/autoca/prod/*`, secretsmanager
   read on `autoca/prod/env-*`): done.
2. Secret `autoca/prod/env` holding the whole `.env.prod` text plus the OpenAI settings: done.
3. `sh deploy/pull-secrets.sh` on the server reported the five LLM settings updated. **Still to confirm:** the web container was
   restarted (`sudo docker compose --env-file .env.prod -f compose.prod.yaml up -d --force-recreate web`), `/healthz` is OK,
   and a synthetic statement gets assistant suggestions. Use test data only; the OpenAI project is global (India residency
   needs OpenAI sales approval; India is storage-only anyway), so keep `VISION_READING=false`.

## Open work, in the user's priority order

1. Role-based reporting dashboards (owner, senior CA, staff, client page): plan and wireframes in `docs/dashboards-plan.md`;
   Recharts approved; open questions in that file (on-track definition, per-person count tables, "assigned" meaning, no
   "vs last week" on live figures, read-only role layout, "client dashboard" means the internal page).
2. Finish and review the alerts dropdown / sidebar redesign (branch above), then deploy only on request.
3. Deploy usage tracking when the user says so.
4. Later: password-locked PDFs; scan reading needs the user's decision on page images leaving the country; AWS cost in the
   usage page via Cost Explorer; Bedrock (Mumbai) adapter if in-country inference is needed; sealed-books correction; TDS
   and payroll extras; speed up statement removal; security audit items A-01..A-16 in `docs/security-audit-2026-10-06.md`.
5. User-side cleanup: delete the old GitHub "Preview"/"Production" environments and revoke the Vercel app; stop Render,
   Supabase and Upstash; old AWS account cleanup.

## Pointers

- Alerts: `ledger/alerts.py`, `api/views/dashboard.py`, `web/src/features/alerts/`.
- Usage and cost: `usage/`; prices and budget in `config/settings/base.py` (`LLM_PRICES`, `USD_INR_RATE`, `LLM_MONTHLY_BUDGET_USD`).
- Model adapters: `integrations/llm/` (`groq.py`, `openai.py`); scans: `banking/scan.py`.
- Settings pull: `deploy/pull-secrets.sh`, `integrations/paramstore.py`, `deploy/import_env.py`.
