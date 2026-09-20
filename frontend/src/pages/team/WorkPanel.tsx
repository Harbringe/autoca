import { Link } from 'react-router-dom'
import { Empty, ErrorNote, formatDate, Spinner, useAsync } from '../../components/ui'
import { RANGES, teamApi, type Range } from './api'

export function RangePicker({ value, onChange }: { value: string; onChange: (key: string) => void }) {
  return (
    <select value={value} onChange={(e) => onChange(e.target.value)} aria-label="Period">
      {RANGES.map((r) => (
        <option key={r.key} value={r.key}>
          {r.label}
        </option>
      ))}
    </select>
  )
}

export function rangeFor(key: string): Range {
  return (RANGES.find((r) => r.key === key) ?? RANGES[1]).range()
}

/** One person's work for a period, plus what is still open on their clients. */
export default function WorkPanel({ memberId, rangeKey }: { memberId: string; rangeKey: string }) {
  const { data, error, loading } = useAsync(() => teamApi.work(memberId, rangeFor(rangeKey)), [memberId, rangeKey])

  if (loading && !data) return <Spinner />
  if (!data) return <ErrorNote error={error} />

  const busiest = Math.max(1, ...data.by_day.map((d) => d.count))
  const total = Object.values(data.totals).reduce((sum, n) => sum + n, 0)
  const shown = data.metrics.filter((m) => data.by_client.some((row) => Number(row[m.key]) > 0))

  return (
    <div className="stack">
      <div className="grid-cards">
        {data.metrics.map((m) => (
          <div key={m.key} className="card">
            <div className="k">{m.label}</div>
            <div className="v">{data.totals[m.key] ?? 0}</div>
          </div>
        ))}
      </div>

      <div className="panel">
        <div className="panel-head">
          <h2>Day by day</h2>
          <span className="sub">
            {formatDate(data.period.from)} – {formatDate(data.period.to)}
          </span>
        </div>
        <div className="panel-body">
          {total === 0 ? (
            <p className="sub">No recorded work in this period.</p>
          ) : (
            <div className="daybars" role="img" aria-label="Work per day">
              {data.by_day.map((d) => (
                <span
                  key={d.date}
                  className="daybar"
                  style={{ height: `${Math.max(2, (d.count / busiest) * 100)}%`, opacity: d.count ? 1 : 0.25 }}
                  title={`${formatDate(d.date)}: ${d.count}`}
                />
              ))}
            </div>
          )}
        </div>
      </div>

      <div className="grid-2">
        <div className="panel">
          <div className="panel-head">
            <h2>By client</h2>
          </div>
          {!data.by_client.length ? (
            <Empty title="Nothing in this period" />
          ) : (
            <div className="table-wrap">
              <table className="grid">
                <thead>
                  <tr>
                    <th>Client</th>
                    {shown.map((m) => (
                      <th key={m.key} className="num">
                        {m.label}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {data.by_client.map((row) => (
                    <tr key={row.id ?? row.name}>
                      <td>{row.name}</td>
                      {shown.map((m) => (
                        <td key={m.key} className="num">
                          {Number(row[m.key]) || ''}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        <div className="panel">
          <div className="panel-head">
            <h2>Still open on their clients</h2>
          </div>
          {!data.open_work.length ? (
            <Empty title="No clients">Not assigned to any client yet.</Empty>
          ) : (
            <div className="table-wrap">
              <table className="grid">
                <thead>
                  <tr>
                    <th>Client</th>
                    <th className="num">To place</th>
                    <th className="num">Awaiting approval</th>
                  </tr>
                </thead>
                <tbody>
                  {data.open_work.map((c) => (
                    <tr key={c.id}>
                      <td>
                        <Link to={`/clients/${c.id}/review`}>{c.name}</Link>
                      </td>
                      <td className="num">{c.unresolved}</td>
                      <td className="num">{c.pending_approval}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      </div>
      <p className="sub">
        Rows placed are counted from when team tracking was switched on. Uploads, approvals and corrections include all history.
      </p>
    </div>
  )
}
