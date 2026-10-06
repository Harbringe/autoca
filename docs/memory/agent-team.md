---
name: agent-team
description: "The 9-agent AutoCA review/dev team in .claude/agents (orchestrator + devops, ux-critic, security-auditor, api-qa, two CA reviewers, backend-dev, frontend-dev); how to start it and the safety rules it runs under"
metadata:
  node_type: memory
  type: project
---

Created 2026-09-28. Agents live in `.claude/agents/` (gitignored, so local only); the shared rules are `web/qa/TEAM.md` (tracked). Start with `claude --agent orchestrator` from E:\autoca: only the main agent can dispatch subagents, so the orchestrator (opus) cannot be a subagent. Others are sonnet. Findings go to `web/qa/findings/<round>/<agent>.md`, board in `BOARD.md`. New agent files need a Claude Code restart to register. Reuses `web/qa/CA_REVIEWER.md`, `CA_API_REVIEWER.md`, `scripts/qa_seed.py`.

**Why:** user wanted a project-manager orchestrator plus specialist testers and developers working as a team on the product, which is now deployed (Render `<old-host>`, Vercel `<old-host>`).

**How to apply:** the local `.env` points at the same Supabase DB that production and the cofounder use, so the team's rules matter: synthetic `QA ` data only; real statements only with the user's quoted approval per file; nobody pushes `main` (auto-deploys) or commits without approval; work goes on branch `team/<round>`; only backend-dev runs pytest, one at a time; no active tests against deployed URLs; no reading `.env`; migrations are flagged and held because Render has no pre-deploy migrate step. See [[web-frontend-and-ca-reviewer]] for the earlier single-reviewer loop.
