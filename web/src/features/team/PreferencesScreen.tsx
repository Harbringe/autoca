// Preferences: how this person likes the screen. They live in this browser only, never on the server.
//
// A short menu on the left and one topic at a time on the right. Every topic shows a live sample of what it changes: the theme and the row
// spacing on a few Review rows, the search switch on a search, and the rows per page on a skeleton of the page being set.

import { type ReactNode, useState } from 'react'
import { Checkbox } from '@/components/ui/controls'
import { Button } from '@/components/ui/button'
import { GlideChips } from '@/components/ui/glide-chips'
import { ShortcutGuide } from '@/features/shell/ShortcutSheet'
import { usePreferences, type Density, type Theme } from '@/lib/preferences'
import { SIZE_CHOICES, pageSizeOf, setAllPageSize, setSectionPageSize, usePageSizeChoices, type PageSection } from '@/lib/pageSizes'
import { setSearchAllStatements, useSearchAllStatements } from '@/lib/reviewPrefs'
import { usePageTitle } from '@/lib/title'
import { cn } from '@/lib/utils'

type Topic = 'look' | 'review' | 'lists' | 'keys'
const TOPICS: { id: Topic; label: string }[] = [
  { id: 'look', label: 'Look' },
  { id: 'review', label: 'Review' },
  { id: 'lists', label: 'Rows per page' },
  { id: 'keys', label: 'Keyboard' },
]

function Heading({ children }: { children: ReactNode }) {
  return <h3 className="mb-4 text-lg font-semibold text-heading">{children}</h3>
}

function Label({ children }: { children: ReactNode }) {
  return <div className="mb-1.5 text-[11px] font-bold uppercase tracking-wider text-muted-foreground">{children}</div>
}

/** One choice out of a few, drawn as a card with a small picture of what it does. */
function Cards<T extends string>({ legend, value, onChange, columns, options }: { legend: string; value: T; onChange: (v: T) => void; columns: 2 | 3; options: { value: T; label: string; hint?: string; picture: ReactNode }[] }) {
  return (
    <div role="radiogroup" aria-label={legend} className={cn('grid gap-2.5', columns === 3 ? 'grid-cols-3 max-sm:grid-cols-1' : 'grid-cols-2 max-sm:grid-cols-1')}>
      {options.map((o) => (
        <button
          key={o.value}
          type="button"
          role="radio"
          aria-checked={value === o.value}
          onClick={() => onChange(o.value)}
          className={cn('rounded-xl border bg-card p-2.5 text-left transition-colors duration-150 hover:border-muted-foreground', value === o.value && 'border-primary ring-1 ring-primary')}
        >
          {o.picture}
          <b className="mt-2 block text-sm">{o.label}</b>
          {o.hint && <span className="text-xs text-muted-foreground">{o.hint}</span>}
        </button>
      ))}
    </div>
  )
}

/** A few bars standing for a screen in a theme: the picture on a theme card. */
function ThemePicture({ kind }: { kind: Theme }) {
  const bar = (bg: string, w: string) => <i className="block h-2 rounded-sm" style={{ width: w, background: bg }} />
  const body = (page: string, line: string) => (
    <div className="flex flex-1 flex-col gap-1.5 p-2" style={{ background: page }}>
      {bar(line, '55%')}
      {bar('#4fb3a0', '40%')}
      {bar(line, '80%')}
      {bar(line, '65%')}
    </div>
  )
  return (
    <div aria-hidden className="flex h-[70px] overflow-hidden rounded-lg border">
      {kind !== 'dark' && body('#f4f5f3', '#d6dad5')}
      {kind !== 'light' && body('#0f1113', '#2b3236')}
    </div>
  )
}

function DensityPicture({ rows, gap }: { rows: number; gap: number }) {
  return (
    <div aria-hidden className="flex h-[70px] flex-col overflow-hidden rounded-lg border bg-background px-2 py-1.5">
      {Array.from({ length: rows }, (_, i) => (
        <i key={i} className="block h-2 rounded-sm bg-border-strong" style={{ marginBottom: gap }} />
      ))}
    </div>
  )
}

type SampleRow = [date: string, narration: string, amount: string, statement: string]
const SAMPLE_ROWS: SampleRow[] = [
  ['14-05-2025', 'SAMPLE CUSTOMER ONE', '₹60,00,000.00', 'Apr–Jun 2025'],
  ['14-05-2025', 'Cash Withdrawal At Br : SAMPLETOWN', '₹2,00,000.00', 'Apr–Jun 2025'],
  ['12-04-2025', 'SMS CHRG FOR:01-01-2025to31-03-2025', '₹2.65', 'Jan–Mar 2025'],
  ['22-09-2025', 'Paid To : TO SAMPLE TRADERS PVT LTD', '₹50,00,000.00', 'Jul–Sep 2025'],
  ['29-08-2025', 'REJECT:4:REQUIRED INFORMATIO NOT LEGIBLE', '₹26,00,000.00', 'Jul–Sep 2025'],
  ['12-07-2025', 'SMS CHRG FOR:01-04-2025to30-06-2025', '₹1.47', 'Jul–Sep 2025'],
  ['03-06-2025', 'UPI/ZERODHA BROKING/COLLECTION', '₹1,10,000.00', 'Apr–Jun 2025'],
  ['21-05-2025', 'NEFT-SAMPLE SUPPLIER TWO', '₹30,000.00', 'Apr–Jun 2025'],
]

function SampleRows({ rows, density, showStatement }: { rows: SampleRow[]; density: Density; showStatement?: boolean }) {
  return (
    <div className="overflow-hidden rounded-xl border bg-card">
      {rows.map((r) => (
        <div key={r[0] + r[1]} className={cn('flex items-center gap-3 border-b px-3.5 text-[13px] last:border-b-0 transition-[padding] duration-200', density === 'compact' ? 'py-1.5' : 'py-3.5')}>
          <span className="num w-24 shrink-0 text-muted-foreground">{r[0]}</span>
          <span className="min-w-0 flex-1 truncate">{r[1]}</span>
          {showStatement && <span className="whitespace-nowrap rounded-full border border-info/30 bg-info-bg px-2 text-[11px] font-bold text-info">{r[3]}</span>}
          <span className="num font-semibold">{r[2]}</span>
        </div>
      ))}
    </div>
  )
}

/** The two palettes a theme card can show. A theme is drawn in its own colours, whatever theme the page is in now. */
const PALETTE = {
  dark: { bg: '#0f1113', card: '#161a1c', line: '#2b3236', fg: '#e6eae8', mute: '#98a39e', acc: '#4fb3a0', accInk: '#06201b', rail: '#0b0d0e', sel: '#1b2326' },
  light: { bg: '#f4f5f3', card: '#ffffff', line: '#d6dad5', fg: '#14181a', mute: '#4f5753', acc: '#1e5b4f', accInk: '#ffffff', rail: '#0b0d0e', sel: '#eef4f1' },
}

function useResolvedTheme(theme: Theme): 'light' | 'dark' {
  if (theme !== 'system') return theme
  return typeof window !== 'undefined' && window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
}

/**
 * A small window of the app in the theme and row spacing chosen: the rail, the top bar, a heading with its tabs, and Review rows. It is
 * drawn in the theme's own colours, so a card you have not chosen yet can be seen before you choose it, and spacing shows as it will fall.
 */
function AppPreview({ theme, density }: { theme: Theme; density: Density }) {
  const c = PALETTE[useResolvedTheme(theme)]
  const rows = SAMPLE_ROWS.slice(0, density === 'compact' ? 8 : 5)
  const pad = density === 'compact' ? 6 : 14
  return (
    <div role="img" aria-label={`A preview of the app in the ${theme === 'system' ? 'device' : theme} theme with ${density} rows`} className="overflow-hidden rounded-xl border transition-colors duration-200" style={{ background: c.bg, color: c.fg, borderColor: c.line }}>
      <div className="flex">
        <div className="flex w-11 shrink-0 flex-col items-center gap-2 py-3" style={{ background: c.rail }}>
          <span className="grid size-6 place-items-center rounded-md text-[9px] font-bold text-white" style={{ background: '#2f6f62' }}>CA</span>
          {[0, 1, 2, 3].map((i) => (
            <span key={i} className="size-5 rounded-md" style={{ background: i === 3 ? c.sel : '#1d2326', boxShadow: i === 3 ? `inset 2px 0 0 ${c.acc}` : undefined }} />
          ))}
        </div>
        <div className="min-w-0 flex-1">
          <div className="relative flex h-9 items-center gap-2 border-b px-3 text-[11px]" style={{ borderColor: c.line, color: c.mute }}>
            <span className="absolute inset-x-0 top-0 h-[2px]" style={{ background: '#2f6f62' }} />
            <span>plant’s firm › Laxmi › </span>
            <b style={{ color: c.fg }}>Review</b>
            <span className="ml-auto h-5 w-32 rounded-md border px-2 text-[10px] leading-5" style={{ borderColor: c.line, background: c.card }}>Search or jump</span>
          </div>
          <div className="px-4 pb-4 pt-3">
            <div className="text-lg font-semibold">Review</div>
            <div className="mt-1 flex gap-1 text-[11px]">
              {['Needs a ledger 3', 'Ready to post 46', 'All waiting 49'].map((x, i) => (
                <span key={x} className="rounded-md px-2 py-1" style={i === 1 ? { background: c.sel, color: c.fg, fontWeight: 600 } : { color: c.mute }}>
                  {x}
                </span>
              ))}
              <span className="ml-auto rounded-md px-2 py-1 font-semibold" style={{ background: c.acc, color: c.accInk }}>
                Post all (3)
              </span>
            </div>
            <div className="mt-3 overflow-hidden rounded-lg border text-[12px]" style={{ background: c.card, borderColor: c.line }}>
              {rows.map((r) => (
                <div key={r[0] + r[1]} className="flex items-center gap-3 border-b px-3 last:border-b-0 transition-[padding] duration-200" style={{ borderColor: c.line, paddingBlock: pad }}>
                  <span className="num w-20 shrink-0" style={{ color: c.mute }}>
                    {r[0]}
                  </span>
                  <span className="min-w-0 flex-1 truncate">{r[1]}</span>
                  <span className="num font-semibold">{r[2]}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

function Look() {
  const { theme, setTheme, density, setDensity } = usePreferences()
  return (
    <>
      <Heading>Look</Heading>
      <div className="grid gap-6 xl:grid-cols-[minmax(0,420px)_minmax(0,1fr)]">
        <div className="grid content-start gap-5">
          <div>
            <Label>Theme</Label>
            <Cards
              legend="Theme"
              columns={3}
              value={theme}
              onChange={setTheme}
              options={[
                { value: 'light', label: 'Light', picture: <ThemePicture kind="light" /> },
                { value: 'dark', label: 'Dark', picture: <ThemePicture kind="dark" /> },
                { value: 'system', label: 'Match my device', picture: <ThemePicture kind="system" /> },
              ]}
            />
          </div>
          <div>
            <Label>Rows</Label>
            <Cards
              legend="Rows"
              columns={2}
              value={density}
              onChange={setDensity}
              options={[
                { value: 'comfortable', label: 'Comfortable', hint: 'More room around each row', picture: <DensityPicture rows={4} gap={9} /> },
                { value: 'compact', label: 'Compact', hint: 'More rows on a screen', picture: <DensityPicture rows={7} gap={2} /> },
              ]}
            />
          </div>
        </div>
        <div className="min-w-0">
          <Label>Preview: the app as you have chosen it</Label>
          <AppPreview theme={theme} density={density} />
          <p className="mt-1.5 text-[13px] text-muted-foreground" aria-live="polite">
            {density === 'compact' ? 'Compact fits more rows on a screen.' : 'Comfortable gives each row more room.'}
          </p>
        </div>
      </div>
    </>
  )
}

/** A search over Review's rows, as it reads with the setting off or on, so the two can be set side by side. */
function SearchSample({ on, current, density, onChoose }: { on: boolean; current: boolean; density: Density; onChoose: () => void }) {
  const rows = on ? SAMPLE_ROWS.slice(0, 5) : SAMPLE_ROWS.filter((r) => r[3] === 'Apr–Jun 2025')
  return (
    // The picture is the control: pressing it chooses that way. It is a radio of a pair, so the keyboard works as it does for any radio.
    <div
      role="radio"
      aria-checked={current}
      tabIndex={0}
      onClick={onChoose}
      onKeyDown={(e) => {
        if (e.key === 'Enter' || e.key === ' ') {
          e.preventDefault()
          onChoose()
        }
      }}
      className={cn('cursor-pointer rounded-xl border bg-card p-3 transition-colors duration-200 hover:border-muted-foreground', current && 'border-primary bg-selected ring-1 ring-primary')}
    >
      <div className="mb-2 flex items-center justify-between gap-2">
        <b className="text-sm">{on ? 'On: every statement' : 'Off: this statement only'}</b>
        <span className={cn('rounded-full px-2 py-0.5 text-[11px] font-semibold', current ? 'bg-primary text-primary-foreground' : 'border text-muted-foreground')}>{current ? 'Selected' : 'Press to choose'}</span>
      </div>
      <div className="mb-2 flex h-8 items-center gap-2 rounded-lg border bg-background px-2.5 text-[13px]">
        <span aria-hidden>⌕</span>a<span className="text-xs text-muted-foreground"> · searching {on ? 'all 3 statements' : 'Apr–Jun 2025'}</span>
      </div>
      <SampleRows rows={rows} density={density} showStatement={on} />
      <p className="mt-1.5 text-[13px] text-muted-foreground">
        {on ? `${rows.length} rows found, each tagged with where it is from.` : `${rows.length} rows found, in the statement being reviewed only.`}
      </p>
    </div>
  )
}

function ReviewTopic() {
  const searchAll = useSearchAllStatements()
  const { density } = usePreferences()
  return (
    <>
      <Heading>Review</Heading>
      <div className="mb-5 flex items-start gap-4 rounded-xl border bg-card p-4">
        <div className="flex-1">
          <Checkbox label={<b className="text-sm font-semibold">Search every bank statement</b>} checked={searchAll} onChange={(e) => setSearchAllStatements(e.target.checked)} />
          <p className="ml-7 mt-1 text-[13px] text-muted-foreground">
            Review works through one statement at a time. With this on, its search box looks through all of the client’s statements, and shows where each row is from.
          </p>
        </div>
      </div>
      <Label>Preview: the same search, both ways. Press one to choose it.</Label>
      <div role="radiogroup" aria-label="Which way to search" className="grid gap-4 lg:grid-cols-2">
        <SearchSample on={false} current={!searchAll} density={density} onChoose={() => setSearchAllStatements(false)} />
        <SearchSample on current={searchAll} density={density} onChoose={() => setSearchAllStatements(true)} />
      </div>
    </>
  )
}

// ----------------------------------------------------------------------------------------------- rows per page
interface ListInfo {
  id: PageSection | 'all'
  label: string
  sub: string
  /** An example total, to show how many pages that makes. */
  total: number
}
const LISTS: ListInfo[] = [
  { id: 'all', label: 'All lists', sub: 'One number for every list', total: 312 },
  { id: 'review', label: 'Review queue', sub: 'Review', total: 312 },
  { id: 'daybook', label: 'Day Book', sub: 'Bookkeeping › Day Book', total: 1284 },
  { id: 'statements', label: 'Statement rows', sub: 'Bank statements › one statement', total: 842 },
  { id: 'ledger', label: 'A ledger’s entries', sub: 'Ledgers › one ledger', total: 96 },
  { id: 'parties', label: 'Parties found', sub: 'Parties & rules', total: 41 },
  { id: 'alerts', label: 'Alerts', sub: 'Alerts', total: 23 },
  { id: 'activity', label: 'Activity log', sub: 'Settings › Activity log', total: 530 },
]

/** A bar standing for a bit of text or a figure. */
const Bar = ({ w, h = 10, accent }: { w: number | string; h?: number; accent?: boolean }) => (
  <span aria-hidden className={cn('block shrink-0 rounded-[5px]', accent ? 'bg-primary/55' : 'bg-border-strong')} style={{ width: w, height: h }} />
)
const vary = (i: number, base: number, spread: number) => Math.max(18, base - ((i * 7 + 3) % spread))

interface Shape {
  title: string
  top: ReactNode
  head?: [string, number][]
  /** Row height in px, comfortable and compact. */
  h: [number, number]
  row: (i: number, h: number) => ReactNode
}
const Row = ({ h, children }: { h: number; children: ReactNode }) => (
  <div className="flex items-center gap-3.5 border-b px-3.5" style={{ height: h }}>
    {children}
  </div>
)
const flex = (children: ReactNode, col = false) => <span className={cn('flex min-w-0 flex-1', col ? 'flex-col gap-1.5' : '')}>{children}</span>
const Tools = ({ widths }: { widths: (number | string)[] }) => (
  <div className="mb-2.5 flex flex-wrap gap-2.5">
    {widths.map((w, i) => (
      <Bar key={i} w={w} h={30} />
    ))}
  </div>
)

const SHAPES: Record<PageSection | 'all', Shape> = {
  all: { title: 'Any list', top: <Tools widths={[180, 110]} />, h: [44, 30], row: (i, h) => (
    <Row h={h}><Bar w={70} />{flex(<Bar w={`${vary(i, 80, 30)}%`} />)}<Bar w={90} /></Row>
  ) },
  review: { title: 'Review', top: <Tools widths={[96, 104, 112, 120]} />, h: [64, 38], row: (i, h) => (
    <Row h={h}><Bar w={18} h={18} /><Bar w={70} />{flex(<><Bar w={`${vary(i, 80, 30)}%`} /><Bar w={`${vary(i, 46, 20)}%`} h={8} accent /></>, true)}<Bar w={88} /></Row>
  ) },
  daybook: { title: 'Day Book', top: <Tools widths={[170, 120, 120, 90]} />, head: [['Date', 70], ['No.', 46], ['Particulars', 0], ['Debit', 84], ['Credit', 84]], h: [48, 32], row: (i, h) => (
    <Row h={h}><Bar w={70} /><Bar w={46} />{flex(<Bar w={`${vary(i, 78, 30)}%`} />)}<Bar w={84} /><Bar w={84} /></Row>
  ) },
  statements: { title: 'Statement rows', top: <Tools widths={[220, 130, 100]} />, head: [['Date', 70], ['Narration', 0], ['Withdrawal', 80], ['Deposit', 80], ['Balance', 90]], h: [44, 30], row: (i, h) => (
    <Row h={h}><Bar w={70} />{flex(<Bar w={`${vary(i, 82, 34)}%`} />)}<Bar w={80} /><Bar w={80} /><Bar w={90} /></Row>
  ) },
  ledger: { title: 'Ledger', top: <Tools widths={[200, 130]} />, head: [['Date', 70], ['Particulars', 0], ['Debit', 76], ['Credit', 76], ['Balance', 90]], h: [46, 30], row: (i, h) => (
    <Row h={h}><Bar w={70} />{flex(<Bar w={`${vary(i, 70, 30)}%`} />)}<Bar w={76} /><Bar w={76} /><Bar w={90} /></Row>
  ) },
  parties: { title: 'Parties & rules', top: <Tools widths={[96, 104]} />, h: [58, 36], row: (i, h) => (
    <Row h={h}><span aria-hidden className="size-[30px] shrink-0 rounded-full bg-border-strong" />{flex(<><Bar w={`${vary(i, 50, 24)}%`} /><Bar w={`${vary(i, 34, 14)}%`} h={8} /></>, true)}<Bar w={110} accent /><Bar w={60} /></Row>
  ) },
  alerts: { title: 'Alerts', top: <Tools widths={[70, 78, 86, 94]} />, h: [66, 40], row: (i, h) => (
    <Row h={h}>{flex(<><Bar w={60} h={8} accent /><Bar w={`${vary(i, 62, 24)}%`} /><Bar w={`${vary(i, 40, 14)}%`} h={8} /></>, true)}<Bar w={70} /></Row>
  ) },
  activity: { title: 'Activity log', top: <Tools widths={[180, 140, 110]} />, head: [['When', 110], ['What happened', 0]], h: [42, 28], row: (i, h) => (
    <Row h={h}><Bar w={110} />{flex(<Bar w={`${vary(i, 86, 40)}%`} />)}</Row>
  ) },
  firm: { title: 'People and clients', top: <Tools widths={[160]} />, h: [56, 36], row: (i, h) => (
    <Row h={h}><span aria-hidden className="size-8 shrink-0 rounded-md bg-border-strong" />{flex(<><Bar w={`${vary(i, 50, 24)}%`} /><Bar w={`${vary(i, 34, 14)}%`} h={8} /></>, true)}<Bar w={80} /></Row>
  ) },
}

const fmt = (n: number) => n.toLocaleString('en-IN')

/** The page being set, drawn as bars, with as many rows as the number chosen and a line where a typical screen ends. */
function PagePreview({ info, size, density }: { info: ListInfo; size: number; density: Density }) {
  const shape = SHAPES[info.id]
  const h = density === 'compact' ? shape.h[1] : shape.h[0]
  const n = Math.min(size, info.total)
  const onScreen = Math.floor(400 / h)
  const pages = Math.ceil(info.total / size)
  const numbers = Array.from({ length: Math.min(pages, 4) }, (_, i) => i + 1)
  return (
    <section aria-label={`Preview of ${info.label}`} className="overflow-hidden rounded-xl border bg-card">
      <div className="flex flex-wrap items-center justify-between gap-3 border-b bg-selected px-4 py-3 text-sm">
        <span>
          <b>Previewing: {info.label}</b> <span className="text-[13px] text-muted-foreground">· {info.sub}</span>
        </span>
        <span className="text-[13px] text-muted-foreground" aria-live="polite">
          <b className="num text-foreground">{size}</b> rows per page · <b className="num text-foreground">{pages}</b> page{pages === 1 ? '' : 's'} for {fmt(info.total)} rows (example)
        </span>
      </div>
      <div className="bg-background px-4 pt-3.5">
        <h4 className="mb-2.5 text-[22px] font-semibold text-heading">{shape.title}</h4>
        {shape.top}
        <div tabIndex={0} aria-label="Rows on one page" className="h-[440px] overflow-auto rounded-[10px] border bg-card">
          {shape.head && (
            <div className="sticky top-0 z-[2] flex h-[34px] items-center gap-3.5 border-b bg-selected px-3.5">
              {shape.head.map(([name, w]) => (
                <span key={name} className="text-xs text-muted-foreground" style={w ? { width: w, flex: 'none' } : { flex: 1 }}>
                  {name}
                </span>
              ))}
            </div>
          )}
          {Array.from({ length: n }, (_, i) => (
            <div key={i}>
              {shape.row(i, h)}
              {i === onScreen - 1 && n > onScreen && (
                <div className="relative z-[1] h-0 border-t-2 border-dashed border-warning">
                  <span className="absolute -top-[11px] right-2.5 rounded-full border border-warning bg-card px-2 text-[11px] font-bold text-warning">A typical screen ends here</span>
                </div>
              )}
            </div>
          ))}
        </div>
        <div key={size} className="rise my-3 flex flex-wrap items-center justify-between gap-2.5 rounded-[10px] border-2 border-primary bg-selected px-3.5 py-2.5">
          <span className="text-[13px]">
            <b className="num">1–{n}</b> of <span className="num">{fmt(info.total)}</span> · <b>{size} rows per page</b>
          </span>
          <span className="flex gap-1" aria-hidden>
            {['‹', ...numbers.map(String), ...(pages > 5 ? ['…'] : []), ...(pages > 4 ? [String(pages)] : []), '›'].map((c, i) => (
              <span key={i} className={cn('grid h-7 min-w-7 place-items-center rounded-md border bg-card text-[13px] font-semibold', c === '1' && 'border-foreground bg-foreground text-background')}>
                {c}
              </span>
            ))}
          </span>
        </div>
      </div>
    </section>
  )
}

function Lists() {
  const chosen = usePageSizeChoices()
  const { density } = usePreferences()
  const [pick, setPick] = useState<ListInfo['id']>('review')
  const sizeOf = (id: ListInfo['id']) => (id === 'all' ? (chosen.all ?? 10) : pageSizeOf(id, chosen))
  const info = LISTS.find((l) => l.id === pick)!
  const isReset = chosen.all === null && Object.keys(chosen.by).length === 0
  return (
    <>
      <Heading>Rows per page</Heading>
      <p className="-mt-2 mb-4 text-[13px] text-muted-foreground">
        How many rows a list shows before it pages. Pick a page, change its number, and the preview redraws that page with that many rows. Every list starts at 10.
      </p>
      <div className="grid gap-5 lg:grid-cols-[320px_minmax(0,1fr)]">
        <div className="content-start">
          <div role="listbox" aria-label="Pages" className="overflow-hidden rounded-xl border bg-card">
            {LISTS.map((l) => {
              const own = l.id !== 'all' && chosen.by[l.id] !== undefined
              return (
                <div
                  key={l.id}
                  role="option"
                  tabIndex={0}
                  aria-selected={pick === l.id}
                  onClick={() => setPick(l.id)}
                  onKeyDown={(e) => {
                    if (e.target === e.currentTarget && (e.key === 'Enter' || e.key === ' ')) {
                      e.preventDefault()
                      setPick(l.id)
                    }
                  }}
                  className="cursor-pointer border-b px-3 py-2.5 outline-none last:border-b-0 hover:bg-hover focus-visible:bg-hover"
                >
                  <span className="flex items-center justify-between gap-2">
                    <b className="text-sm">{l.label}</b>
                    <span className="text-xs text-muted-foreground">{l.id === 'all' ? 'Starts at 10 for every list' : own ? 'Set on its own' : chosen.all !== null ? 'Same as all lists' : 'Its own'}</span>
                  </span>
                  <GlideChips
                    label={`${l.label} rows per page`}
                    variant="segmented"
                    className="mt-2 w-fit"
                    value={String(sizeOf(l.id))}
                    onChange={(v) => {
                      setPick(l.id)
                      if (l.id === 'all') setAllPageSize(Number(v))
                      else setSectionPageSize(l.id, Number(v))
                    }}
                    options={SIZE_CHOICES.map((n) => ({ value: String(n), label: String(n) }))}
                  />
                </div>
              )
            })}
          </div>
          <p className="mt-2 text-[13px] text-muted-foreground">
            Pick a page to preview it.{' '}
            <Button size="sm" variant="outline" className="ml-1 h-7" disabled={isReset} onClick={() => setAllPageSize(null)}>
              Reset all to 10
            </Button>
          </p>
        </div>
        <PagePreview info={info} size={sizeOf(pick)} density={density} />
      </div>
    </>
  )
}

function Keyboard() {
  return (
    <>
      <Heading>Keyboard</Heading>
      <p className="-mt-2 mb-4 text-[13px] text-muted-foreground">
        The keys for every screen, here to look through; the screen you are on is marked. Press a shortcut and its row lights up; on this page it does not run, so you can try them safely. Press ? anywhere else for the same guide.
      </p>
      <ShortcutGuide inline allScreens />
    </>
  )
}

export function PreferencesScreen() {
  usePageTitle('Preferences')
  const [topic, setTopic] = useState<Topic>('look')
  return (
    <div className="grid gap-4">
      <p className="text-[13px] text-muted-foreground">Kept in this browser. They change how you see the screen, not the firm’s books.</p>
      <div className="grid items-start gap-6 md:grid-cols-[180px_minmax(0,1fr)]">
        <nav aria-label="Preferences" className="flex gap-1 max-md:overflow-x-auto md:grid">
          {TOPICS.map((t) => (
            <button
              key={t.id}
              type="button"
              aria-current={topic === t.id ? 'true' : undefined}
              onClick={() => setTopic(t.id)}
              className={cn('rounded-lg px-3 py-2 text-left text-sm text-muted-foreground transition-colors duration-150 hover:bg-hover max-md:shrink-0', topic === t.id && 'font-semibold')}
            >
              {t.label}
            </button>
          ))}
        </nav>
        <div className="min-w-0">
          {topic === 'look' && <Look />}
          {topic === 'review' && <ReviewTopic />}
          {topic === 'lists' && <Lists />}
          {topic === 'keys' && <Keyboard />}
        </div>
      </div>
    </div>
  )
}
