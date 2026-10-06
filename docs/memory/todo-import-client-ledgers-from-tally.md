---
name: todo-import-client-ledgers-from-tally
description: "Deferred TODO - let a firm import a client's existing ledger list from their Tally as the client's default chart of accounts. Not started; user said do not build yet."
metadata: 
  node_type: memory
  type: project
---

**TODO (not started, user asked to only record it):** offer an option to import a client's ledgers from their Tally, so the client's own chart becomes the default instead of names we invent.

**Why:** today `classify/seeds.py` seeds only 4 ledgers per client (Bank Interest Received, Bank Charges, Cash-in-Hand, Suspense A/c) and the ~50-name `classify/standard_ledgers.py` list only steers AI proposals. A seeded name that differs from the client's Tally name (e.g. "Rent" vs "Office Rent") makes the Tally export silently create a second ledger and split the books. Importing the client's real ledger names removes that risk. Discussed 2026-09-19.

**How to apply:** when the user returns to default ledgers or client onboarding, raise this first. Keep the small universal seed alongside it. Still undecided and worth asking: whether clients usually already have Tally files, whether defaults should exist at client creation or grow per statement, and proprietor vs company mix (affects Drawings/Capital). An opt-in "starter chart" template by business type was floated as a quicker alternative for clients with no Tally history. Related later seeds tied to features: GST ledgers once a client has a GSTIN, "Difference in opening balances".
