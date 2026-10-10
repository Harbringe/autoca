# GSTIN verification against the GST portal: plan

Status: **plan only, nothing built.** Written 2026-10-10 after the request to match Tally's "Compare Party Details" screen
(portal trade name, legal name, address, state, registration type and status beside what is in the books).

## What it should do

1. **On a party** (new or existing): a "Verify with the GST portal" action beside the GSTIN. It shows two columns, *As per
   portal* and *As per books*, exactly as Tally does: trade name, legal name, address, state, pincode, registration type,
   GSTIN status. One click copies the portal's value into the party; nothing changes without a click.
2. **On an uploaded invoice**: the supplier's (or buyer's) GSTIN is checked as the invoice is read. A cancelled or suspended
   GSTIN on a purchase is an alert ("input tax credit is at risk"), and a name that does not match the portal's is shown, not
   hidden.
3. **For the whole client**: "Verify all parties" as a background job, with a table of mismatches and cancelled GSTINs. Re-checked
   on a schedule (monthly), because a supplier cancelled after you booked its invoices is exactly what an auditor asks about.

## What the GST system offers (and what is not yet confirmed)

From the search done for this plan (vendor pages, not GSTN's own documentation, so **to be confirmed with the chosen provider**):

- GSTN exposes a **public** "search taxpayer by GSTIN" API: basic details, no consent from the taxpayer needed, reached through a
  GST Suvidha Provider (GSP), not directly. A **private** API (returns, filing detail) needs the taxpayer's consent and an OTP;
  this plan does not need it.
- There is no free official open endpoint for software to call. The portal's own search page is protected by a captcha, and
  third-party scrapers that solve it exist but depend on terms and on a page that can change. **Not recommended** for books
  that go to an auditor.
- Pricing is per lookup and varies (listings seen quote from about 50 paise a call; some scrapers a few dollars per thousand).
  Treat all of it as unconfirmed until a quote is in hand.

Sources: [GST APIs via Quicko GSP](https://help.quicko.com/portal/en/kb/articles/gst-apis-available-via-quicko-gsp),
[GST public API overview (Ginesys)](https://www.ginesys.in/blog/gst-public-api-empowering-taxpayers-real-time-compliance-and-data-accuracy),
[GST Suvidha Provider overview (Masters India)](https://www.mastersindia.co/blog/gst-suvidha-provider-overview/),
[GSTIN API listing (Capterra)](https://www.capterra.in/software/1240769/GSTIN-API).

## Design

**An adapter, like the model and storage adapters.** `integrations/gstverify/base.py` defines one call:
`lookup(gstin) -> TaxpayerDetails | NotFound | Unavailable`. A stub adapter (returns fixed data, used in tests and when no
provider is configured) and one adapter per provider. Swapping provider is a settings change, as with the model.

**What is stored.** A `GstinCheck` row per GSTIN per firm: the portal's legal name, trade name, address, state, pincode,
registration type, status, date of registration or cancellation, and when it was checked. Names and addresses of businesses are
public registration data, but they are stored encrypted like the rest of a party's identifiers. The GSTIN itself is looked up by
its blind index, as parties are.

**When a call is made.** Only when a person asks (party screen), when an invoice is read and the GSTIN has no check younger than
30 days, and in the scheduled job. A cached answer is reused, so a supplier seen on forty invoices is looked up once a month. A
per-firm monthly cap stops a loop from running up a bill, the way the model budget does.

**What it never does.** It never changes a party, an invoice or the books by itself. The check informs: a mismatch is shown, a
cancelled GSTIN raises an alert, and a person decides. It does not block booking, because the portal can be down or wrong and
the books must not depend on it.

**Failure.** Provider down, rate limited or quota spent: the screen says "could not check right now" and shows the last answer
with its date. Nothing else is affected.

**Where the credentials live.** In the server's secrets store, set with the same script as the model key. Never in the repository,
never in chat, never in a log. The provider's key is not needed on a PC running the app against the live database unless the
flag for it is turned on, as with the model.

## Build order

1. Adapter interface, stub, `GstinCheck` table, a `parties/{id}/verify` endpoint, and the compare dialog on the party screen.
2. Provider adapter for the chosen GSP, with a recorded-response test so it can be exercised without a key.
3. Invoice-time check and the alerts (cancelled supplier, name mismatch).
4. The monthly job and the mismatch list.

Phases 1 to 2 are the part that matches Tally's screen; 3 and 4 are what makes it earn its keep.

## Decisions needed from you

1. **Provider.** Which GSP or API vendor do you want to use (or already have an account with)? If none, the next step is to ask
   two or three for a quote for GSTIN search at your volume and their terms on storing the results.
2. **Volume.** Roughly how many distinct GSTINs across all clients, and how often should they be re-checked? This sets the cost.
3. **Scope of the first release.** Party screen only, or invoices as well from the start?
4. **Terms.** Whether the provider's terms allow keeping results (the plan stores them, encrypted, for 30 days of reuse).
