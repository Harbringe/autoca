import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Kbd } from '@/components/ui/kbd'
import { comboKeys, useHotkeyList } from '@/lib/hotkeys'

/** Lists the keys that work on this screen right now -- whatever is registered, and nothing that is not. */
export function ShortcutSheet({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const hotkeys = useHotkeyList()
  const groups = new Map<string, typeof hotkeys>()
  for (const hotkey of hotkeys) {
    const group = hotkey.group ?? 'Global'
    groups.set(group, [...(groups.get(group) ?? []), hotkey])
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg" aria-describedby={undefined}>
        <DialogHeader>
          <DialogTitle>Keyboard shortcuts</DialogTitle>
          <DialogDescription>Everything here works without the mouse.</DialogDescription>
        </DialogHeader>
        <div className="grid max-h-[60vh] gap-5 overflow-y-auto pr-1">
          {[...groups].map(([group, entries]) => (
            <section key={group}>
              <h3 className="mb-1.5 text-xs font-medium uppercase tracking-wide text-muted-foreground">{group}</h3>
              <ul className="grid gap-1">
                {entries.map((hotkey) => (
                  <li key={hotkey.combo + hotkey.description} className="flex items-center justify-between gap-4 py-1 text-sm">
                    <span>{hotkey.description}</span>
                    <span className="flex shrink-0 items-center gap-1">
                      {comboKeys(hotkey.combo).map((key, i) => (
                        <Kbd key={i}>{key}</Kbd>
                      ))}
                    </span>
                  </li>
                ))}
              </ul>
            </section>
          ))}
        </div>
      </DialogContent>
    </Dialog>
  )
}
