// A stand-in for the Django API with invented sample data, so the web app can be looked at without a database.
//
//   node qa/tools/mock-api.mjs        (listens on 127.0.0.1:8000, the dev server's default target)
//   npm run dev                       (in another terminal), then open http://127.0.0.1:5173
//
// You are signed in as a firm owner with three made-up clients and nine made-up alerts. Only the shell, the alerts and the
// client pages' headers have data; every other list is empty. Nothing here touches a real database or real data.
import http from 'node:http'

const FIRM = { id: 'f0000000-0000-4000-8000-000000000001', name: "Rudra's Firm", is_active: true, created_at: '2026-01-01T00:00:00Z' }
const PERMS = [
  'client.view', 'document.view', 'transaction.view', 'journal.view', 'report.view', 'gst.view', 'document.upload',
  'statement.delete', 'transaction.classify', 'suggestion.edit', 'ledger.manage', 'party.manage', 'journal.approve',
  'journal.correct', 'books.request', 'gst.prepare', 'period.close', 'books.sign_off', 'gst.sign_off', 'ledger.import',
  'team.view', 'team.assign', 'member.invite', 'member.deactivate', 'firm.manage', 'client.update', 'audit.view',
  'member.manage', 'member.remove', 'client.create', 'client.delete',
]
const ME = {
  id: 'u0000000-0000-4000-8000-000000000001', email: 'owner@example.test', full_name: 'owner_rudra', firm: FIRM,
  membership_id: 'm0000000-0000-4000-8000-000000000001', role: 'FIRM_ADMIN', role_display: 'Firm owner', is_owner: true, permissions: PERMS,
}
const CLIENTS = [
  ['c0000000-0000-4000-8000-000000000001', 'Divine Construwell Private Limited'],
  ['c0000000-0000-4000-8000-000000000002', 'Laxmi Synthetics'],
  ['c0000000-0000-4000-8000-000000000003', 'Sarika Gaggad'],
].map(([id, name]) => ({
  id, name, fy_start: '2025-04-01', business_profile: '', created_at: '2026-09-01T00:00:00Z', lead: { id: 'l1', name: 'R. Iyer' },
  can_sign_off: true, can_post: true, has_entries: true, close_period: 'QUARTERLY',
}))
const page = (results) => ({ count: results.length, next: null, previous: null, results })

const alert = (client, kind, severity, module, title, detail, screen, search = {}, count = 1) => ({
  kind, severity, module, client: client.id, client_name: client.name, title, detail, to: `/clients/${client.id}/${screen}`.replace(/\/$/, ''),
  search, amount_paise: null, amount_display: null, count,
})
const [A, B, C] = CLIENTS
const ALERTS = [
  alert(B, 'tds', 'critical', 'bookkeeping', 'TDS is overdue', 'TDS of ₹42,500.00 was due by 07-09-2026 and is not deposited.', 'tds'),
  alert(A, 'seal', 'high', 'bookkeeping', 'Books are due to be sealed', 'The books were due to be sealed through 30-09-2026.', 'books'),
  alert(B, 'bank', 'high', 'bank', 'A bank account does not agree with its statement', 'HDFC ••••4521 differs by ₹1,250.00 at 30-09-2026.', 'statements'),
  alert(A, 'payment_unallocated', 'high', 'bookkeeping', 'Payments not matched to bills', '3 item(s): Payment to Shree Traders is not allocated to any bill. Blocks sealing until fixed or explained.', 'open-items', {}, 3),
  alert(A, 'review', 'medium', 'bank', 'Rows need a ledger', '12 bank row(s) have no ledger yet.', 'review', { stage: 'unresolved' }, 12),
  alert(C, 'review', 'medium', 'bank', 'Rows ready to post', '5 placed bank row(s) are waiting to be posted.', 'review', { stage: 'pending_approval' }, 5),
  alert(C, 'statements', 'medium', 'bank', 'A statement month is missing', 'No statement covers 2 month(s) inside the run of statements.', 'statements', {}, 2),
  alert(A, 'unchecked', 'medium', 'bookkeeping', 'Assistant entries need checking', '5 entr(ies) the assistant posted have not been checked.', 'daybook', {}, 5),
  alert(B, 'approval', 'medium', 'bookkeeping', 'Entries changed after approval', '2 entr(ies) changed since the senior approved.', 'books', {}, 2),
]
const feed = (alerts, module) => {
  const by_module = { bank: 0, bookkeeping: 0, reports: 0, gst: 0, documents: 0 }
  const by_severity = { critical: 0, high: 0, medium: 0 }
  for (const a of alerts) { by_module[a.module]++; by_severity[a.severity]++ }
  return { counts: { total: alerts.length, by_module, by_severity }, alerts: module ? alerts.filter((a) => a.module === module) : alerts }
}
const overviewRow = (c, i) => ({
  id: c.id, name: c.name, lead: { id: 'l1', name: 'R. Iyer' }, stage: ['needs_ledger', 'in_review', 'ready_to_post'][i], unresolved: [12, 0, 0][i],
  pending_approval: [0, 0, 5][i], assistant_waiting: 0, ai_unchecked: [5, 0, 0][i], review_pending: i === 1, signed_off_through: null,
  last_statement_end: '2026-09-30', months_missing: i === 2 ? ['2026-07', '2026-08'] : [],
  next_step: { code: ['place', 'sign_off', 'post'][i], label: ['12 rows to place', 'Sent for review', '5 rows to post'][i], count: [12, 0, 5][i] },
})
const overview = () => ({
  totals: { clients: 3, unresolved: 12, pending_approval: 5, assistant_waiting: 0, ai_unchecked: 5, review_pending: 1, months_missing: 2 },
  by_stage: { no_statements: 0, needs_ledger: 1, ready_to_post: 1, ready_for_review: 0, in_review: 1, signed_off: 0 },
  clients: CLIENTS.map(overviewRow),
})
const books = () => ({
  signed_off_through: null, review_pending: false, requested_by: '', requested_at: null, returned_note: '', approved_through: null, approved_by: '',
  approved_at: null, changed_since_approval: 0, close_period: 'QUARTERLY', sealable_dates: [], next_seal_date: '2026-12-31', waiting: 0,
  ai_posted: 5, ai_revised: 0, can_request: true, can_sign_off: true, history: [],
})
const summary = () => ({ high: 0, advised: 4, judgement: 8, total: 12, bulk_approvable: 0, needs_settlement: 0, unresolved: 12, pending_approval: 0, assistant_waiting: 0 })
const month = (i) => ({ month: `${i < 9 ? 2025 : 2026}-${String(((i + 3) % 12) + 1).padStart(2, '0')}`, income_paise: 0, expense_paise: 0, profit_paise: 0 })

const send = (res, body, status = 200) => {
  res.writeHead(status, { 'content-type': 'application/json' })
  res.end(JSON.stringify(body))
}

http
  .createServer((req, res) => {
    const url = new URL(req.url, 'http://x')
    const p = url.pathname
    const module = url.searchParams.get('module') || undefined
    if (req.method !== 'GET') return send(res, {})
    let m
    if (p === '/api/v1/me/') return send(res, ME)
    if (p === '/api/v1/firm/overview/') return send(res, overview())
    if (p === '/api/v1/firm/alerts/') return send(res, feed(ALERTS, module))
    if (p === '/api/v1/clients/') {
      const q = (url.searchParams.get('search') || '').toLowerCase()
      return send(res, page(CLIENTS.filter((c) => !q || c.name.toLowerCase().includes(q))))
    }
    if ((m = p.match(/^\/api\/v1\/clients\/([^/]+)\/alerts\/$/))) return send(res, feed(ALERTS.filter((a) => a.client === m[1]), module))
    if ((m = p.match(/^\/api\/v1\/clients\/([^/]+)\/review-queue\/summary\/$/))) return send(res, summary())
    if ((m = p.match(/^\/api\/v1\/clients\/([^/]+)\/books\/$/))) return send(res, books())
    if ((m = p.match(/^\/api\/v1\/clients\/([^/]+)\/dashboard\/$/)))
      return send(res, { financial_year: 2025, as_of: '2026-10-07', income_paise: 0, expense_paise: 0, profit_paise: 0, trend: Array.from({ length: 12 }, (_, i) => month(i)), top_expenses: [], accounts: [], owed: { receivables: { total_paise: 0, over_90_paise: 0, top: [] }, payables: { total_paise: 0, over_90_paise: 0, top: [] } }, gst_net_payable_paise: 0, tds_payable_paise: 0, books: { approved_through: null, signed_off_through: null, changed_since_approval: 0, close_period: 'QUARTERLY', next_seal_date: '2026-12-31' }, attention: { open_items: 0, blocking_unexplained: 0, failing_controls: [] } })
    if ((m = p.match(/^\/api\/v1\/clients\/([^/]+)\/$/))) return send(res, CLIENTS.find((c) => c.id === m[1]) ?? CLIENTS[0])
    if (p.startsWith('/api/')) return send(res, page([]))
    send(res, {})
  })
  .listen(8000, '127.0.0.1', () => console.log('mock api on 8000'))
