# Security review, 2026-10-10 (before the deploy of the locked-PDF / aliases / rectify / stock / TDS-return work)

Scope: the audit of 2026-10-06 re-checked against the code, plus everything added since.

## Earlier audit items, re-checked

| Item | Now |
|---|---|
| A-02 regex rules / ReDoS | `classify/regex_guard.py` is in place |
| A-04 public API schema | `SERVE_PERMISSIONS` requires login |
| A-07 upload limits | `DATA_UPLOAD_*` limits and `upload` throttle (120/hour) set |
| A-08 login throttle | sign-in counted three ways (address+account, address, account) |
| A-05, A-06, A-10, A-11, A-14 | infrastructure / process items; unchanged and still listed in the audit document (KMS move, hash-locked dependencies, SHA-pinned actions) |

## New surfaces reviewed

- **PDF passwords**: write-only field; hidden from error reports with `sensitive_post_parameters` on `dispatch` (on the method it
  crashed every upload, found by CI and fixed); never stored, logged or echoed in errors (tested); the file is stored as it came.
  A locked scan renders at most the model's page cap while the password is to hand.
- **Names sent to the model**: person aliases keyed with the blind-index key and scoped per client; person-named loan/capital
  ledgers are tokens turned back on our side.
- **Rectifying journal**: lead or firm admin only, reason required, party and bank/cash ledgers refused, dated after sign-off,
  original untouched and its change log records it.
- **Stock entries, TDS return pack, paid-from**: all behind the per-client scoped viewsets and firm permissions; stock has
  row-level security and is in the isolation suite; every text cell in the TDS workbook goes through the spreadsheet formula
  guard (a review found three unguarded cells; fixed). Paid-from looks the account up by firm and client and refuses a bank
  with uploaded statements (would double-book).
- **Debug archive / live settings**: both off unless explicitly switched on; the archive bucket is the user's to create.

## Still open (not code)

AWS KMS move, hash-locked dependencies and SHA-pinned CI actions, shared cache backend, login/MFA events in the per-firm audit
table. See the audit document.
