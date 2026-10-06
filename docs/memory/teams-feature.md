---
name: teams-feature
description: "Teams/assignments feature built 2026-09-14 — design decisions, where the rules live, what's unverified"
metadata: 
  node_type: memory
  type: project
---

Built 2026-09-14 (uncommitted at the time): Senior CA teams, client leads, client assignments that limit visibility, sign-off limited to lead or firm admin, invite links, work tracking, team history. Design and decisions: docs/design-teams-and-assignments.md.

- Visibility rule lives only in core/access.py; team write rules in teams/service.py; sweep test teams/tests/test_access.py walks the router registry.
- Existing members kept scope_all_clients=True (still see everything); invites set False. Clients with no lead: any approver may sign off.
- Work counts: uploads/approvals/corrections from source tables; placements etc. from teams_activity_event (from release onward).
- No email service: invites are copyable links.
- Screens were not checked in a browser (the model must not type passwords into login forms); user should do a visual pass.

**Why:** User wanted a corporate-style hierarchy (firm admin → Senior CA → staff) with remapping and work tracking.
**How to apply:** Any new client-bearing endpoint must use core.access; see [[autoca-phase1-state]], [[removable-addons]].
