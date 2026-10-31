// Check the move against Tally: the accountant exports Tally's trial balance for the same company and year, and every ledger whose
// closing balance differs from the posted books is listed with both figures. Differences are shown, never fixed.

import { useRef, useState } from 'react'
import { CheckCircle2, FileUp } from 'lucide-react'
import { useTrialBalanceCheck } from '@/api/queries/tallyImport'
import { Money } from '@/components/ca/Money'
import { Button } from '@/components/ui/button'
import { Card } from '@/components/ui/card'
import { useFy } from '@/features/shell/useFy'
import { plural } from '@/lib/format'

type Answer = NonNullable<ReturnType<typeof useTrialBalanceCheck>['data']>

export function TrialBalanceCheck({ clientId }: { clientId: string }) {
  const { fy } = useFy()
  const check = useTrialBalanceCheck(clientId)
  const input = useRef<HTMLInputElement>(null)
  const [answer, setAnswer] = useState<Answer | null>(null)
  const [error, setError] = useState<string | null>(null)

  async function choose(file: File | undefined) {
    if (!file) return
    setError(null)
    setAnswer(null)
    try {
      setAnswer(await check.mutateAsync({ file, fy }))
    } catch (e) {
      setError(e instanceof Error && e.message ? e.message : 'Something went wrong. Try again.')
    }
  }

  return (
    <Card className="grid gap-3 p-4">
      <h2 className="font-medium">Check against Tally</h2>
      <p className="text-sm text-muted-foreground">
        Export the trial balance from Tally for the same company and year, as XML or JSON. Every ledger whose closing balance differs from
        these books is listed. Nothing is changed.
      </p>
      <div>
        <input
          ref={input}
          type="file"
          accept=".xml,.json,text/xml,application/json"
          aria-label="Trial balance file"
          className="sr-only"
          onChange={(e) => {
            void choose(e.target.files?.[0])
            e.target.value = ''
          }}
        />
        <Button variant="outline" loading={check.isPending} onClick={() => input.current?.click()}>
          <FileUp aria-hidden /> Choose Tally's trial balance
        </Button>
      </div>
      {error && (
        <Card tone="danger" role="alert" className="p-3 text-sm">
          {error}
        </Card>
      )}
      {answer && (
        <div className="grid gap-2 text-sm">
          <p data-testid="tb-matched">{plural(answer.matched, 'ledger')} agree.</p>
          {answer.differences.length === 0 ? (
            <p className="flex items-center gap-2 font-medium">
              <CheckCircle2 className="size-4" aria-hidden /> Everything matches.
            </p>
          ) : (
            <table className="w-full text-left">
              <caption className="sr-only">Ledgers whose closing balance differs from Tally</caption>
              <thead>
                <tr className="text-muted-foreground">
                  <th scope="col">Ledger</th>
                  <th scope="col" className="text-right">Tally</th>
                  <th scope="col" className="text-right">Here</th>
                </tr>
              </thead>
              <tbody>
                {answer.differences.map((d) => (
                  <tr key={d.name}>
                    <td>{d.name}</td>
                    <td className="num text-right"><Money paise={d.tally_paise} /></td>
                    <td className="num text-right"><Money paise={d.ours_paise} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}
    </Card>
  )
}
