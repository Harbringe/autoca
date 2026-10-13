import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { createMemoryHistory, createRootRoute, createRoute, createRouter, RouterProvider } from '@tanstack/react-router'
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { clientDetail } from '@/api/queries/clients'
import { UploadProvider } from './UploadDialog'

const post = vi.fn()
const get = vi.fn()
vi.mock('@/api/client', () => ({ raw: { post: (...a: unknown[]) => post(...a), get: (...a: unknown[]) => get(...a) } }))
vi.mock('@/api/jobs', async (orig) => ({ ...(await orig<object>()), waitForJob: async (job: unknown) => job }))
vi.mock('@/session/session', () => ({ useSession: () => ({ can: () => true }) }))

const CLIENT = 'c1'
const okJob = (statement: string, rows = 10) => ({ id: `j-${statement}`, status: 'SUCCEEDED', progress: 100, message: '', error: '', error_code: '', result: { statement, bank_account: 'b1', is_new: true, rows_created: rows, rows_already_present: 0, needs_opening_confirmation: false, rows_posted: 0, rows_need_ledger: 2, rows_ready_to_post: rows - 2 } })
const failJob = (code: string) => ({ id: `j-${code}`, status: 'FAILED', progress: 0, message: '', error: 'x', error_code: code, result: null })

async function setup() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { staleTime: Infinity, retry: false } } })
  queryClient.setQueryData(clientDetail(CLIENT).queryKey, { id: CLIENT, name: 'Laxmi' } as never)
  const root = createRootRoute()
  const page = createRoute({ getParentRoute: () => root, path: '/', component: () => <UploadProvider clientId={CLIENT}>{null}</UploadProvider> })
  const review = createRoute({ getParentRoute: () => root, path: '/clients/$clientId/review', validateSearch: (s: Record<string, unknown>) => ({ statement: s.statement as string | undefined }), component: () => <p>review</p> })
  const router = createRouter({ routeTree: root.addChildren([page, review]), history: createMemoryHistory({ initialEntries: ['/'] }) })
  render(
    <QueryClientProvider client={queryClient}>
      <RouterProvider router={router} />
    </QueryClientProvider>,
  )
  // The provider listens once the router has drawn the page, so ask until the dialog is there.
  await waitFor(() => {
    act(() => void document.dispatchEvent(new Event('autoca:upload')))
    expect(screen.getByRole('dialog')).toBeInTheDocument()
  })
  return router
}

const pdf = (name: string) => new File(['%PDF'], name, { type: 'application/pdf' })

beforeEach(() => {
  post.mockReset()
  get.mockReset()
  get.mockResolvedValue(null)
})

describe('uploading several statements at once', () => {
  it('reads each in turn, shows each file’s own result, and opens Review on exactly the statements read', async () => {
    post.mockImplementation(async (_url: string, form: FormData) => (String((form.get('file') as File).name).startsWith('a') ? okJob('s1', 10) : okJob('s2', 6)))
    const router = await setup()
    const input = await screen.findByLabelText('Choose statements')
    fireEvent.change(input, { target: { files: [pdf('b.pdf'), pdf('a.pdf')] } })
    expect(await screen.findByText('2 statements chosen')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /Upload and read 2 statements/ }))
    await screen.findByText(/of 2 read, 16 rows in all/)
    // a.pdf is read first (name order), b.pdf second
    expect(post.mock.calls.map((c) => (c[1] as FormData).get('file')).map((f) => (f as File).name)).toEqual(['a.pdf', 'b.pdf'])
    const list = screen.getByRole('list')
    expect(within(list).getByText('a.pdf')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /Review 16 rows/ }))
    await waitFor(() => expect(router.state.location.pathname).toBe('/clients/c1/review'))
    expect(router.state.location.search).toMatchObject({ statement: 's1,s2' })
  })

  it('carries on past a file that fails, says so on its line, and offers to open it on its own', async () => {
    post.mockImplementation(async (_url: string, form: FormData) => ((form.get('file') as File).name === 'a.pdf' ? failJob('balance_chain_broken') : okJob('s2', 6)))
    await setup()
    fireEvent.change(await screen.findByLabelText('Choose statements'), { target: { files: [pdf('a.pdf'), pdf('b.pdf')] } })
    fireEvent.click(await screen.findByRole('button', { name: /Upload and read 2 statements/ }))
    await screen.findByText(/of 2 read, 16 rows in all|of 2 read, 6 rows in all/)
    expect(screen.getByText(/The running balance does not add up/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Open on its own' })).toBeInTheDocument()
  })

  it('tries a statement again after the others when it was refused for a gap', async () => {
    let a = 0
    post.mockImplementation(async (_url: string, form: FormData) => {
      const name = (form.get('file') as File).name
      if (name === 'a.pdf') return ++a === 1 ? failJob('statement_period_missing') : okJob('s1', 5)
      return okJob('s2', 6)
    })
    await setup()
    fireEvent.change(await screen.findByLabelText('Choose statements'), { target: { files: [pdf('a.pdf'), pdf('b.pdf')] } })
    fireEvent.click(await screen.findByRole('button', { name: /Upload and read 2 statements/ }))
    await screen.findByText(/of 2 read, 11 rows in all/)
    expect(post).toHaveBeenCalledTimes(3)
  })

  it('leaves out a file that cannot be read and says so, and one file is still the ordinary upload', async () => {
    await setup()
    const input = await screen.findByLabelText('Choose statements')
    fireEvent.change(input, { target: { files: [pdf('a.pdf'), new File(['x'], 'notes.exe')] } })
    expect(await screen.findByText(/1 file was left out/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Upload and read' })).toBeEnabled()
    expect(screen.queryByText(/statements chosen/)).toBeNull()
  })
})
