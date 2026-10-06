---
name: removable-addons
description: Operator/convenience features (e.g. super admin console) must be isolated so they can be deleted easily
metadata: 
  node_type: memory
  type: feedback
---

Build operator-only or experimental features as a self-contained unit (own Django app + own frontend folder, tiny hooks into existing code, reversible migrations, documented removal steps).

**Why:** When asked for a super admin view (2026-09-14), the user said "make it in a way where i can remove it later very easily".

**How to apply:** Keep core free of imports of the add-on; use generic settings hooks; list every hook line and a removal procedure in the add-on's README. See [[autoca-phase1-state]].
