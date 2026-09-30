// The table every list in the product is built on.
//
// Real <table> markup (th scope, an sr-only caption, aria-sort), 12px sentence-case headers,
// numbers right-aligned and tabular, one line per row, and a row height that follows the density
// preference (--row-h). Columns carry a priority so a narrow screen drops the least important
// first, and a wide table becomes a labelled scroll region rather than squeezing.

import { ArrowDown, ArrowUp, ChevronsUpDown } from 'lucide-react'
import { useMemo, useState, type KeyboardEvent, type ReactNode } from 'react'
import { cn } from '@/lib/utils'

export interface Column<T> {
  key: string
  header: ReactNode
  /** Plain text for the header when `header` is not text (the sort button and the skeleton use it). */
  label?: string
  cell: (row: T) => ReactNode
  align?: 'left' | 'right'
  /** 1 = never hidden, 2 = hidden under 640px, 3 = hidden under 1024px. Default 1. */
  priority?: 1 | 2 | 3
  /** Give a column a sort key and it becomes sortable. */
  sortValue?: (row: T) => string | number
  className?: string
  /** A CSS width, e.g. '9rem'. */
  width?: string
}

const PRIORITY_HIDE: Record<number, string> = { 1: '', 2: 'max-sm:hidden', 3: 'max-lg:hidden' }

export function DataTable<T>({
  caption,
  columns,
  rows,
  rowKey,
  footer,
  loading,
  empty,
  onRowClick,
  rowClassName,
  selectedKey,
  defaultSort,
  scrollHeight,
  className,
}: {
  /** Names the table for screen readers; not shown. */
  caption: string
  columns: Column<T>[]
  rows: T[] | undefined
  rowKey: (row: T) => string
  /** A totals row, rendered in <tfoot>: 600 weight, 2px top rule. Pass the cells for each column. */
  footer?: ReactNode
  loading?: boolean
  /** Shown instead of the table when there are no rows. */
  empty?: ReactNode
  onRowClick?: (row: T) => void
  rowClassName?: (row: T) => string | undefined
  selectedKey?: string
  defaultSort?: { key: string; dir: 'asc' | 'desc' }
  /** Make the table its own scroll box with a sticky header, e.g. '70vh'. Off: the page scrolls. */
  scrollHeight?: string
  className?: string
}) {
  const [sort, setSort] = useState(defaultSort)
  const sorted = useMemo(() => {
    if (!rows || !sort) return rows
    const col = columns.find((c) => c.key === sort.key)
    if (!col?.sortValue) return rows
    const get = col.sortValue
    const dir = sort.dir === 'asc' ? 1 : -1
    return [...rows].sort((a, b) => {
      const [x, y] = [get(a), get(b)]
      return (typeof x === 'number' && typeof y === 'number' ? x - y : String(x).localeCompare(String(y), 'en', { numeric: true })) * dir
    })
  }, [rows, sort, columns])

  if (!loading && rows && rows.length === 0 && empty) return <>{empty}</>

  const toggle = (key: string) =>
    setSort((prev) => (prev?.key === key ? { key, dir: prev.dir === 'asc' ? 'desc' : 'asc' } : { key, dir: 'asc' }))

  return (
    <div
      role="region"
      aria-label={caption}
      aria-busy={loading || undefined}
      tabIndex={0}
      className={cn('relative overflow-auto rounded-lg border bg-card', className)}
      style={scrollHeight ? { maxHeight: scrollHeight } : undefined}
    >
      <table className="w-full text-left text-sm">
        <caption className="sr-only">{loading ? `Loading ${caption}` : caption}</caption>
        <thead className="border-b bg-surface-2 text-xs text-muted-foreground">
          <tr>
            {columns.map((col) => {
              const active = sort?.key === col.key
              return (
                <th
                  key={col.key}
                  scope="col"
                  aria-sort={active ? (sort.dir === 'asc' ? 'ascending' : 'descending') : col.sortValue ? 'none' : undefined}
                  style={col.width ? { width: col.width } : undefined}
                  className={cn(
                    'whitespace-nowrap px-3 py-2 text-xs font-semibold',
                    scrollHeight && 'sticky top-0 z-10 bg-surface-2',
                    col.align === 'right' ? 'text-right' : 'text-left',
                    PRIORITY_HIDE[col.priority ?? 1],
                  )}
                >
                  {col.sortValue ? (
                    <button
                      type="button"
                      onClick={() => toggle(col.key)}
                      className={cn('inline-flex items-center gap-1 rounded-sm hover:text-foreground', col.align === 'right' && 'flex-row-reverse')}
                    >
                      {col.header}
                      {active ? (
                        sort.dir === 'asc' ? <ArrowUp className="size-3" aria-hidden /> : <ArrowDown className="size-3" aria-hidden />
                      ) : (
                        <ChevronsUpDown className="size-3 opacity-60" aria-hidden />
                      )}
                    </button>
                  ) : (
                    col.header
                  )}
                </th>
              )
            })}
          </tr>
        </thead>
        <tbody>
          {loading
            ? Array.from({ length: 5 }, (_, i) => (
                <tr key={i} className="h-(--row-h) border-b last:border-b-0" aria-hidden>
                  {columns.map((col) => (
                    <td key={col.key} className={cn('px-3 py-1', PRIORITY_HIDE[col.priority ?? 1])}>
                      <div className={cn('skeleton h-3', col.align === 'right' ? 'ml-auto w-16' : 'w-3/4')} />
                    </td>
                  ))}
                </tr>
              ))
            : (sorted ?? []).map((row) => {
                const key = rowKey(row)
                const onKey = onRowClick
                  ? (e: KeyboardEvent) => {
                      if (e.target === e.currentTarget && (e.key === 'Enter' || e.key === ' ')) {
                        e.preventDefault()
                        onRowClick(row)
                      }
                    }
                  : undefined
                return (
                  <tr
                    key={key}
                    onClick={onRowClick ? () => onRowClick(row) : undefined}
                    onKeyDown={onKey}
                    tabIndex={onRowClick ? 0 : undefined}
                    aria-selected={selectedKey !== undefined ? key === selectedKey : undefined}
                    className={cn(
                      'h-(--row-h) border-b last:border-b-0',
                      onRowClick && 'cursor-pointer hover:bg-hover focus-visible:outline-offset-[-2px]',
                      selectedKey === key && 'bg-accent',
                      rowClassName?.(row),
                    )}
                  >
                    {columns.map((col) => (
                      <td
                        key={col.key}
                        className={cn(
                          'whitespace-nowrap px-3 py-1',
                          col.align === 'right' ? 'num text-right' : 'text-left',
                          PRIORITY_HIDE[col.priority ?? 1],
                          col.className,
                        )}
                      >
                        {col.cell(row)}
                      </td>
                    ))}
                  </tr>
                )
              })}
        </tbody>
        {footer && <tfoot className="border-t-2 border-foreground bg-surface-2 font-semibold">{footer}</tfoot>}
      </table>
    </div>
  )
}
