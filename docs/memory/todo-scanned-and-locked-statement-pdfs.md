---
name: todo-scanned-and-locked-statement-pdfs
description: Deferred TODO (2026-10-02) - support scanned/image bank-statement PDFs via a vision model and password-protected PDFs. Designs agreed in discussion; nothing built.
metadata:
  node_type: memory
  type: project
---

**TODO (not started, user asked to only log it):** two statement-intake gaps found when a friend's firm on the Render deployment uploaded real statements. Today `banking/parsers/__init__.py` refuses any PDF with no text layer (OCR is `integrations/ocr/stub.py`, "not wired yet"), and password-protected PDFs have no handling at all (`integrations/pdf/base.py` lumps encrypted with corrupt under `PdfExtractionError`, so the user likely sees a misleading "damaged file, re-download" message - not verified by running a locked PDF).

**Scanned / image PDFs - direction the user leaned toward:** skip classic OCR (user has seen it cause many issues); send page images straight to a vision-capable model that returns structured rows (date, narration, debit, credit, balance + header: account no., bank, period), fed into the existing balance-chain proof as a hard gate. Mark the statement "read from a scan"; require a person to confirm opening/closing balance. Plug in at the `integrations/ocr` adapter slot. Caveats raised and not yet decided:
- Privacy: images cannot be masked like narrations are, so the provider sees the whole page. Needs the user's call on sending page images to an outside provider.
- Needs a paid vision-capable key (current Groq free plan is 8,000 tokens/min and already saturated); provider/budget not chosen.
- Slow, so it must run as a background job, not inside the upload request (see [[render-502-upload-hotfix-pending]]; the queue in `classify/queue.py` on `preview/r2-redesign` is the same pattern).
- Check the chain across page joins for long statements.

**Password-protected PDFs - decided by the user:** store the original exactly as uploaded (still locked); never keep an unlocked copy; never store the password; ask for the password every time the file needs processing (upload and any reprocess). Wrong password gets its own clear error, not "damaged". Planned shape: optional `password` through `PdfTextAdapter.page_count`/`extract`, separate `password_required` / `password_incorrect` error codes in `core/jobs.py` and the API, a password field in the upload dialog, tests including "password never appears in logs, errors or the database".
- Open tension: a background job cannot ask for the password later. Plan: unlock while the user is present (in the upload request); for locked scans hand the job only temporary page images, deleted when it finishes. Suggested to build locked text PDFs first and design the scan path to follow.

**Why:** the friend's real statements were image-only PDFs, and emailed Indian bank statements are usually password-locked, so both are likely common in real use.

**How to apply:** when the user returns to statement intake, start from these decisions rather than re-asking; the open questions are (1) cloud vision provider acceptable and which one/budget, (2) whether locked scans wait for the later phase.
