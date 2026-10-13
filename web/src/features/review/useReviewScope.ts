// The statements chosen for review and the numbers that follow from the choice, read once for every part of the screen that shows a count
// (the tabs, the buttons, the headline), so they always agree. The two queues are the same ones the Review list reads, so nothing extra is fetched.

import { useQuery } from '@tanstack/react-query'
import { useMemo } from 'react'
import { reviewQueue } from '@/api/queries/books'
import { statements as statementsQuery } from '@/api/queries/clients'
import { useSession } from '@/session/session'
import { resolveSelection, scopedCounts, waitingStatements, type ScopedCounts, type StatementChoice } from './statementChoices'

export interface ReviewScope {
  /** The ids chosen, or null for all of the client's statements. */
  selection: string[] | null
  /** Statements with anything waiting, oldest first. */
  waiting: StatementChoice[]
  /** The counts for the chosen statements, or null when all are chosen (the client's totals apply). */
  counts: ScopedCounts | null
  loaded: boolean
}

export function useReviewScope(clientId: string, asked: string | undefined, enabled = true): ReviewScope {
  const { can } = useSession()
  const on = enabled && can('transaction.view')
  const needs = useQuery({ ...reviewQueue(clientId, 'unresolved'), enabled: on })
  const ready = useQuery({ ...reviewQueue(clientId, 'pending_approval'), enabled: on })
  const stmts = useQuery({ ...statementsQuery(clientId), enabled: on })
  return useMemo(() => {
    const loaded = !!needs.data && !!ready.data && !!stmts.data
    if (!loaded) return { selection: null, waiting: [], counts: null, loaded }
    const list = stmts.data!.results
    const waiting = waitingStatements(list, needs.data!, ready.data!)
    const selection = resolveSelection(asked, waiting, list)
    return { selection, waiting, counts: scopedCounts(selection, needs.data!, ready.data!, list), loaded }
  }, [asked, needs.data, ready.data, stmts.data])
}
