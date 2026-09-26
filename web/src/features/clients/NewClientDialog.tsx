import { zodResolver } from '@hookform/resolvers/zod'
import { useNavigate } from '@tanstack/react-router'
import { useState } from 'react'
import { useForm } from 'react-hook-form'
import { toast } from 'sonner'
import { z } from 'zod'
import { isApiError, messageOf } from '@/api/errors'
import { useCreateClient } from '@/api/queries/clients'
import { Button } from '@/components/ui/button'
import { DateInput } from '@/components/ui/date-input'
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Field } from '@/components/ui/field'
import { Input } from '@/components/ui/input'
import { financialYearOf, formatDate, parseDate } from '@/lib/format'

const schema = z.object({
  name: z.string().trim().min(2, 'Enter the client’s name (at least 2 characters).'),
  fy_start: z
    .string()
    .refine((v) => parseDate(v) !== null, 'Enter a date as DD-MM-YYYY, for example 01-04-2025.')
    .refine((v) => parseDate(v)?.endsWith('-01'), 'The financial year must start on the 1st of a month, normally 1 April.'),
  business_profile: z.string().max(2000, 'Keep this under 2,000 characters.'),
})
type Values = z.infer<typeof schema>

const defaults = (): Values => ({
  name: '',
  fy_start: formatDate(`${financialYearOf(new Date())}-04-01`),
  business_profile: '',
})

export function NewClientDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const navigate = useNavigate()
  const create = useCreateClient()
  const [confirmingDiscard, setConfirmingDiscard] = useState(false)
  const form = useForm<Values>({ resolver: zodResolver(schema), defaultValues: defaults() })
  const { register, handleSubmit, setError, reset, formState } = form
  // Read during render, so the form keeps tracking it. Read only inside an event handler, it is
  // not tracked until the second time the dialog opens, and the first close would lose the text.
  const { isDirty, isSubmitting } = formState

  function close() {
    setConfirmingDiscard(false)
    reset(defaults())
    onOpenChange(false)
  }

  // Esc, the close button and a click outside all come through here. Typed work is not thrown away silently.
  function requestClose(next: boolean) {
    if (next) return onOpenChange(true)
    // Esc or the close button while the prompt is showing means "no, keep editing".
    if (confirmingDiscard) return setConfirmingDiscard(false)
    if (isDirty && !isSubmitting) return setConfirmingDiscard(true)
    close()
  }

  async function submit(values: Values) {
    try {
      const client = await create.mutateAsync({
        name: values.name.trim(),
        fy_start: parseDate(values.fy_start)!,
        business_profile: values.business_profile,
      })
      toast.success(`${client.name} added`)
      close()
      await navigate({ to: '/clients/$clientId', params: { clientId: client.id } })
    } catch (error) {
      if (isApiError(error) && Object.keys(error.fields).length) {
        for (const [name, messages] of Object.entries(error.fields)) {
          setError(name as keyof Values, { message: messages[0] })
        }
      } else {
        setError('root', { message: messageOf(error) })
      }
    }
  }

  return (
    <Dialog open={open} onOpenChange={requestClose}>
      <DialogContent aria-describedby={undefined}>
        <DialogHeader>
          <DialogTitle>New client</DialogTitle>
          <DialogDescription>Each client has its own books, chart of accounts and financial year.</DialogDescription>
        </DialogHeader>
        <form onSubmit={handleSubmit(submit)} className="grid gap-4" noValidate>
          <fieldset disabled={confirmingDiscard} className="grid gap-4">
          <Field label="Client name" error={formState.errors.name?.message}>
            {(props) => <Input {...props} autoFocus autoComplete="off" {...register('name')} />}
          </Field>
          <Field
            label="Financial year starts"
            hint="Books are kept April to March, so this is normally 01-04-YYYY. It cannot be changed once entries are posted."
            error={formState.errors.fy_start?.message}
          >
            {(props) => <DateInput {...props} {...register('fy_start')} />}
          </Field>
          <Field
            label="What the business does (optional)"
            hint="Helps the assistant suggest the right ledgers."
            error={formState.errors.business_profile?.message}
          >
            {(props) => (
              <textarea
                {...props}
                rows={3}
                className="w-full rounded-md border border-input bg-card px-3 py-2 text-sm shadow-xs aria-invalid:border-destructive"
                {...register('business_profile')}
              />
            )}
          </Field>
          {formState.errors.root && (
            <p role="alert" className="text-sm text-destructive">
              {formState.errors.root.message}
            </p>
          )}
          </fieldset>
          {confirmingDiscard ? (
            <div role="alertdialog" aria-label="Discard what you typed?" className="flex items-center justify-between gap-3 rounded-md border border-warning/50 bg-warning/10 p-3 text-sm">
              <span>Discard what you have typed?</span>
              <span className="flex gap-2">
                <Button size="sm" variant="outline" autoFocus onClick={() => setConfirmingDiscard(false)}>
                  Keep editing
                </Button>
                <Button size="sm" variant="destructive" onClick={close}>
                  Discard
                </Button>
              </span>
            </div>
          ) : (
            <DialogFooter>
              <Button variant="ghost" onClick={() => requestClose(false)}>
                Cancel
              </Button>
              <Button type="submit" disabled={formState.isSubmitting}>
                {formState.isSubmitting ? 'Adding…' : 'Add client'}
              </Button>
            </DialogFooter>
          )}
        </form>
      </DialogContent>
    </Dialog>
  )
}
