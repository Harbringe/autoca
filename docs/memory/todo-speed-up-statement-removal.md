---
name: todo-speed-up-statement-removal
description: "Deferred TODO (2026-10-03) - removing a statement takes ~4s because remove_statement deletes entries one at a time (~13 queries per entry); bulk rewrite designed, not built."
metadata:
  node_type: memory
  type: project
---

**TODO (not started, user asked to only park it):** make `banking/removal.py::remove_statement` fast.

**Why:** measured 2026-10-03 on the 54-row Axis 7214 statement with every row posted: 3,902 ms and 715 queries (13.2 per entry); one DB round trip from the dev machine to Supabase Mumbai is ~4.6 ms, so ~3.8 s of the 3.9 s is waiting on queries, Python is ~0.1 s. Per entry it runs: `is_locked` twice (2 `core_client` SELECTs, once in `remove_statement`'s locked check and once in `editing.require_editable`), a `select_for_update` fetch plus another entry SELECT, two `ledger_journal_line` SELECTs (snapshot + the delete's fetch), one `EntryChange` INSERT, two classification UPDATEs (`needs_review` and `_release_mirrors`), line and entry DELETEs, plus savepoints. Cost grows linearly with posted entries.

**Planned fix (nothing edited):** inside the same `@transaction.atomic`: check the client's `signed_off_through` once; load all entries + lines in two queries; `bulk_create` the `EntryChange` rows; bulk-update classifications; bulk-delete lines then entries, in layers so corrections (`supersedes`) go before what they correct. Target ~20-30 queries and ~0.15 s. Keep the all-or-nothing behaviour, the `entry_locked` refusal and the change-log content. Add a test that removes a many-entry statement with a hard cap on the query count (e.g. `django_assert_max_num_queries`).

**Bigger risk to check:** Render has no Mumbai region, and Supabase is `aws-0-ap-south-1`. If the Render backend runs in Singapore/elsewhere, each round trip may be tens of ms, so 715 queries could take 30-100 s and hit the proxy timeout (502) on the live site. Ask the user which Render region the service uses. The same one-at-a-time pattern likely exists in `approve_many` (posting) and upload; a full ingest + post + remove test run took ~25 s, not timed separately. The R2 file delete after commit was not measured.

**How to apply:** when the user returns to performance or statement removal, start from this plan; measure with a scratch pytest file outside the repo (`PYTHONPATH=/e/autoca`, `-p conftest`, cwd = scratch dir) as done on 2026-10-03. Related: [[aws-migration-and-bedrock-on-hold]] (keep app and DB in the same region).
