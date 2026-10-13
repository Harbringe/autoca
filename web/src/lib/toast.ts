// Notifications: the short messages that confirm or warn after something a person did.
//
// Successes and plain information disappear on their own. Warnings and errors stay until they are closed,
// because a missed message is a problem in accounts. The store is free of React so it can be tested; the
// stack that shows it is components/ca/Notifications.tsx. The call sites use `toast.success(...)`,
// `toast.error(...)` and so on, as they always did.

import { useSyncExternalStore } from 'react'

export type NoteKind = 'success' | 'warning' | 'error' | 'info'

export interface Note {
  id: number
  kind: NoteKind
  title: string
  description?: string
  /** Warnings and errors wait to be closed; the rest go after a few seconds. */
  sticky: boolean
}

interface Options {
  description?: string
}

/** How long a success or information message stays. */
export const AUTO_CLOSE_MS = 6000
/** More than this and the oldest fall off, so a failing loop cannot fill the page. */
const KEEP = 30

let notes: Note[] = []
let nextId = 1
const listeners = new Set<() => void>()

function emit(next: Note[]) {
  notes = next
  listeners.forEach((l) => l())
}

function push(kind: NoteKind, title: string, options?: Options): number {
  // The same message again replaces the one showing, so repeating a failed action does not stack copies.
  const same = notes.find((n) => n.kind === kind && n.title === title && n.description === options?.description)
  const note: Note = { id: nextId++, kind, title, description: options?.description, sticky: kind === 'warning' || kind === 'error' }
  emit([note, ...notes.filter((n) => n !== same)].slice(0, KEEP))
  return note.id
}

function dismiss(id?: number) {
  emit(id === undefined ? [] : notes.filter((n) => n.id !== id))
}

export const toast = {
  success: (title: string, options?: Options) => push('success', title, options),
  info: (title: string, options?: Options) => push('info', title, options),
  /** A plain message, shown as information. */
  message: (title: string, options?: Options) => push('info', title, options),
  warning: (title: string, options?: Options) => push('warning', title, options),
  error: (title: string, options?: Options) => push('error', title, options),
  /** Close one message, or every message when no id is given. */
  dismiss,
}

const subscribe = (listener: () => void) => {
  listeners.add(listener)
  return () => void listeners.delete(listener)
}

/** The messages showing now, newest first. */
export function useNotes(): Note[] {
  return useSyncExternalStore(subscribe, () => notes, () => notes)
}
