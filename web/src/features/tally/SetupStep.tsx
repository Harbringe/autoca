// Start from the Tally files themselves: choose the voucher exports and bank reports, and see the ledgers and bank accounts they imply, each
// with the group the files suggest and why. Change anything that is wrong, untick what you do not want, then create them. Nothing is created
// until you press the button, and a ledger the client already has is never touched.

import { useRef, useState } from 'react'
import { CheckCircle2, FileUp } from 'lucide-react'
import { useDiscover, useSetup, type AccountProposal, type Discovery } from '@/api/queries/tallyImport'
import { LEDGER_GROUPS } from '@/api/types'
import { PagedList } from '@/components/ca/Pager'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Checkbox, Select } from '@/components/ui/controls'
import { plural } from '@/lib/format'
import { toast } from '@/lib/toast'

const messageOf = (error: unknown) => (error instanceof Error && error.message ? error.message : 'Something went wrong. Try again.')

const inputClass = 'h-9 rounded-md border border-input bg-card px-2 text-sm'

export function SetupStep({ clientId }: { clientId: string }) {
  const discover = useDiscover(clientId)
  const setup = useSetup(clientId)
  const input = useRef<HTMLInputElement>(null)
  const [files, setFiles] = useState<File[]>([])
  const [found, setFound] = useState<Discovery | null>(null)
  const [groups, setGroups] = useState<Record<string, string>>({})
  const [skipped, setSkipped] = useState<Set<string>>(new Set())
  const [accounts, setAccounts] = useState<Record<string, AccountProposal>>({})
  const [named, setNamed] = useState<Record<string, string>>({})
  const [done, setDone] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  async function read(chosen: File[], bankLedgers: Record<string, string>) {
    setError(null)
    setDone(null)
    try {
      const result = await discover.mutateAsync({ files: chosen, bankLedgers })
      setFound(result)
      setGroups(Object.fromEntries(result.ledgers.map((p) => [p.name, p.group])))
      setSkipped(new Set())
      setAccounts(Object.fromEntries(result.accounts.map((a) => [a.ledger, a])))
    } catch (e) {
      setFound(null)
      setError(messageOf(e))
    }
  }

  async function choose(list: FileList | null) {
    const chosen = Array.from(list ?? [])
    if (!chosen.length) return
    setFiles(chosen)
    setNamed({})
    await read(chosen, {})
  }

  const chosenLedgers = found?.ledgers.filter((p) => !skipped.has(p.name)) ?? []
  const chosenAccounts = Object.values(accounts).filter((a) => !skipped.has(a.ledger))
  const unnamed = found?.reports.filter((r) => !r.ledger) ?? []

  async function create() {
    setError(null)
    try {
      const result = await setup.mutateAsync({
        ledgers: chosenLedgers.map((p) => ({ name: p.name, group: groups[p.name] ?? p.group })),
        accounts: chosenAccounts,
      })
      const waiting = result.waiting_for_a_number.length
      setDone(
        `${plural(result.ledgers, 'ledger')} created, ${plural(result.accounts, 'bank account')} opened.` +
          (waiting ? ` ${plural(waiting, 'account')} still need${waiting === 1 ? 's' : ''} a number: type it and press the button again.` : ' Now import the vouchers below.'),
      )
      toast.success(`${plural(result.ledgers, 'ledger')} created`)
      if (!waiting) setFound(null)
    } catch (e) {
      setError(messageOf(e))
    }
  }

  return (
    <Card className="grid gap-3 p-4">
      <h2 className="font-medium">Set up from your Tally files</h2>
      <p className="text-sm text-muted-foreground">
        The quickest way to start a new client. Choose the voucher exports and the bank reports together, and the ledgers, bank accounts and their groups are worked
        out from them. You check the list before anything is created.
      </p>
      <div>
        <input
          ref={input}
          type="file"
          multiple
          accept=".xml,text/xml"
          aria-label="Tally files"
          className="sr-only"
          onChange={(e) => {
            void choose(e.target.files)
            e.target.value = ''
          }}
        />
        <Button variant="outline" loading={discover.isPending} onClick={() => input.current?.click()}>
          <FileUp aria-hidden /> Choose the Tally files
        </Button>
      </div>

      {error && (
        <Card tone="danger" role="alert" className="p-3 text-sm">
          {error}
        </Card>
      )}

      {found && (
        <div className="grid gap-3">
          <p className="text-sm" data-testid="discovery">
            {plural(found.vouchers, 'voucher')} in {plural(found.voucher_files, 'file')} and {plural(found.reports.length, 'bank report')}. {found.ledgers.length} ledgers
            and {found.accounts.length} bank accounts are not in this client yet.
          </p>

          {unnamed.map((r) => (
            <div key={r.file} className="flex flex-wrap items-end gap-2 text-sm">
              <label className="grid gap-1">
                Which bank ledger is {r.file} the report of?
                <input
                  className={`${inputClass} w-80`}
                  aria-label={`Bank ledger of ${r.file}`}
                  value={named[r.file] ?? ''}
                  onChange={(e) => setNamed((cur) => ({ ...cur, [r.file]: e.target.value }))}
                  placeholder="The ledger's name in Tally"
                />
              </label>
              <Button variant="outline" disabled={!(named[r.file] ?? '').trim()} onClick={() => void read(files, named)}>
                Read again
              </Button>
            </div>
          ))}

          {found.accounts.length > 0 && (
            <div className="grid gap-2">
              <h3 className="text-sm font-medium">Bank accounts</h3>
              {found.accounts.map((a) => {
                const mine = accounts[a.ledger] ?? a
                return (
                  <div key={a.ledger} className="flex flex-wrap items-center gap-2 text-sm">
                    <Checkbox
                      label={a.ledger}
                      checked={!skipped.has(a.ledger)}
                      onChange={(e) =>
                        setSkipped((cur) => {
                          const next = new Set(cur)
                          if (e.target.checked) next.delete(a.ledger)
                          else next.add(a.ledger)
                          return next
                        })
                      }
                    />
                    <span className="text-muted-foreground">{a.kind === 'LOAN' ? 'loan / cash credit' : 'bank'}</span>
                    <input
                      className={`${inputClass} w-24`}
                      aria-label={`Bank code for ${a.ledger}`}
                      value={mine.bank_code}
                      onChange={(e) => setAccounts((cur) => ({ ...cur, [a.ledger]: { ...mine, bank_code: e.target.value } }))}
                    />
                    <input
                      className={`${inputClass} w-44`}
                      aria-label={`Account number for ${a.ledger}`}
                      placeholder="Account number"
                      value={mine.account_number}
                      onChange={(e) => setAccounts((cur) => ({ ...cur, [a.ledger]: { ...mine, account_number: e.target.value } }))}
                    />
                  </div>
                )
              })}
            </div>
          )}

          {found.ledgers.length > 0 && (
            <div className="grid gap-1">
              <h3 className="text-sm font-medium">Ledgers</h3>
              <PagedList rows={found.ledgers} resetKey={`${found.ledgers.length}`} label="ledgers" section="proposals">
                {(items) => (
                  <ul className="grid gap-1 text-sm">
                    {items.map((p) => (
                      <li key={p.name} className="flex flex-wrap items-center gap-2 rounded border p-2">
                        <Checkbox
                          label={p.name}
                          checked={!skipped.has(p.name)}
                          onChange={(e) =>
                            setSkipped((cur) => {
                              const next = new Set(cur)
                              if (e.target.checked) next.delete(p.name)
                              else next.add(p.name)
                              return next
                            })
                          }
                        />
                        <Select
                          aria-label={`Group for ${p.name}`}
                          className="w-56"
                          value={groups[p.name] ?? p.group}
                          onChange={(e) => setGroups((cur) => ({ ...cur, [p.name]: e.target.value }))}
                        >
                          {LEDGER_GROUPS.map(([g, l]) => (
                            <option key={g} value={g}>
                              {l}
                            </option>
                          ))}
                        </Select>
                        <span className={p.unsure ? 'text-warning' : 'text-muted-foreground'}>
                          {p.unsure ? 'Check this one: ' : ''}
                          {p.reason}
                        </span>
                      </li>
                    ))}
                  </ul>
                )}
              </PagedList>
            </div>
          )}

          <div>
            <Button loading={setup.isPending} disabled={chosenLedgers.length + chosenAccounts.length === 0} onClick={() => void create()}>
              Create {plural(chosenLedgers.length, 'ledger')} and {plural(chosenAccounts.length, 'bank account')}
            </Button>
          </div>
        </div>
      )}

      {done && (
        <div className="flex items-center gap-2 text-sm font-medium">
          <CheckCircle2 className="size-4 text-success" aria-hidden /> {done}
        </div>
      )}
    </Card>
  )
}
