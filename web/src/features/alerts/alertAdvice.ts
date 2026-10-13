// What a person does about each kind of alert: one line of plain guidance, and the name of the screen it opens. Pure, so it can be tested.

import type { Alert } from '@/api/types'
import { clientScreenName } from '@/lib/clientNav'

/** One line on what to do. The kinds are the server's; the few that stand for two different jobs are told apart by their screen or title. */
export function adviceFor(alert: Alert): string {
  switch (alert.kind) {
    case 'review':
      return alert.search?.stage === 'pending_approval' ? 'Tick the rows you agree with and post them.' : 'Place each in a ledger, or let the assistant suggest.'
    case 'statements':
      return 'Ask the client for the missing statements and upload them.'
    case 'unchecked':
      return 'Look at them in the Day Book and mark them as checked.'
    case 'review_pending':
      return 'Ask the senior CA to approve the books or send them back.'
    case 'bank':
      return 'Find the missing or doubled row, or explain the difference.'
    case 'control':
      return 'Do what the check names, then it clears by itself.'
    case 'seal':
      return /ready to seal/i.test(alert.title) ? 'Seal the books through that date.' : 'Finish the checklist, then ask the senior to approve and seal.'
    case 'approval':
      return 'Look at what changed after approval, then approve it again or put it back.'
    case 'tds':
      return 'Deposit the challan and record it, or note the late fee.'
    case 'tds_due':
      return 'Prepare the challan before the due date.'
    default:
      return 'Open it and follow what the screen shows.'
  }
}

/** The name of the screen the alert opens, for its button ("Open TDS"). */
export function actionLabel(alert: Alert): string {
  return `Open ${clientScreenName(alert.to) ?? 'it'}`
}
