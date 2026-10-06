---
name: render-502-upload-hotfix-pending
description: "Statement-upload 502 on Render: root cause (model call sleeps inside the upload request) and the no-wait hotfix, pushed to origin/main on 2026-10-03 as 7461dbe; Render redeploy not yet confirmed by the user."
metadata:
  node_type: memory
  type: project
---

**UPDATE 2026-10-03 (later):** `preview/r2-redesign` was promoted to `main`: all working-tree work committed (49abd4d), origin/main (incl. the hotfix) merged in, two Tally-import bugs fixed (ad44f75), full backend suite + frontend typecheck/build/173 tests green, then `origin/main` fast-forwarded 7461dbe -> ad44f75 and the branch pushed. The user ran `migrate --database=owner` (ledger 0009/0010, new Tally tables) and `grant_app_role` themselves against the shared Supabase DB BEFORE the push (the auto-mode classifier blocked me from running them). Not yet confirmed: Render/Vercel redeployed and a real upload works. Note: local `.env` points at the same Supabase DB as production, so dev and prod share one database. The no-wait hotfix and the queue now coexist on main. The text below describes the earlier hotfix-only state.

**State as of 2026-10-03 (earlier):** hotfix PUSHED to `origin/main` (fast-forward `42fe243..7461dbe`, commit "Never sleep on the model's rate limit inside an upload request"). Whether Render auto-deployed it and whether the 502 is gone is NOT yet confirmed; the user has to watch the Render deploy and retry an upload.

**Original problem:** a friend's live deployment (Render backend `<old-host>`, Vercel frontend `<old-host>` with `/api/*` rewrites) showed "The server answered 502" on statement upload. Render logs showed every upload logged `202`, so the 502 came from the proxy in front of Django, not the app.

**Root cause:** `main` runs the Groq model tier inside the upload request (`_ingest` -> `suggest_unresolved`). The Groq plan allows 8,000 tokens/min and a 25-row batch needs ~8-10k, so the adapter split the batch and slept 40-60s between attempts; one request ran 2-3 minutes.

**What the hotfix does:** `classify/llm._suggest` now uses `get_llm().without_waiting()` (new no-wait Groq twin: one attempt, 15s timeout, typed `LLMRateLimited` instead of sleeping; ported from `preview/r2-redesign` integrations/llm/{base,groq}.py). A rate limit stops the run, rows already answered are kept, the rest stay unplaced for a person. Consequence: on this Groq plan only a few rows per upload get AI suggestions.

**Not done / caveats:** the real fix (the queue: `classify/queue.py`, `mark_waiting`, `process_next_batch`) exists only on `preview/r2-redesign` (297 files ahead of main, plus ~160 uncommitted/untracked files incl. Tally import and migrations 0016/0017) and is not shipped. Lesson: local `main` had been stale (behind origin by PR #1); always `git fetch` and compare to `origin/main`, not local `main`. Worktree `E:\autoca-hotfix` (branch `hotfix/no-wait-model-upload`) still exists and holds copied gitignored `.env`/`.env.test`; delete it when done.

**How to apply:** if the user reports uploads still failing, check Render deploy logs first (did 7461dbe deploy?), then look for sleeps/timeouts. Related: [[todo-scanned-and-locked-statement-pdfs]], [[aws-migration-and-bedrock-on-hold]].
