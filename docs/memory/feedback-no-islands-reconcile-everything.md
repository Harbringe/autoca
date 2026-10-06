---
name: feedback-no-islands-reconcile-everything
description: "Core product rule from the user: raw documents are separate islands; AutoCA's value is linking and reconciling them all into one set of books. Think twice before implementing any feature and check it for new islands."
metadata:
  node_type: memory
  type: feedback
---

The user (2026-10-05, stressed "very crucial"): every kind of document a CA firm receives (bank, loan and card statements, purchase and sales invoices, GST registers and 2B, assets, payroll, Tally openings) is raw data, and raw data on its own is an island. The app exists to reconcile them together so they make sense as one set of books. Also: "think twice before implementing a feature about how it can be implemented properly, are there any issues with that implementation".

**Why:** a feature that adds a new document type or table but does not link to the others is worth little to a CA; the reconciliation across documents is the product. `gst/` is today's example of an island (it compares registers with 2B and never reads the ledger); the user does not want more of those.

**How to apply:** before building any feature, (1) say what the new thing links to and by what shared key (GSTIN + invoice no + date, party, ledger, bank row, document id), (2) check whether another table already holds the same fact and would become a second copy, (3) make unmatched or orphaned items visible as open items instead of silent, (4) design the cross-links first and the screens after, (5) list the risks of the chosen implementation before writing code. See [[books-of-record-and-full-reconciliation]].
