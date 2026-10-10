# Interface overhaul: what was wrong, what the research says, what changed

Written 2026-10-10. The screens were looked at in the running app (client "Laxmi", FY 2026-27), not judged from the code.
**A correction:** the first look was in a 2504px-wide window (the tool could not resize it), so the first set of screenshots
showed a wide-screen layout, not a laptop's. The receipt page and the purchases list were then checked again in frames of exactly
1366px and 390px, which is where the cramped supplier fields, the long receipt card and the cut-off phone table showed up.

## What was wrong

1. **Three layers of navigation on every bookkeeping page.** The side rail, the client panel, and then a row of ten tabs. A
   person could not tell the daily tabs (Purchases and Sales, Day Book) from the occasional ones (TDS, Payroll, Assets).
2. **The same thing said three times.** On Purchases and Sales: the page title, the selected tab, and a section heading, all
   "Purchases & Sales"; two "View alerts" buttons with different counts; a "Receipt" column of empty boxes.
3. **Buttons that did not belong.** "Upload bank statement" on a purchases page. Edit and Delete buttons that were disabled until
   a row was ticked, in plain sight. "Save expense" on a purchase invoice.
4. **A long form with no shape.** The receipt page asked for about fourteen things in one stream: a new-supplier box nested
   inside a half-width column, TDS fields and a reverse-charge tick shown for every invoice, helper text under every field.
5. **Itemizations that did not show their figures.** A seven-column table squeezed into a half-width column, scrolling
   sideways, so Rate and Amount were out of sight. For old readings, "No lines were read" with no way to try again.
6. **Small text.** 12px and 11px labels in well over a hundred places.
7. **Guessing at purchase or sale.** A file the system could not classify was treated as a purchase.

## What the research agrees on

(Vendor design-system guides and practitioner articles, not controlled studies, so read these as direction.)

- **Progressive disclosure**: show what the moment needs, put the rest one step away. Summaries that drill down beat one page of
  detail.
- **Forms**: one column; labels above fields; group a form of more than six fields into labelled sections; validate after the
  person has typed, not while they are typing; do not use placeholders as labels.
- **Tabs**: around seven peers is where a row stops being scannable; fold the occasional ones under a menu; keep names short and
  specific.
- **Tables**: settle what is in each cell (short numbers and dates versus long text) before choosing the layout; keep figures
  aligned.

## Decisions and what changed

| Problem | Change |
|---|---|
| Ten bookkeeping tabs | Seven in the row (Books summary, Purchases & Sales, Day Book, To fix, Ledgers, Parties & rules, Sign-off); TDS, Payroll and Assets under "More", which names the current one when you are on it |
| Repeated titles and buttons | One title per page; the page's own "N rows need a look" link instead of a second alerts button; a single item page drops the section tabs and the module's alerts |
| Misplaced upload button | Shown only on overview, pipeline, statements, review and the books summary |
| Always-disabled Edit and Delete | A selection bar that appears with the first ticked row: "N selected: Edit, Delete, Clear" |
| Form shape | Type, number, party and dates in one grid; new supplier as one full-width row; TDS and reverse charge folded (open when used); save button named for what it saves; a Round off button; a proper New account dialog |
| Phone list | The purchases list is cards under 640px, not a table that scrolls sideways |
| Itemizations | Each line as its own block with every column visible, no sideways scroll; edits are remembered per party; "Read the lines again" for readings made before the reader improved |
| Small text | The smallest step raised from 12px to 13px in one place, and the 10 to 11px labels moved onto it |
| Invoice From, To | The invoice reads as two cards: From (seller) and To (buyer). The client's own side shows its name and its GSTIN as printed; the other side is the party, matched to one already on file by GSTIN or by business name, with the printed details beneath. A warning when the invoice is made out to someone who shares no word with the client. The narration is worked out from the lines |
| Header chips | The books' state and the year were repeated under every title, in the client panel and in the top bar; only the lock note stays |
| Buyer and seller | Both shown on every invoice, whichever kind it is; kind suggested from the printed names and the model's own judgement, and chosen by the person when neither says |
| Review filters | Confidence chips and search on one line |

## Walked through and left as they are

Looked at in the running app at 1366px and, for several, at 390px: Dashboard, Clients, Client overview, Statements, Review, Pipeline,
Day Book, Ledgers, Purchases and Sales, Reports (trial balance), Documents, GST (empty). They share one structure (title, tab row,
table or cards) and, apart from the repeated chips fixed above, do not contradict each other. At 390px the dashboard cards stack, the
client list drops its secondary columns and wide report tables scroll sideways, which is how a ledger table should behave.

## Not done, so it is not forgotten

- **Settings, Staff, Alerts, Parties & rules, Sign-off, TDS, Payroll, Assets and To fix** were not opened in this pass.
- **Client overview** repeats the left panel as three "Open" cards. Candidate: replace them with the client's next step.
- **Dashboard** is dense. Candidate: one list with bars in place of the donut and its legend.
- **Empty states** mostly say what is missing and not what to do next.
- **Nothing here has been tried by someone doing a day's work.** The next real test is a day of uploads on one client.

## Rules to keep to

- A control that is not usable now is not shown, unless the person needs to know it exists.
- The same fact is not shown twice on one screen.
- A long form is grouped; the occasional field is folded, never removed.
- Wording names the action: "Save purchase", not "Submit"; the same name in the toast.
- A figure is never guessed to look complete: a value the system rejected is shown with why.
