import { QueryClient, QueryClientProvider, useMutation } from '@tanstack/react-query'
import { act, render, waitFor } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { INVOICE_UPLOAD_KEY } from '@/api/queries/bills'
import { Ribbon } from './Shell'

function Upload({ release }: { release: Promise<void> }) {
  const m = useMutation({ mutationKey: INVOICE_UPLOAD_KEY, mutationFn: () => release })
  return <button onClick={() => m.mutate()}>go</button>
}

describe('the line along the top of the bar', () => {
  it('sweeps while an invoice is being read, and stops when it is done', async () => {
    let done!: () => void
    const release = new Promise<void>((resolve) => (done = resolve))
    const { container, getByText } = render(
      <QueryClientProvider client={new QueryClient()}>
        <Ribbon clientId="c1" />
        <Upload release={release} />
      </QueryClientProvider>,
    )
    expect(container.querySelector('.ribbon-sweep')).toBeNull()
    act(() => getByText('go').click())
    await waitFor(() => expect(container.querySelector('.ribbon-sweep')).not.toBeNull())
    act(() => done())
    await waitFor(() => expect(container.querySelector('.ribbon-sweep')).toBeNull())
  })
})
