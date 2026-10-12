import { act, renderHook } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { trackWrite, usePendingWrites } from './pending'

describe('pending writes', () => {
  it('counts a write while it runs and stops counting when it ends, even if it fails', async () => {
    const { result } = renderHook(() => usePendingWrites())
    expect(result.current).toBe(0)
    let finish: () => void = () => {}
    let started: Promise<void> = Promise.resolve()
    act(() => {
      started = trackWrite(() => new Promise<void>((resolve) => (finish = resolve)))
    })
    expect(result.current).toBe(1)
    await act(async () => {
      finish()
      await started
    })
    expect(result.current).toBe(0)
    await act(async () => {
      await trackWrite(() => Promise.reject(new Error('refused'))).catch(() => undefined)
    })
    expect(result.current).toBe(0)
  })
})
