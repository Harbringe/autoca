// Small, boring building blocks. Boring is the point: an accountant reading
// figures wants a dense, quiet table, not a design system.

import { useEffect, useState, type ReactNode } from 'react'
import { ApiError } from '../api/client'

export function Money({ value, muted }: { value: string | null | undefined; muted?: boolean }) {
  if (!value) return <span className="money muted">—</span>
  return <span className={muted ? 'money muted' : 'money'}>{value}</span>
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return '—'
  const [y, m, d] = iso.slice(0, 10).split('-')
  return `${d}-${m}-${y}`
}

export function formatDateTime(iso: string | null | undefined): string {
  if (!iso) return '—'
  const date = new Date(iso)
  return date.toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short' })
}

export function Badge({ tone = 'neutral', children }: { tone?: 'neutral' | 'good' | 'warn' | 'bad' | 'info'; children: ReactNode }) {
  return <span className={`badge badge-${tone}`}>{children}</span>
}

export function BandBadge({ band }: { band: 'HIGH' | 'ADVISED' | 'JUDGEMENT' }) {
  const tone = band === 'HIGH' ? 'good' : band === 'ADVISED' ? 'warn' : 'bad'
  const label = band === 'HIGH' ? 'Ready to post' : band === 'ADVISED' ? 'Worth a look' : 'Needs an answer'
  return <Badge tone={tone}>{label}</Badge>
}

export function ErrorNote({ error, className = '' }: { error: unknown; className?: string }) {
  if (!error) return null
  let text: string
  let fields: [string, string[]][] = []
  if (error instanceof ApiError) {
    text = error.message
    fields = Object.entries(error.fields)
  } else if (error instanceof Error) {
    text = error.message
  } else {
    text = String(error)
  }
  return (
    <div className={`note note-bad ${className}`} role="alert">
      <div>{text}</div>
      {fields.length > 0 && (
        <ul>
          {fields.map(([name, messages]) => (
            <li key={name}>
              <strong>{name}</strong>: {messages.join(' ')}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

export function Note({ tone = 'info', children }: { tone?: 'info' | 'good' | 'warn' | 'bad'; children: ReactNode }) {
  return <div className={`note note-${tone}`}>{children}</div>
}

export function Spinner({ label = 'Loading…' }: { label?: string }) {
  return (
    <div className="spinner" role="status">
      <span className="spinner-dot" /> {label}
    </div>
  )
}

export function Empty({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="empty">
      <h3>{title}</h3>
      {children && <p>{children}</p>}
    </div>
  )
}

export function Modal({ title, onClose, children, wide }: { title: string; onClose: () => void; children: ReactNode; wide?: boolean }) {
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => event.key === 'Escape' && onClose()
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])
  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div className={wide ? 'modal modal-wide' : 'modal'} role="dialog" aria-modal="true" aria-label={title} onClick={(e) => e.stopPropagation()}>
        <header className="modal-head">
          <h2>{title}</h2>
          <button type="button" className="btn btn-ghost" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </header>
        <div className="modal-body">{children}</div>
      </div>
    </div>
  )
}

export function Field({ label, hint, error, children }: { label: string; hint?: string; error?: string; children: ReactNode }) {
  return (
    <label className="field">
      <span className="field-label">{label}</span>
      {children}
      {hint && !error && <span className="field-hint">{hint}</span>}
      {error && <span className="field-error">{error}</span>}
    </label>
  )
}

export function Button({
  children,
  kind = 'default',
  busy,
  ...rest
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { kind?: 'default' | 'primary' | 'danger' | 'ghost'; busy?: boolean }) {
  return (
    <button type="button" className={`btn btn-${kind}`} disabled={busy || rest.disabled} {...rest}>
      {busy ? 'Working…' : children}
    </button>
  )
}

export function useAsync<T>(load: () => Promise<T>, deps: unknown[]): { data: T | null; error: unknown; loading: boolean; reload: () => void } {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<unknown>(null)
  const [loading, setLoading] = useState(true)
  const [tick, setTick] = useState(0)
  useEffect(() => {
    let live = true
    setLoading(true)
    setError(null)
    load().then(
      (result) => live && (setData(result), setLoading(false)),
      (err) => live && (setError(err), setLoading(false)),
    )
    return () => {
      live = false
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, tick])
  return { data, error, loading, reload: () => setTick((t) => t + 1) }
}

export function Confidence({ value }: { value: number }) {
  const pct = Math.round(value * 100)
  return (
    <span className="confidence" title={`${pct}% confidence`}>
      <span className="confidence-bar">
        <span className={`confidence-fill conf-${value >= 0.9 ? 'high' : value >= 0.75 ? 'mid' : 'low'}`} style={{ width: `${pct}%` }} />
      </span>
      <span className="confidence-num">{pct}%</span>
    </span>
  )
}
