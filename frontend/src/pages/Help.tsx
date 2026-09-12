export default function Help() {
  return (
    <div className="help">
      <h1>How it works</h1>
      <p className="sub">Bank statements in, approved double-entry journal entries out. Nothing is final until a senior CA approves it.</p>

      <h2>The flow</h2>
      <ol>
        <li>
          <strong>Upload a statement.</strong> Any bank, as a born-digital PDF. The bank and account are read from the file. Every row is proved against the running balance and the printed totals before anything is saved — a statement whose arithmetic does not close is refused with the row that broke.
        </li>
        <li>
          <strong>Confirm the opening balance</strong> the first time an account is seen. A client onboarding in October has six months this system never saw; the books start from what you confirm, not from an assumption.
        </li>
        <li>
          <strong>Review.</strong> Rules place what they can. The model suggests for the rest, with a one-line reason, and never with enough confidence to be bulk-approved. Placing one row teaches a rule keyed on the payee, so the same payee is placed automatically from then on.
        </li>
        <li>
          <strong>Approve.</strong> Only a senior CA or firm admin can. Approval allocates a voucher number and writes the permanent journal entry — which cannot be edited or deleted afterwards. Corrections are new entries that reverse and replace, with the original left visible.
        </li>
        <li>
          <strong>Check month end.</strong> The computed bank-ledger balance beside the bank's own closing figure. A period that does not reconcile is not finished.
        </li>
        <li>
          <strong>Report and export.</strong> Trial balance, P&amp;L and balance sheet for the financial year, each saying how many rows are still unposted. A Tally Prime import file of approved entries only.
        </li>
      </ol>

      <h2>Confidence bands</h2>
      <ul>
        <li>
          <strong>High confidence</strong> — a rule keyed on the exact payee, or the bank's own charges and interest. Eligible for one-click bulk approval.
        </li>
        <li>
          <strong>Review advised</strong> — a broader rule, or a model suggestion. Worth a look; approve individually.
        </li>
        <li>
          <strong>Needs judgement</strong> — nothing placed it. A person decides, and the system learns from the decision.
        </li>
      </ul>

      <h2>What leaves the server</h2>
      <p>
        When the model is asked about a row, it receives the channel, direction, an amount band, and the narration with account numbers, references, PAN, GSTIN, phone numbers and card numbers masked. People's names are replaced by stable pseudonyms; known vendors by alias tokens; the account holder's own name is never sent. It answers with a ledger name from the client's own chart of accounts, which is checked before anything is written.
      </p>

      <h2>Roles</h2>
      <ul>
        <li><strong>Read only</strong> — can see everything in the firm, change nothing.</li>
        <li><strong>Staff</strong> — can upload, place rows, manage ledgers and vendors. Cannot approve.</li>
        <li><strong>Senior CA</strong> — everything staff can, plus approval and corrections.</li>
        <li><strong>Firm administrator</strong> — everything, plus clients and members.</li>
      </ul>
    </div>
  )
}
