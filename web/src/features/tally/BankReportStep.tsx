// Bank history from Tally's bank ledger reports: choose one report per bank account, say which account each is for, and preview. The preview and
// the posting are the same as for a vouchers export. A transfer between two of the client's own accounts is in both reports; choosing both
// together writes it once.

import { useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { FileUp } from 'lucide-react'
import { bankAccounts } from '@/api/queries/clients'
import { useStageBankReports, type VoucherRun } from '@/api/queries/tallyImport'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { Select } from '@/components/ui/controls'

const messageOf = (error: unknown) => (error instanceof Error && error.message ? error.message : 'Something went wrong. Try again.')

export function BankReportStep({ clientId, onStaged, onError }: { clientId: string; onStaged: (run: VoucherRun) => void; onError: (message: string) => void }) {
  const accounts = useQuery(bankAccounts(clientId))
  const stage = useStageBankReports(clientId)
  const input = useRef<HTMLInputElement>(null)
  const [files, setFiles] = useState<File[]>([])
  const [chosen, setChosen] = useState<Record<string, string>>({})
  const list = accounts.data?.results ?? []

  const ready = files.length > 0 && files.every((f) => chosen[f.name]) && new Set(files.map((f) => chosen[f.name])).size === files.length

  async function preview() {
    try {
      onStaged(await stage.mutateAsync({ reports: files.map((file) => ({ file, account: chosen[file.name]! })) }))
    } catch (e) {
      onError(messageOf(e))
    }
  }

  return (
    <Card className="grid gap-3 p-4">
      <h2 className="font-medium">3. Bank reports</h2>
      <p className="text-sm text-muted-foreground">
        Tally's report of a bank ledger's vouchers, exported as XML. Choose the report of each bank account together, and say which account each is for. Add the bank
        accounts first (the set-up step above does it). A row where Tally lists several ledgers is left out and says so. Use this or the vouchers file for the same bank
        entries, not both.
      </p>
      <div>
        <input
          ref={input}
          type="file"
          multiple
          accept=".xml,text/xml"
          aria-label="Bank reports"
          className="sr-only"
          onChange={(e) => {
            setFiles(Array.from(e.target.files ?? []))
            setChosen({})
            e.target.value = ''
          }}
        />
        <Button variant="outline" onClick={() => input.current?.click()}>
          <FileUp aria-hidden /> Choose the bank reports
        </Button>
      </div>
      {files.map((f) => (
        <div key={f.name} className="flex flex-wrap items-center gap-2 text-sm">
          <span className="font-medium">{f.name}</span>
          <Select aria-label={`Bank account for ${f.name}`} className="w-72" value={chosen[f.name] ?? ''} onChange={(e) => setChosen((cur) => ({ ...cur, [f.name]: e.target.value }))}>
            <option value="">Which account…</option>
            {list.map((a) => (
              <option key={a.id} value={a.id}>
                {a.ledger_name}
              </option>
            ))}
          </Select>
        </div>
      ))}
      {files.length > 0 && (
        <div>
          <Button loading={stage.isPending} disabled={!ready} onClick={() => void preview()}>
            Preview the bank entries
          </Button>
          {!ready && <span className="ml-3 text-sm text-muted-foreground">Choose a different account for each report.</span>}
        </div>
      )}
    </Card>
  )
}
