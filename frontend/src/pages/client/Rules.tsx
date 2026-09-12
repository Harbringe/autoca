// Rules are mostly written by the system: every decision a reviewer makes
// mints one, keyed on the payee. This screen shows them, what they have
// placed, and lets a preparer switch one off.

import { allPages, api, V1 } from '../../api/client'
import type { Client, Rule } from '../../api/types'
import { useSession } from '../../auth/session'
import { Badge, Button, Confidence, Empty, ErrorNote, formatDateTime, Spinner, useAsync } from '../../components/ui'
import { useState } from 'react'

const MATCH_LABEL: Record<string, string> = {
  PARTY_EQUALS: 'Counterparty is exactly',
  PARTY_CONTAINS: 'Counterparty contains',
  NARRATION_CONTAINS: 'Narration contains',
  CHANNEL_IS: 'Channel is',
  REGEX: 'Narration matches regex',
}

export default function Rules({ client }: { client: Client }) {
  const { can } = useSession()
  const rules = useAsync(() => allPages<Rule>(`${V1}/clients/${client.id}/rules/`), [client.id])
  const [error, setError] = useState<unknown>(null)

  async function toggle(rule: Rule) {
    setError(null)
    try {
      await api.patch(`${V1}/clients/${client.id}/rules/${rule.id}/`, { is_active: !rule.is_active })
      rules.reload()
    } catch (err) {
      setError(err)
    }
  }

  const sorted = [...(rules.data ?? [])].sort((a, b) => b.hit_count - a.hit_count)

  return (
    <div className="panel">
      <div className="panel-head">
        <h2>Classification rules</h2>
        <span className="sub">{sorted.length} rules · learned from your decisions, plus the bank's own charges and interest</span>
      </div>
      <ErrorNote error={error ?? rules.error} />
      {rules.loading ? (
        <Spinner />
      ) : !sorted.length ? (
        <Empty title="No rules yet">Place a row in the review queue and a rule is learned from it.</Empty>
      ) : (
        <div className="table-wrap">
          <table className="grid">
            <thead>
              <tr>
                <th>When</th>
                <th>Place in</th>
                <th>Source</th>
                <th>Confidence</th>
                <th className="num">Hits</th>
                <th>Last hit</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              {sorted.map((r) => (
                <tr key={r.id}>
                  <td>
                    <div className="tiny">{MATCH_LABEL[r.match_type] ?? r.match_type}</div>
                    <code>{r.pattern}</code>
                    {r.direction !== 'ANY' && <Badge>{r.direction === 'DEBIT' ? 'debits only' : 'credits only'}</Badge>}
                  </td>
                  <td>
                    <strong>{r.ledger_name}</strong>
                    <div className="pill-row tiny">
                      {r.rcm && <Badge tone="warn">RCM</Badge>}
                      {r.tds_section && <Badge tone="info">TDS {r.tds_section}</Badge>}
                    </div>
                  </td>
                  <td>
                    <Badge tone={r.source === 'SEED' ? 'neutral' : r.source === 'LEARNED' ? 'good' : 'info'}>{r.source.toLowerCase()}</Badge>
                    {!r.is_active && <Badge>off</Badge>}
                  </td>
                  <td>
                    <Confidence value={r.confidence} />
                  </td>
                  <td className="num">{r.hit_count}</td>
                  <td className="tiny">{formatDateTime(r.last_hit_at)}</td>
                  <td className="num">
                    {can('suggestion.edit') && (
                      <Button className="btn-sm" onClick={() => void toggle(r)}>
                        {r.is_active ? 'Switch off' : 'Switch on'}
                      </Button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
