// Preferences: how this person likes the screen. They live in this browser only, never on the server.

import type { ReactNode } from 'react'
import { PageHeader } from '@/components/ca/Page'
import { ShortcutList } from '@/features/shell/ShortcutSheet'
import { usePreferences, type Density, type Theme } from '@/lib/preferences'
import { usePageTitle } from '@/lib/title'

const THEMES: { value: Theme; label: string }[] = [
  { value: 'light', label: 'Light' },
  { value: 'dark', label: 'Dark' },
  { value: 'system', label: 'Match my device' },
]
const DENSITIES: { value: Density; label: string }[] = [
  { value: 'comfortable', label: 'Comfortable' },
  { value: 'compact', label: 'Compact' },
]

function Choice<T extends string>({ legend, name, options, value, onChange }: { legend: string; name: string; options: { value: T; label: string }[]; value: T; onChange: (v: T) => void }) {
  return (
    <fieldset className="grid gap-2">
      <legend className="mb-1 text-[13px] font-semibold text-heading">{legend}</legend>
      <div className="flex flex-wrap gap-4">
        {options.map((o) => (
          <label key={o.value} className="flex cursor-pointer items-center gap-2 text-sm">
            <input type="radio" name={name} className="size-4 accent-[var(--primary)]" checked={value === o.value} onChange={() => onChange(o.value)} />
            {o.label}
          </label>
        ))}
      </div>
    </fieldset>
  )
}

function Panel({ id, title, children }: { id: string; title: string; children: ReactNode }) {
  return (
    <section aria-labelledby={id} className="grid gap-4 rounded-lg border bg-card p-5">
      <h3 id={id} className="text-[15px] font-semibold text-heading">
        {title}
      </h3>
      {children}
    </section>
  )
}

export function PreferencesScreen() {
  usePageTitle('Preferences')
  const { theme, setTheme, density, setDensity } = usePreferences()
  return (
    <div className="grid max-w-3xl gap-4 [&>*]:min-w-0">
      <PageHeader title="Preferences" description="Kept in this browser. They change how you see the screen, not the firm’s books." className="mb-0" />
      <Panel id="pref-look" title="Look">
        <Choice legend="Theme" name="theme" options={THEMES} value={theme} onChange={setTheme} />
        <Choice legend="Rows" name="density" options={DENSITIES} value={density} onChange={setDensity} />
      </Panel>
      <Panel id="pref-keys" title="Keyboard shortcuts">
        <p className="-mt-2 text-[13px] text-muted-foreground">The keys that work on this page. Press ? anywhere to see the ones for the screen you are on.</p>
        <div className="grid gap-4">
          <ShortcutList />
        </div>
      </Panel>
    </div>
  )
}
