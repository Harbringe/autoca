import { beforeEach, describe, expect, it, vi } from 'vitest'
import { allPages } from './books'

const get = vi.fn()
vi.mock('@/api/client', async (orig) => ({ ...(await orig<object>()), raw: { get: (...a: unknown[]) => get(...a) } }))

const rows = (from: number, n: number) => Array.from({ length: n }, (_, i) => from + i)

describe('reading every page of a list', () => {
  beforeEach(() => {
    get.mockReset()
  })

  it('returns one page as it is', async () => {
    get.mockResolvedValueOnce({ count: 3, next: null, previous: null, results: [1, 2, 3] })
    expect(await allPages('/x/')).toEqual([1, 2, 3])
    expect(get).toHaveBeenCalledTimes(1)
  })

  it('fetches the later pages together and keeps the rows in order', async () => {
    let running = 0
    let peak = 0
    get.mockImplementation(async (...args: unknown[]) => {
      const q = args[1] as { page: number }
      if (q.page === 1) return { count: 3000, next: 'n', previous: null, results: rows(0, 500) }
      running += 1
      peak = Math.max(peak, running)
      await new Promise((r) => setTimeout(r, q.page === 2 ? 15 : 1))
      running -= 1
      return { count: 3000, next: q.page < 6 ? 'n' : null, previous: 'p', results: rows((q.page - 1) * 500, 500) }
    })
    const all = await allPages<number>('/x/')
    expect(all).toEqual(rows(0, 3000))
    expect(peak).toBeGreaterThan(1)
    expect(peak).toBeLessThanOrEqual(4)
  })
})
