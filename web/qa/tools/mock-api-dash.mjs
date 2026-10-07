// A stand-in for the Django API for the dashboards work, with invented data only. Separate from mock-api.mjs.
//
//   node qa/tools/mock-api-dash.mjs            (listens on 127.0.0.1:8001)
//   set VITE_DEV_API=http://127.0.0.1:8001 & npx vite --host 127.0.0.1 --port 5174
//
// The signed-in role is the cookie `mockrole` (FIRM_ADMIN, SENIOR_CA, STAFF, READ_ONLY); the browser sends it with
// every API call, so a screenshot script sets it with context.addCookies. Staff and read-only get fewer permissions.
// `mockempty=1` makes the portfolio empty.
import http from 'node:http'

const FIRM = { id: 'f0000000-0000-4000-8000-000000000001', name: "Rudra's Firm", is_active: true, created_at: '2026-01-01T00:00:00Z' }
const ALL = [
  'client.view', 'document.view', 'transaction.view', 'journal.view', 'report.view', 'gst.view', 'document.upload',
  'statement.delete', 'transaction.classify', 'suggestion.edit', 'ledger.manage', 'party.manage', 'journal.approve',
  'journal.correct', 'books.request', 'gst.prepare', 'period.close', 'books.sign_off', 'gst.sign_off', 'ledger.import',
  'team.view', 'team.assign', 'member.invite', 'member.deactivate', 'firm.manage', 'client.update', 'audit.view',
  'member.manage', 'member.remove', 'client.create', 'client.delete',
]
const PERMS = {
  FIRM_ADMIN: ALL,
  SENIOR_CA: ALL.filter((p) => !['firm.manage', 'member.manage', 'member.remove', 'client.delete', 'member.deactivate'].includes(p)),
  STAFF: ['client.view', 'document.view', 'transaction.view', 'report.view', 'document.upload', 'transaction.classify', 'suggestion.edit'],
  READ_ONLY: ['client.view', 'document.view', 'transaction.view', 'journal.view', 'report.view', 'gst.view'],
}
const NAME = { FIRM_ADMIN: 'Firm owner', SENIOR_CA: 'Senior CA', STAFF: 'Staff', READ_ONLY: 'Read only' }
const roleOf = (req) => {
  const m = /(?:^|;\s*)mockrole=([A-Z_]+)/.exec(req.headers.cookie || '')
  return m && PERMS[m[1]] ? m[1] : 'FIRM_ADMIN'
}
const me = (role) => ({
  id: 'u0000000-0000-4000-8000-000000000001', email: 'person@example.test', full_name: 'Meera Shah', firm: FIRM,
  membership_id: 'm0000000-0000-4000-8000-000000000001', role, role_display: NAME[role], is_owner: role === 'FIRM_ADMIN', permissions: PERMS[role],
})

const id = (n) => `c0000000-0000-4000-8000-00000000000${n}`
const LEAD = { id: 'l1', name: 'R. Iyer' }
// name, stage, extras
const SPEC = [
  ['Divine Construwell Private Limited', 'needs_ledger', { unresolved: 12, ai_unchecked: 5, seal_due: '2026-09-30', tds_overdue_paise: 4250000, receivables_paise: 128000000, payables_paise: 9500000, open_items: 14, blocking_unexplained: 3, failing_controls: 1, next: ['place', '12 rows to place', 12] }],
  ['Laxmi Synthetics', 'in_review', { review_pending: true, receivables_paise: 45000000, payables_paise: 23000000, open_items: 2, next: ['sign_off', 'Sent for review', 0] }],
  ['Sarika Gaggad', 'ready_to_post', { pending_approval: 5, months_missing: ['2026-07', '2026-08'], receivables_paise: 1250000, payables_paise: 640000, open_items: 6, next: ['post', '5 rows to post', 5] }],
  ['Rao & Sons Traders', 'signed_off', { receivables_paise: 8800000, payables_paise: 4100000, open_items: 0, next: ['none', 'Sealed to date', 0] }],
  ['Meera Textiles LLP', 'no_statements', { receivables_paise: 0, payables_paise: 0, open_items: 0, next: ['upload', 'Upload a bank statement', 0] }],
  ['Kumar Logistics', 'ready_for_review', { receivables_paise: 76000000, payables_paise: 31000000, open_items: 5, blocking_unexplained: 2, failing_controls: 2, next: ['send_for_review', 'Send for review', 0] }],
  ['Patel Agro Industries', 'signed_off', { receivables_paise: 22000000, payables_paise: 12000000, open_items: 0, next: ['none', 'Sealed to date', 0] }],
]
const rows = (money) =>
  SPEC.map(([name, stage, x], i) => ({
    id: id(i + 1), name, lead: LEAD, stage, next_step: { code: x.next[0], label: x.next[1], count: x.next[2] },
    unresolved: x.unresolved ?? 0, pending_approval: x.pending_approval ?? 0, assistant_waiting: 0, ai_unchecked: x.ai_unchecked ?? 0,
    review_pending: !!x.review_pending, signed_off_through: stage === 'signed_off' ? '2026-09-30' : null,
    last_statement_end: stage === 'no_statements' ? null : '2026-09-30', months_missing: x.months_missing ?? [],
    ...(money === null ? {} : {
      detail: true, approved_through: null, changed_since_approval: 0, seal_due: x.seal_due ?? null, next_seal_date: '2026-12-31',
      open_items: x.open_items, blocking_unexplained: x.blocking_unexplained ?? 0, failing_controls: x.failing_controls ?? 0,
      ...(money ? { tds_overdue_paise: x.tds_overdue_paise ?? 0, receivables_paise: x.receivables_paise, payables_paise: x.payables_paise } : {}),
    }),
  }))
const withHealth = (cl, money) =>
  cl.map((c) => {
    const late = !!c.tds_overdue_paise
    const risk = !!c.seal_due || c.months_missing.length > 0 || (c.failing_controls ?? 0) > 0
    return { ...c, health: money && late ? 'overdue' : risk ? 'at_risk' : 'on_track', ready_to_seal: c.stage === 'in_review' ? false : c.stage === 'signed_off', oldest_pending_approval_days: c.review_pending ? 4 : null }
  })
const STAGES = ['no_statements', 'needs_ledger', 'ready_to_post', 'ready_for_review', 'in_review', 'signed_off']
const byStage = (cl) => Object.fromEntries(STAGES.map((s) => [s, cl.filter((c) => c.stage === s).length]))
const totals = (cl) => ({
  clients: cl.length, unresolved: cl.reduce((n, c) => n + c.unresolved, 0), pending_approval: cl.reduce((n, c) => n + c.pending_approval, 0),
  assistant_waiting: 0, ai_unchecked: cl.reduce((n, c) => n + c.ai_unchecked, 0), review_pending: cl.filter((c) => c.review_pending).length,
  months_missing: cl.reduce((n, c) => n + c.months_missing.length, 0),
})
const att = (c, severity, kind, text, to, search = {}, amount = null) => ({ severity, kind, client: id(c), client_name: SPEC[c - 1][0], text, amount_paise: amount, amount_display: null, to: `/clients/${id(c)}/${to}`.replace(/\/$/, ''), search })
const ATTENTION = [
  att(1, 'critical', 'tds', 'TDS of ₹42,500.00 was due by 07-09-2026 and is not deposited.', 'tds'),
  att(1, 'critical', 'seal', 'The books were due to be sealed through 30-09-2026.', 'books'),
  att(1, 'high', 'review', '12 bank rows have no account yet.', 'review', { stage: 'unresolved' }),
  att(3, 'high', 'statements', 'No statement covers 2 months inside the run of statements.', 'statements'),
  att(6, 'high', 'controls', '2 checks are failing and 2 items block sealing.', 'books'),
  att(2, 'medium', 'approval', 'Sent for review and waiting for a decision.', 'books'),
  att(3, 'medium', 'review', '5 sorted rows are waiting to be recorded.', 'review', { stage: 'pending_approval' }),
]
const DEADLINES = [
  { date: '2026-10-15', label: 'TDS deposit for September', clients: ['Divine Construwell Private Limited', 'Kumar Logistics'] },
  { date: '2026-10-31', label: 'Seal the books to 30-09-2026', clients: ['Laxmi Synthetics', 'Sarika Gaggad', 'Kumar Logistics', 'Rao & Sons Traders'] },
  { date: '2026-11-15', label: 'TDS deposit for October', clients: ['Divine Construwell Private Limited'] },
  { date: '2026-12-10', label: 'Seal the books to 31-12-2026', clients: ['Rao & Sons Traders'] },
]
const portfolio = (role, empty) => {
  const money = PERMS[role].includes('journal.view')
  let cl = withHealth(rows(money), money)
  if (role === 'STAFF') cl = cl.slice(0, 3)
  if (role === 'SENIOR_CA') cl = cl.slice(0, 6)
  if (empty) cl = []
  const keep = new Set(cl.map((c) => c.client ?? c.id))
  const roll = money && !empty
    ? (() => {
        const recv = cl.reduce((n, c) => n + (c.receivables_paise ?? 0), 0)
        const pay = cl.reduce((n, c) => n + (c.payables_paise ?? 0), 0)
        const bucket = (total, f) => ['0-30', '31-60', '61-90', 'Over 90'].map((b, i) => ({ bucket: b, amount_paise: Math.round(total * f[i]), amount_display: null }))
        return {
          receivables_total_paise: recv, payables_total_paise: pay, receivables_total_display: null, payables_total_display: null,
          aging: { receivables: bucket(recv, [0.38, 0.27, 0.17, 0.18]), payables: bucket(pay, [0.5, 0.3, 0.12, 0.08]) },
          top_receivables: [...cl].filter((c) => (c.receivables_paise ?? 0) > 0).sort((a, b) => b.receivables_paise - a.receivables_paise).slice(0, 5).map((c) => ({ client: c.id, client_name: c.name, amount_paise: c.receivables_paise, amount_display: null })),
        }
      })()
    : {}
  return { totals: totals(cl), by_stage: byStage(cl), clients: cl, attention: ATTENTION.filter((a) => keep.has(a.client)), deadlines: empty ? [] : DEADLINES, detailed: true, ...roll }
}

const CLIENTS = SPEC.map(([name], i) => ({
  id: id(i + 1), name, fy_start: '2026-04-01', business_profile: i === 0 ? 'Builders and civil contractors. GST registered, TDS on contractors.' : '', created_at: '2026-09-01T00:00:00Z', lead: LEAD,
  can_sign_off: true, can_post: true, has_entries: true, close_period: 'QUARTERLY',
}))
const page = (results) => ({ count: results.length, next: null, previous: null, results })

const INCOME = [24, 27, 31, 22, 29, 33, 0, 0, 0, 0, 0, 0]
const EXPENSE = [19, 21, 26, 24, 22, 25, 0, 0, 0, 0, 0, 0]
const month = (i, k) => ({ month: `${i < 9 ? 2026 : 2027}-${String(((i + 3) % 12) + 1).padStart(2, '0')}`, income_paise: INCOME[i] * k * 100000 * 100 / 10, expense_paise: EXPENSE[i] * k * 100000 * 100 / 10, profit_paise: 0 })
const inr = (paise) => '₹' + (paise / 100).toLocaleString('en-IN', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
const withDisplay = (o) => ({ ...o, amount_display: inr(o.amount_paise) })
const snapshot = (n) => {
  const k = [1, 0.4, 0.15, 0.9, 0, 0.7, 0.5][n - 1] ?? 1
  const trend = Array.from({ length: 12 }, (_, i) => month(i, k))
  const income = trend.reduce((s, m) => s + m.income_paise, 0)
  const expense = trend.reduce((s, m) => s + m.expense_paise, 0)
  const top = [['Salaries and wages', 0.34], ['Raw materials', 0.27], ['Rent', 0.14], ['Freight and transport', 0.09], ['Electricity', 0.05], ['Professional fees', 0.03]].map(([ledger, f]) => withDisplay({ ledger, amount_paise: Math.round(expense * f) }))
  const party = (name, amount_paise) => withDisplay({ name, amount_paise })
  const side = (total, over, names) => ({ total_paise: total, over_90_paise: over, total_display: inr(total), over_90_display: inr(over), top: names.map(([nm, f]) => party(nm, Math.round(total * f))) })
  const recv = Math.round(SPEC[n - 1][2].receivables_paise ?? 0)
  const pay = Math.round(SPEC[n - 1][2].payables_paise ?? 0)
  return {
    financial_year: 2026, as_of: '2026-10-07', income_paise: income, expense_paise: expense, profit_paise: income - expense, trend, top_expenses: top,
    accounts: [{ label: 'HDFC Current ••••4521', kind: 'BANK', balance_paise: 1840000000 * k, balance_display: inr(1840000000 * k) }, { label: 'ICICI Credit Card ••••9012', kind: 'CARD', balance_paise: 21000000, balance_display: inr(21000000) }, { label: 'SBI Term Loan ••••7788', kind: 'LOAN', balance_paise: 560000000, balance_display: inr(560000000) }],
    owed: { receivables: side(recv, Math.round(recv * 0.18), [['Shree Traders', 0.4], ['Anand Enterprises', 0.25], ['Mehta & Co', 0.15]]), payables: side(pay, 0, [['Gupta Steel', 0.5], ['City Transport', 0.3], ['Vikas Cement', 0.2]]) },
    gst_net_payable_paise: 21800000, tds_payable_paise: SPEC[n - 1][2].tds_overdue_paise ?? 640000,
    books: { approved_through: null, signed_off_through: null, changed_since_approval: 0, close_period: 'QUARTERLY', next_seal_date: '2026-12-31' },
    attention: { open_items: 0, blocking_unexplained: 0, failing_controls: [] },
    prior_income_paise: n === 5 ? null : Math.round(income * 1.9), prior_expense_paise: n === 5 ? null : Math.round(expense * 1.8),
    reports_ready: [
      { key: 'pnl', label: 'Profit and loss', ready: n !== 3 && n !== 5, reason: n === 3 ? '2 months of statements are missing' : n === 5 ? 'Nothing has been posted yet' : null },
      { key: 'balance_sheet', label: 'Balance sheet', ready: n === 4 || n === 7, reason: n === 4 || n === 7 ? null : 'Rows are still waiting to be recorded' },
      { key: 'trial_balance', label: 'Trial balance', ready: n !== 3 && n !== 5, reason: n === 3 ? '2 months of statements are missing' : n === 5 ? 'Nothing has been posted yet' : null },
      { key: 'receivables', label: 'Who owes me', ready: n !== 5, reason: n === 5 ? 'Nothing has been posted yet' : null },
      { key: 'payables', label: 'Whom I owe', ready: n !== 5, reason: n === 5 ? 'Nothing has been posted yet' : null },
      { key: 'tds', label: 'TDS', ready: n !== 1, reason: n === 1 ? 'TDS is overdue' : null },
      { key: 'gst', label: 'GST', ready: n !== 3, reason: n === 3 ? '2 months of statements are missing' : null },
    ],
    prior_income_display: null, prior_expense_display: null,
    income_display: inr(income), expense_display: inr(expense), profit_display: inr(income - expense), gst_net_payable_display: inr(21800000), tds_payable_display: inr(640000),
  }
}
const statementsFor = (n) => {
  if (n === 5) return []
  const spans = n === 1 ? [['2026-04-01', '2026-07-31'], ['2026-09-01', '2026-09-30']] : n === 3 ? [['2026-04-01', '2026-06-30'], ['2026-09-01', '2026-09-30']] : [['2026-04-01', '2026-09-30']]
  return spans.map(([a, b], i) => ({ id: `s${n}${i}`, bank_account: `ba${n}`, bank_account_label: 'HDFC ••••4521', document: {}, period_start: a, period_end: b, opening_balance_paise: 0, closing_balance_paise: 0, total_debit_paise: 0, total_credit_paise: 0, transaction_count: 100, parser: 'x', parser_version: 1, created_at: '2026-10-01T00:00:00Z' }))
}
const books = (n) => ({
  signed_off_through: SPEC[n - 1][1] === 'signed_off' ? '2026-09-30' : null, review_pending: !!SPEC[n - 1][2].review_pending, requested_by: 'Aarav (staff)', requested_at: null, returned_note: '', approved_through: null,
  approved_by: '', approved_at: null, changed_since_approval: 0, close_period: 'QUARTERLY', sealable_dates: [], next_seal_date: '2026-12-31', waiting: 0,
  ai_posted: SPEC[n - 1][2].ai_unchecked ?? 0, ai_revised: 0, can_request: true, can_sign_off: true, history: [],
})
const summary = (n) => ({ high: 0, advised: 4, judgement: 8, total: 12, bulk_approvable: 0, needs_settlement: 0, unresolved: SPEC[n - 1][2].unresolved ?? 0, pending_approval: SPEC[n - 1][2].pending_approval ?? 0, assistant_waiting: 0 })
const alerts = { counts: { total: 0, by_module: { bank: 0, bookkeeping: 0, reports: 0, gst: 0, documents: 0 }, by_severity: { critical: 0, high: 0, medium: 0 } }, alerts: [] }

const send = (res, body, status = 200) => {
  res.writeHead(status, { 'content-type': 'application/json' })
  res.end(JSON.stringify(body))
}

http
  .createServer((req, res) => {
    const url = new URL(req.url, 'http://x')
    const p = url.pathname
    if (req.method !== 'GET') return send(res, {})
    const role = roleOf(req)
    const empty = /mockempty=1/.test(req.headers.cookie || '')
    let m
    if (p === '/api/v1/me/') return send(res, me(role))
    if (p === '/api/v1/firm/portfolio/') return send(res, portfolio(role, empty))
    if (p === '/api/v1/firm/overview/') { const pf = portfolio(role, empty); return send(res, { totals: pf.totals, by_stage: pf.by_stage, clients: pf.clients }) }
    if (p === '/api/v1/firm/work-flow/') {
      const weeks = Array.from({ length: 12 }, (_, i) => {
        const d = new Date(Date.UTC(2026, 6, 20 + i * 7))
        return { week_start: d.toISOString().slice(0, 10), received: [40, 55, 38, 62, 71, 58, 66, 80, 74, 69, 90, 52][i], finished: [34, 41, 39, 50, 58, 55, 61, 66, 70, 64, 72, 30][i] }
      })
      const sum = (k) => weeks.reduce((n, w) => n + w[k], 0)
      return send(res, { scope: role === 'FIRM_ADMIN' ? 'firm' : 'team', period: { from: '2026-07-20', to: '2026-10-07' }, weekly: weeks, totals: { received: sum('received'), finished: sum('finished'), prev_received: 600, prev_finished: 540 } })
    }
    if (p === '/api/v1/firm/people/') {
      if (!PERMS[role].includes('team.view')) return send(res, { code: 'forbidden', detail: 'Your role does not permit team.view.', fields: {} }, 403)
      const P = [['Aarav Mehta', 'STAFF', 3, 14, 38, 1, 2], ['Divya Nair', 'STAFF', 2, 6, 52, 0, 1], ['R. Iyer', 'SENIOR_CA', 5, 9, 21, 2, 3], ['Sana Qureshi', 'STAFF', 4, 22, 17, 3, 5], ['Vikram Shah', 'STAFF', 1, 0, 0, 0, 0]]
      return send(res, { period: { from: '2026-10-01', to: '2026-10-07' }, detailed: true, people: P.map(([name, r, a, o, f, l, w], i) => ({ member_id: `m${i}`, name, role: r, assigned_clients: a, open_items: o, finished_in_period: f, overdue: l, waiting_on_others: w })) })
    }
    if (p === '/api/v1/me/work/') {
      const daily = Array.from({ length: 7 }, (_, i) => ({ date: `2026-10-0${i + 1}`, finished: [4, 7, 5, 0, 0, 9, 6][i] }))
      const cl = rows(true).slice(0, 3)
      return send(res, {
        period: { from: '2026-10-01', to: '2026-10-07' }, assigned_clients: 3, open_items: 17, overdue: 1, waiting: 4, finished_in_period: 31, daily,
        next_tasks: [
          { client: id(1), client_name: SPEC[0][0], title: 'TDS is overdue', due: '2026-09-07', to: `/clients/${id(1)}/tds`, search: {}, severity: 'critical' },
          { client: id(1), client_name: SPEC[0][0], title: 'Sort 12 entries into accounts', due: null, to: `/clients/${id(1)}/review`, search: { stage: 'unresolved' }, severity: 'medium' },
          { client: id(3), client_name: SPEC[2][0], title: 'Record 5 entries in the books', due: null, to: `/clients/${id(3)}/review`, search: { stage: 'pending_approval' }, severity: 'medium' },
        ],
        clients: cl.map((c) => ({ id: c.id, name: c.name, open_items: c.open_items })),
      })
    }
    if (p === '/api/v1/firm/alerts/') return send(res, alerts)
    if (p === '/api/v1/clients/') return send(res, page(CLIENTS))
    if ((m = p.match(/^\/api\/v1\/clients\/c0000000-0000-4000-8000-00000000000(\d)\/(.*)$/))) {
      const n = Number(m[1])
      const rest = m[2]
      if (rest === 'alerts/') return send(res, alerts)
      if (rest === 'review-queue/summary/') return send(res, summary(n))
      if (rest === 'books/') return send(res, books(n))
      if (rest === 'statements/') return send(res, page(statementsFor(n)))
      if (rest === 'bank-accounts/') return send(res, page(n === 5 ? [] : [{ id: `ba${n}`, label: 'HDFC ••••4521', client: id(n), bank_code: 'HDFC', kind: 'BANK', account_last4: '4521', ifsc: '', has_opening_balance: n !== 3, is_active: true, created_at: '2026-09-01T00:00:00Z' }]))
      if (rest === 'dashboard/') return send(res, snapshot(n))
      if (rest === '') return send(res, CLIENTS[n - 1])
    }
    if ((m = p.match(/^\/api\/v1\/clients\/c0000000-0000-4000-8000-00000000000(\d)\/$/))) return send(res, CLIENTS[Number(m[1]) - 1])
    if (p.startsWith('/api/')) return send(res, page([]))
    send(res, {})
  })
  .listen(8001, '127.0.0.1', () => console.log('dash mock api on 8001'))
