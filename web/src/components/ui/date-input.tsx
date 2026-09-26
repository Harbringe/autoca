import type { ComponentProps } from 'react'
import { Input } from './input'

/**
 * A date field that reads and writes DD-MM-YYYY. The browser's own date control follows the
 * device's locale, which for many Indian machines is month-first: "04/01/2026" then reads as
 * 4 January when the app means 1 April. A text field removes the ambiguity.
 */
export function DateInput(props: Omit<ComponentProps<typeof Input>, 'type'>) {
  return <Input inputMode="numeric" placeholder="DD-MM-YYYY" autoComplete="off" maxLength={10} {...props} />
}
