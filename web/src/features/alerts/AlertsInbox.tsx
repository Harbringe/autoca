// The Alerts inbox: the list on the left, in the groups the person chose, and on the right the one that is selected, with what is wrong, what to do
// about it, the button that goes there, and what else is open for the same client. With one client it is a plain list: nobody needs to be told
// whose it is, so the client is left off the rows and the client menu and grouping are not offered.
//
// Keys: J and K for the next and the previous alert, O to open the one selected, and the arrows once the list has focus.

import { Link, useNavigate } from '@tanstack/react-router'
import { ChevronDown } from 'lucide-react'
import { useEffect, useMemo, useRef, useState, type KeyboardEvent } from 'react'
import type { Alert, AlertModule } from '@/api/types'
import { Money } from '@/components/ca/Money'
import { EmptyState } from '@/components/ca/Page'
import { Pager, useFadeOnChange, usePaged } from '@/components/ca/Pager'
import { Button } from '@/components/ui/button'
import { DropdownMenu, DropdownMenuContent, DropdownMenuRadioGroup, DropdownMenuRadioItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { GlideChips } from '@/components/ui/glide-chips'
import { Kbd } from '@/components/ui/kbd'
import { useHotkey } from '@/lib/hotkeys'
import { plural } from '@/lib/format'
import { initialsOf } from '@/lib/useDebounced'
import { cn } from '@/lib/utils'
import { actionLabel, adviceFor } from './alertAdvice'
import { alertKey, clientsOf, flatten, groupAlerts, severityCounts, sortAlerts, type GroupBy, type SeverityFilter } from './alertView'
import { MODULE_LABEL, SEVERITY_LABEL, SeverityMark } from './AlertList'
import { ClientFilter } from './ClientFilter'

export interface InboxFilter {
  module?: AlertModule
  client?: string
}

const MODULES = Object.keys(MODULE_LABEL) as AlertModule[]

/** An element id for an alert: its key with anything an id should not hold taken out. */
const domId = (a: Alert) => `alert-${alertKey(a).replace(/[^a-zA-Z0-9_-]/g, '_')}`

/** Two letters for a client, in a small tile: who the alert belongs to, at a glance. */
function Initials({ name, className }: { name: string; className?: string }) {
  return (
    <span aria-hidden className={cn('grid size-6 shrink-0 place-items-center rounded-md border bg-muted text-[10px] font-bold text-foreground', className)}>
      {initialsOf(name).slice(0, 2)}
    </span>
  )
}

export function AlertsInbox({ alerts, filter, onFilter }: { alerts: Alert[]; filter: InboxFilter; onFilter: (next: InboxFilter) => void }) {
  const navigate = useNavigate()
  const [severity, setSeverity] = useState<SeverityFilter>('all')
  const [groupBy, setGroupBy] = useState<GroupBy>('severity')
  const [selectedKey, setSelectedKey] = useState<string | null>(null)

  const clients = useMemo(() => clientsOf(alerts), [alerts])
  const many = clients.length > 1
  // The module and the client narrow what the counts mean; the severity chip then narrows the list itself.
  const pool = useMemo(() => alerts.filter((a) => (!filter.module || a.module === filter.module) && (!filter.client || a.client === filter.client)), [alerts, filter])
  const counts = severityCounts(pool)
  const visible = useMemo(() => (severity === 'all' ? pool : pool.filter((a) => a.severity === severity)), [pool, severity])
  const by: GroupBy = many ? groupBy : 'none'
  const flat = useMemo(() => flatten(groupAlerts(visible, by)), [visible, by])

  const index = Math.max(0, flat.findIndex((a) => alertKey(a) === selectedKey))
  const selected = flat[index] ?? null
  const pager = usePaged(flat, `${by}|${severity}|${filter.module ?? ''}|${filter.client ?? ''}`)
  const listRef = useRef<HTMLUListElement>(null)
  const listKey = `${by}|${severity}|${filter.module ?? ''}|${filter.client ?? ''}|${pager.page}`
  useFadeOnChange(listRef, listKey)
  // A new page, grouping or filter starts at the top of the list.
  useEffect(() => {
    // (A statement, not the bare call: in current browsers scrollTo returns a promise, which an effect must not return.)
    listRef.current?.scrollTo?.({ top: 0 })
  }, [listKey])

  // Keep one selected: the first on arrival, and the one now in the same place after an alert goes. Its page is the page shown.
  useEffect(() => {
    if (flat.length && !flat.some((a) => alertKey(a) === selectedKey)) setSelectedKey(alertKey(flat[Math.min(index, flat.length - 1)]!))
  }, [flat, selectedKey, index])
  useEffect(() => {
    if (selected) pager.reveal(index)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedKey])
  useEffect(() => {
    if (pager.items.length && !pager.items.some((a) => alertKey(a) === selectedKey)) setSelectedKey(alertKey(pager.items[0]!))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pager.page])

  const select = (next: number, focus = false) => {
    const target = flat[Math.min(Math.max(next, 0), flat.length - 1)]
    if (!target) return
    setSelectedKey(alertKey(target))
    requestAnimationFrame(() => {
      const el = document.getElementById(domId(target))
      el?.scrollIntoView?.({ block: 'nearest' })
      if (focus) el?.focus({ preventScroll: true })
    })
  }
  const open = (alert: Alert | null) => alert && void navigate({ to: alert.to as never, search: alert.search as never })
  useHotkey('j', 'Next alert', () => select(index + 1), 'Alerts')
  useHotkey('k', 'Previous alert', () => select(index - 1), 'Alerts')
  useHotkey('o', 'Open the selected alert', () => open(selected), 'Alerts')

  const onListKey = (e: KeyboardEvent<HTMLUListElement>) => {
    if (e.key === 'ArrowDown') select(index + 1, true)
    else if (e.key === 'ArrowUp') select(index - 1, true)
    else if (e.key === 'Home') select(0, true)
    else if (e.key === 'End') select(flat.length - 1, true)
    else if (e.key === 'Enter') open(selected)
    else return
    e.preventDefault()
  }

  const groups = groupAlerts(pager.items, by)
  const others = selected ? sortAlerts(alerts.filter((a) => a.client === selected.client && alertKey(a) !== alertKey(selected))) : []
  const filtered = !!filter.module || !!filter.client || severity !== 'all'

  return (
    <div className="grid gap-4">
      <div className="flex flex-wrap items-center gap-2">
        <GlideChips
          label="Severity"
          value={severity}
          onChange={setSeverity}
          options={[
            { value: 'all', label: `All ${counts.all}` },
            { value: 'critical', label: `${SEVERITY_LABEL.critical} ${counts.critical}`, disabled: counts.critical === 0 && severity !== 'critical' },
            { value: 'high', label: `${SEVERITY_LABEL.high} ${counts.high}`, disabled: counts.high === 0 && severity !== 'high' },
            { value: 'medium', label: `${SEVERITY_LABEL.medium} ${counts.medium}`, disabled: counts.medium === 0 && severity !== 'medium' },
          ]}
        />
        {many && <ClientFilter clients={clients} value={filter.client} total={alerts.length} onChange={(client) => onFilter({ ...filter, client })} />}
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="outline" size="sm" className="h-9 gap-2 rounded-full px-3.5">
              <span className="text-muted-foreground">Module:</span>
              <span>{filter.module ? MODULE_LABEL[filter.module] : 'All'}</span>
              <ChevronDown className="size-4 text-muted-foreground" aria-hidden />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start" aria-label="Choose a module">
            <DropdownMenuRadioGroup value={filter.module ?? 'all'} onValueChange={(v) => onFilter({ ...filter, module: v === 'all' ? undefined : (v as AlertModule) })}>
              <DropdownMenuRadioItem value="all">All modules</DropdownMenuRadioItem>
              {MODULES.filter((m) => alerts.some((a) => a.module === m) || filter.module === m).map((m) => (
                <DropdownMenuRadioItem key={m} value={m}>
                  {MODULE_LABEL[m]}
                </DropdownMenuRadioItem>
              ))}
            </DropdownMenuRadioGroup>
          </DropdownMenuContent>
        </DropdownMenu>
        <span className="flex-1" />
        {many && (
          <GlideChips
            label="Group by"
            value={groupBy}
            onChange={setGroupBy}
            options={[
              { value: 'severity', label: 'By severity' },
              { value: 'client', label: 'By client' },
              { value: 'none', label: 'Flat' },
            ]}
          />
        )}
      </div>

      {flat.length === 0 ? (
        <EmptyState title={filtered ? 'Nothing matches these filters' : 'All clear'}>
          {filtered ? (
            <button
              type="button"
              className="underline"
              onClick={() => {
                setSeverity('all')
                onFilter({})
              }}
            >
              Clear the filters
            </button>
          ) : (
            'Nothing here needs a person. New alerts appear as statements arrive and deadlines come close.'
          )}
        </EmptyState>
      ) : (
        <div className="grid h-[calc(100svh-17rem)] min-h-[30rem] overflow-hidden rounded-xl border border-border-strong bg-card lg:grid-cols-[minmax(0,1fr)_380px] max-lg:h-auto">
          <div className="flex min-h-0 min-w-0 flex-col">
            <ul
              ref={listRef}
              role="listbox"
              aria-label="Alerts"
              onKeyDown={onListKey}
              className="min-h-0 flex-1 overflow-y-auto overscroll-contain"
            >
              {groups.map((group) => (
                <li key={group.key} role="presentation">
                  <div
                    role="presentation"
                    className="sticky top-0 z-[1] flex items-center gap-2.5 border-b border-border-strong bg-background px-4 py-2 text-xs font-bold uppercase tracking-wide text-muted-foreground"
                  >
                    {group.severity ? <SeverityMark severity={group.severity} className="text-xs" /> : group.client ? <><Initials name={group.client.name} />{' '}<span className="text-foreground">{group.label}</span></> : <span>{group.label}</span>}
                    <span className="num ml-auto font-mono">{group.items.length}</span>
                  </div>
                  <ul role="group" aria-label={group.label}>
                    {group.items.map((alert, i) => {
                      const key = alertKey(alert)
                      const isSelected = key === selectedKey
                      return (
                        <li
                          key={key}
                          id={domId(alert)}
                          role="option"
                          aria-selected={isSelected}
                          tabIndex={isSelected ? 0 : -1}
                          onClick={() => setSelectedKey(key)}
                          style={{ animationDelay: `${Math.min(i, 10) * 28}ms` }}
                          className={cn(
                            'rise relative flex cursor-pointer items-center gap-3 border-b border-border-strong px-4 py-3 outline-none transition-colors duration-150 hover:bg-hover focus-visible:bg-hover',
                            // The bar at the left grows in rather than appearing: a transform, which costs nothing to paint.
                            'before:absolute before:inset-y-0 before:left-0 before:w-[3px] before:origin-center before:scale-y-0 before:bg-primary before:transition-transform before:duration-200',
                            isSelected && 'bg-hover before:scale-y-100',
                          )}
                        >
                          <span className="min-w-0 flex-1">
                            <span className="flex items-center gap-2">
                              <SeverityMark severity={alert.severity} />
                              {many && by !== 'client' && (
                                <span className="flex min-w-0 items-center gap-1.5 text-xs text-muted-foreground">
                                  <Initials name={alert.client_name} className="size-5 text-[9px]" />
                                  <b className="max-w-40 truncate font-semibold text-foreground">{alert.client_name}</b>
                                </span>
                              )}
                            </span>
                            <span className="mt-0.5 block font-medium text-heading">{alert.title}</span>
                          </span>
                          {alert.amount_display && <Money display={alert.amount_display} className="num shrink-0 text-[13px] font-semibold" />}
                        </li>
                      )
                    })}
                  </ul>
                </li>
              ))}
            </ul>
            <Pager paged={pager} label="Alerts" className="flex flex-wrap items-center justify-between gap-3 border-t border-border-strong px-4 py-2.5 text-sm" />
          </div>

          {selected && (
            <aside key={alertKey(selected)} aria-label="Alert detail" className="rise min-h-0 overflow-y-auto overscroll-contain border-l border-border-strong bg-background p-5 max-lg:border-l-0 max-lg:border-t">
              {many ? (
                <div className="mb-2 flex items-center gap-2 text-sm text-muted-foreground">
                  <Initials name={selected.client_name} />
                  <b className="font-semibold text-foreground">{selected.client_name}</b>
                  <span>· {MODULE_LABEL[selected.module]}</span>
                </div>
              ) : (
                <div className="mb-2 text-xs text-muted-foreground">{MODULE_LABEL[selected.module]}</div>
              )}
              <SeverityMark severity={selected.severity} />
              <h2 className="mt-1.5 text-xl font-semibold text-heading">{selected.title}</h2>
              <p className="mt-1 text-sm text-muted-foreground">{selected.detail}</p>
              {(selected.amount_display || selected.count > 1) && (
                <dl className="mt-4 divide-y rounded-lg border bg-card text-sm">
                  {selected.amount_display && (
                    <div className="flex justify-between gap-3 px-3 py-2">
                      <dt className="text-muted-foreground">Amount</dt>
                      <dd>
                        <Money display={selected.amount_display} className="num font-semibold" />
                      </dd>
                    </div>
                  )}
                  {selected.count > 1 && (
                    <div className="flex justify-between gap-3 px-3 py-2">
                      <dt className="text-muted-foreground">How many</dt>
                      <dd className="num font-semibold">{selected.count}</dd>
                    </div>
                  )}
                </dl>
              )}
              <h3 className="mb-1 mt-5 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">What to do</h3>
              <p className="text-sm">{adviceFor(selected)}</p>
              <div className="mt-4 flex flex-wrap gap-2">
                <Button asChild>
                  <Link to={selected.to as never} search={selected.search as never} aria-keyshortcuts="O">
                    {actionLabel(selected)} <Kbd className="ml-1 border-primary-foreground/30 bg-transparent text-primary-foreground">O</Kbd>
                  </Link>
                </Button>
                <Button variant="outline" onClick={() => select(index + 1)} disabled={flat.length < 2} aria-keyshortcuts="J">
                  Next alert <Kbd>J</Kbd>
                </Button>
              </div>
              {many && others.length > 0 && (
                <section aria-label={`Also open for ${selected.client_name}`} className="mt-6">
                  <h3 className="flex flex-wrap items-center gap-2 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
                    Also open for {selected.client_name}
                    {(['critical', 'high', 'medium'] as const).map((s) => {
                      const n = others.filter((a) => a.severity === s).length
                      return n ? (
                        <span key={s} className={cn('num rounded-full border px-2 text-xs normal-case', s === 'critical' ? 'border-destructive/40 bg-destructive-bg text-destructive' : s === 'high' ? 'border-accent-edge bg-accent text-accent-foreground' : 'text-muted-foreground')}>
                          {n} {SEVERITY_LABEL[s]}
                        </span>
                      ) : null
                    })}
                  </h3>
                  <ul className="mt-1">
                    {others.map((a) => (
                      <li key={alertKey(a)}>
                        <button
                          type="button"
                          onClick={() => setSelectedKey(alertKey(a))}
                          className="flex w-full items-center gap-2 rounded-md px-1 py-1.5 text-left text-sm hover:bg-hover"
                        >
                          <SeverityMark severity={a.severity} />
                          <span className="min-w-0 truncate">{a.title}</span>
                        </button>
                      </li>
                    ))}
                  </ul>
                </section>
              )}
              <p className="mt-6 text-xs text-muted-foreground">
                <Kbd>J</Kbd> <Kbd>K</Kbd> next and previous · <Kbd>O</Kbd> open · {plural(flat.length, 'alert')} in this list
              </p>
            </aside>
          )}
        </div>
      )}
    </div>
  )
}
