import { useState, type FormEvent } from 'react'
import { allPages, api, V1 } from '../../api/client'
import type { Client, Vendor } from '../../api/types'
import { TDS_SECTIONS } from '../../api/types'
import { useSession } from '../../auth/session'
import { Badge, Button, Empty, ErrorNote, Field, Spinner, useAsync } from '../../components/ui'

export default function Vendors({ client }: { client: Client }) {
  const { can } = useSession()
  const vendors = useAsync(() => allPages<Vendor>(`${V1}/clients/${client.id}/vendors/`), [client.id])
  const [name, setName] = useState('')
  const [gstin, setGstin] = useState('')
  const [rcm, setRcm] = useState(false)
  const [tds, setTds] = useState('')
  const [error, setError] = useState<unknown>(null)
  const [busy, setBusy] = useState(false)

  async function create(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await api.post(`${V1}/clients/${client.id}/vendors/`, { canonical_name: name.trim(), gstin: gstin.trim().toUpperCase(), rcm_default: rcm, tds_section: tds })
      setName('')
      setGstin('')
      setRcm(false)
      setTds('')
      vendors.reload()
    } catch (err) {
      setError(err)
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      {can('vendor.manage') && (
        <div className="panel">
          <div className="panel-head">
            <h2>Add a party</h2>
          </div>
          <div className="panel-body">
            <p className="sub">The ledger says what kind of expense it was; the party says who it was with. Reverse-charge and TDS defaults live here because they are properties of who you are paying.</p>
            <form onSubmit={create}>
              <div className="inline-form">
                <Field label="Name">
                  <input type="text" required value={name} onChange={(e) => setName(e.target.value)} />
                </Field>
                <Field label="GSTIN" hint="Optional. Checked for shape and check digit; stored encrypted.">
                  <input type="text" value={gstin} onChange={(e) => setGstin(e.target.value)} maxLength={15} className="mono" />
                </Field>
                <Field label="TDS section (default)">
                  <select value={tds} onChange={(e) => setTds(e.target.value)}>
                    {TDS_SECTIONS.map((t) => (
                      <option key={t.value} value={t.value}>
                        {t.label}
                      </option>
                    ))}
                  </select>
                </Field>
                <label className="check">
                  <input type="checkbox" checked={rcm} onChange={(e) => setRcm(e.target.checked)} />
                  Reverse charge by default
                </label>
                <Button kind="primary" type="submit" busy={busy}>
                  Add
                </Button>
              </div>
            </form>
            <ErrorNote error={error} />
          </div>
        </div>
      )}
      <div className="panel">
        <div className="panel-head">
          <h2>Parties</h2>
          <span className="sub">{vendors.data?.length ?? 0}</span>
        </div>
        <ErrorNote error={vendors.error} />
        {vendors.loading ? (
          <Spinner />
        ) : !vendors.data?.length ? (
          <Empty title="No parties yet">Parties are created here or while placing a row in the review queue.</Empty>
        ) : (
          <div className="table-wrap">
            <table className="grid">
              <thead>
                <tr>
                  <th>Party</th>
                  <th>GSTIN</th>
                  <th>Defaults</th>
                  <th>Alias sent to the model</th>
                </tr>
              </thead>
              <tbody>
                {vendors.data.map((v) => (
                  <tr key={v.id}>
                    <td>
                      <strong>{v.canonical_name}</strong> {!v.is_active && <Badge>Inactive</Badge>}
                    </td>
                    <td className="mono">{v.gstin || '—'}</td>
                    <td className="pill-row">
                      {v.rcm_default && <Badge tone="warn">RCM</Badge>}
                      {v.tds_section && <Badge tone="info">TDS {v.tds_section}</Badge>}
                    </td>
                    <td className="mono tiny">{v.alias_token}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </>
  )
}
