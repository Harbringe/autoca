// What a client's profile page shows and how an edit becomes a request. Pure, so it is tested.

import type { ClientProfile, ProfilePatch } from '@/api/queries/clients'
import { formatDate, parseDate } from '@/lib/format'

export const CONSTITUTIONS: [string, string][] = [
  ['INDIVIDUAL', 'Individual or sole proprietor'],
  ['PARTNERSHIP', 'Partnership firm'],
  ['LLP', 'Limited liability partnership'],
  ['PRIVATE_LIMITED', 'Private limited company'],
  ['PUBLIC_LIMITED', 'Public limited company'],
  ['HUF', 'Hindu undivided family'],
  ['TRUST', 'Trust or society'],
  ['AOP', 'Association of persons'],
  ['OTHER', 'Other'],
]

export const MSME_CATEGORIES: [string, string][] = [
  ['MICRO', 'Micro'],
  ['SMALL', 'Small'],
  ['MEDIUM', 'Medium'],
]

export type EditableKey = keyof ProfilePatch & string

export interface FieldDef {
  key: EditableKey
  label: string
  kind: 'text' | 'email' | 'tel' | 'date' | 'select' | 'area' | 'id'
  options?: [string, string][]
  hint?: string
  /** Takes the whole row in a two-column grid. */
  wide?: boolean
  maxLength?: number
}

export const labelOf = (options: [string, string][], value: string | undefined): string => options.find(([v]) => v === value)?.[1] ?? ''

/** A profile value as the edit field shows it: dates as DD-MM-YYYY, empty as an empty string. */
export function draftOf(profile: ClientProfile, fields: FieldDef[]): Record<string, string> {
  const draft: Record<string, string> = {}
  for (const f of fields) {
    const value = (profile as unknown as Record<string, string | null | undefined>)[f.key] ?? ''
    draft[f.key] = f.kind === 'date' && value ? formatDate(value) : value
  }
  return draft
}

/** The request for what the person changed: only changed fields, dates as ISO, an emptied date as null. A bad date comes back as `problem`. */
export function patchOf(profile: ClientProfile, fields: FieldDef[], draft: Record<string, string>): { patch: ProfilePatch; problem?: string } {
  const before = draftOf(profile, fields)
  const patch: Record<string, string | null> = {}
  for (const f of fields) {
    const now = (draft[f.key] ?? '').trim()
    if (now === before[f.key]) continue
    if (f.kind === 'date') {
      if (now === '') patch[f.key] = null
      else {
        const iso = parseDate(now)
        if (!iso) return { patch: {}, problem: `${f.label}: enter the date as DD-MM-YYYY.` }
        patch[f.key] = iso
      }
    } else {
      patch[f.key] = f.kind === 'id' ? now.toUpperCase() : now
    }
  }
  return { patch: patch as ProfilePatch }
}
