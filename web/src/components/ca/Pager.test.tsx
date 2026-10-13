import { fireEvent, render, renderHook, screen, act } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { PAGE_SIZE, PagedList, Pager, pageNumbers, usePaged } from './Pager'

const items = (n: number) => Array.from({ length: n }, (_, i) => i + 1)

function Demo({ n, resetKey = 'a' }: { n: number; resetKey?: string }) {
  const paged = usePaged(items(n), resetKey)
  return (
    <>
      <ul>
        {paged.items.map((i) => (
          <li key={i}>row {i}</li>
        ))}
      </ul>
      <Pager paged={paged} label="Rows" />
    </>
  )
}

describe('the pager', () => {
  it('shows nothing extra for a list that fits on one page', () => {
    render(<Demo n={PAGE_SIZE} />)
    expect(screen.getAllByRole('listitem')).toHaveLength(PAGE_SIZE)
    expect(screen.queryByRole('navigation')).toBeNull()
  })

  it('shows one page of a long list and says where it is', () => {
    render(<Demo n={120} />)
    expect(screen.getAllByRole('listitem')).toHaveLength(PAGE_SIZE)
    expect(screen.getByText('row 1')).toBeInTheDocument()
    expect(screen.getByText('Showing 1–50 of 120')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Previous' })).toBeDisabled()
  })

  it('turns pages, and the last one is short', () => {
    render(<Demo n={120} />)
    fireEvent.click(screen.getByRole('button', { name: 'Next' }))
    expect(screen.getByText('Showing 51–100 of 120')).toBeInTheDocument()
    expect(screen.getByText('row 51')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Page 3' }))
    expect(screen.getAllByRole('listitem')).toHaveLength(20)
    expect(screen.getByText('Showing 101–120 of 120')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Next' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Page 3' })).toHaveAttribute('aria-current', 'page')
  })

  it('goes back to the first page when what the list is of changes', () => {
    const { rerender } = render(<Demo n={120} resetKey="a" />)
    fireEvent.click(screen.getByRole('button', { name: 'Next' }))
    expect(screen.getByText('Showing 51–100 of 120')).toBeInTheDocument()
    rerender(<Demo n={120} resetKey="b" />)
    expect(screen.getByText('Showing 1–50 of 120')).toBeInTheDocument()
  })

  it('moves back to the last page when rows leave and the page is gone', () => {
    const { rerender } = render(<Demo n={120} />)
    fireEvent.click(screen.getByRole('button', { name: 'Page 3' }))
    rerender(<Demo n={95} />)
    expect(screen.getByText('Showing 51–95 of 95')).toBeInTheDocument()
  })
})

describe('usePaged', () => {
  it('turns to the page that holds a given row', () => {
    const { result } = renderHook(() => usePaged(items(200), 'k'))
    act(() => result.current.reveal(120))
    expect(result.current.page).toBe(3)
    expect(result.current.items[0]).toBe(101)
    act(() => result.current.reveal(0))
    expect(result.current.page).toBe(1)
  })

  it('has no rows and no pager for an empty list', () => {
    const { result } = renderHook(() => usePaged([], 'k'))
    expect(result.current).toMatchObject({ items: [], from: 0, to: 0, total: 0, paged: false, pages: 1 })
  })
})

describe('pageNumbers', () => {
  it('lists the first, the last and the neighbours, with a gap marked', () => {
    expect(pageNumbers(1, 3)).toEqual([1, 2, 3])
    expect(pageNumbers(1, 11)).toEqual([1, 2, '…', 11])
    expect(pageNumbers(6, 11)).toEqual([1, '…', 5, 6, 7, '…', 11])
    expect(pageNumbers(11, 11)).toEqual([1, '…', 10, 11])
  })
})

describe('PagedList', () => {
  it('pages a list for a component that cannot hold a hook', () => {
    render(
      <PagedList rows={items(75)} resetKey="k" label="Entries">
        {(shown) => <p>{shown.length} shown</p>}
      </PagedList>,
    )
    expect(screen.getByText('50 shown')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Next' }))
    expect(screen.getByText('25 shown')).toBeInTheDocument()
  })
})
