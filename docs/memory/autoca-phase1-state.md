---
name: autoca-phase1-state
description: "Where the AutoCA build stands (Sept 2026) and the user's standing decisions — Groq for LLM, no Tally to test against, any-bank parsing, frontend rebuilt separately in `web/`."
metadata: 
  node_type: memory
  type: project
---

As of 2026-09-13 AutoCA Phase 1 (bookkeeping) is built end to end: security hardening, Groq model tier (off by default, `LLM_BACKEND` stub), the old React frontend (deleted 2026-09-24 and being rebuilt as `web/`, see [[web-frontend-and-ca-reviewer]]), Dockerfile + compose. GST (Phase 2) is an empty placeholder. Excel/CSV statements and OCR are not done (user said ignore OCR for now).

**Why:** User asked (2026-09-13) for "phase 1 ... only bookkeeping ... with the frontend with proper security guard rails ... groq for llm ... enterprise grade". Earlier they said there are no fixed banks (any bank must work) and they have no Tally to test the export against.

**How to apply:** Don't add per-bank parsers or a Tally round-trip test; don't wire OCR vendors. Keep the LLM pseudonymised. (The old "capped below HIGH band" rule is gone: the code deliberately lets the model reach HIGH and auto-post; see [[web-frontend-and-ca-reviewer]] for the guards the user chose on 2026-09-26.) The Groq account is on a free-style plan with 8,000 tokens/minute; one classification batch is ~5.6K tokens of fixed context, so a 264-row statement takes many minutes and needs the pacing in `integrations/llm/groq.py`. As of 2026-09-14 Groq is live in `.env` with `GROQ_MODEL=openai/gpt-oss-120b` (the old llama-3.3 default was decommissioned; the key was replaced on 09-14 after the old one returned 401). `.env` has `MFA_DISABLED=1` for local testing, so Claude can sign in itself. A full role-based QA report is at `docs/QA-2026-09-14.md`; R2 uses a bucket-scoped `<bucket token>` token. Seeded charts of accounts are only ~4 ledgers, so the model declines most rows until real ledgers are added. For UI testing use the synthetic QA firm from `scripts/qa_seed.py` (Claude can sign in itself with headless Playwright), not the demo login. Dev DB is the shared Supabase project: clear real client statement data (demo firm `<id>`) after manual test rounds.
