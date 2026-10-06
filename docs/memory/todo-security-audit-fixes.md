---
name: todo-security-audit-fixes
description: "Open fixes from the 2026-10-06 security audit (A-01..A-16), agreed order, plus the consistent-aliasing design for names sent to the AI model"
metadata:
  node_type: memory
  type: project
---

Full report: `docs/security-audit-2026-10-06.md` (16 findings, file:line, repro, fix direction). Audit was code-reading only (local .env DB is dead); no cross-firm access found, RLS/triggers/secrets clean. **Done and live 2026-10-06 (3cf1d3b, deployed, healthz 200): A-01..A-07, A-09, A-12, A-13** (A-06 = migration core 0013 append-only + audited GET of bank account/doc download; A-07 = GST xlsx guards + api/throttles.py per-person upload/model limits) (plus 1d party reports/To-fix screen live). **Also done and live (a18a067): A-08 (sign-in per address+account+address-only lines), A-10 (deploy.sh moves to exact commit; CI permissions read), A-11 (W017 warning only), A-14 (urllib3 floor), A-15 (pg_temp last, superadmin 0008).** Still open / user-side: move to AWS KMS (A-11 real fix, infra), hash-locked Python deps and SHA-pinned CI actions (A-10/A-14 remainder), IAM/OIDC console checks (A-10), cache is locmem unless CACHE_URL set (throttles per process), login/MFA events not in per-firm audit table, A-16 accepted. Then roadmap: 1e Tally openings/linking, invoice reading, matching, GST tie-in, assets, payroll/TDS/cards, close screen. A-03 uses a generic label ("a party's own account"), not per-party aliases; A-02 guard is `classify/regex_guard.py` (parsed-pattern walk, 300-char text cap).

**Agreed order (separate commits, push only after the in-flight CI run finishes so it isn't cancelled):**
1. A-03 High: real party names reach Groq (`classify/llm.py` `_context_for` sends `booked_to` ledger names without the party-account exclusion; Tally-imported debtor/creditor/loan ledgers have no Party row). Fix = alias through the same mapping as payees, don't drop.
2. A-01 High: `ledger.manage` can PATCH ledger group/name/is_active after posting/sign-off (`api/serializers/classify.py:45-51`, `api/views/classify.py:83-100`); reports read group live. Make read-only once posted (Tally import already has this rule); bank ledger rename breaks bank-account link.
3. A-02 Medium (confirmed): rule-regex validator bypassed by alternation (`(a|aa)+$`).
4. A-04 Medium (confirmed): OpenAPI schema/Swagger/Redoc public; set `SERVE_PERMISSIONS`.
5. A-05 admin login no throttle; A-06 audit log not append-only in DB + downloads/decrypts not audited; A-07 GST xlsx no size/row guard.
6. Lower: A-08 login throttle keyed on email only; A-09 POST bank-accounts routable; A-10 deploy ships branch tip not tested commit, CI lacks `permissions:`; A-11 KMS/blind-index keys in web container env; A-12 `get_user` ignores is_active; A-13 money fields unbounded (500); A-14 unpinned transitive Python deps (urllib3 2.7.0 advisories); A-15 SECURITY DEFINER search_path; A-16 model-only rows can auto-post (accepted D1=B).

**Aliasing design (discussed, not built):** keep masking as is ([[autoca-phase1-state]]). Consistent pseudonymisation: stable token per name from a keyed hash of the normalised name (use the existing blind-index key), scoped per client (not across clients), applied to ledger names, party names and names inside narrations alike; reverse-map on our side only. Decide a clear rule for which ledgers count as party names. Verify `classify/llm.py` first to see exactly which fields go out.

**Why:** user asked for these to be saved before sleeping, 2026-10-06. **How to apply:** start with A-03 then A-01; see [[feedback-no-islands-reconcile-everything]] for the general build rule.
