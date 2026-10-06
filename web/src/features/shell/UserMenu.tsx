import { Keyboard, LogOut, Monitor, Moon, Rows3, Sun } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Kbd } from '@/components/ui/kbd'
import { usePreferences, type Density, type Theme } from '@/lib/preferences'
import { cn } from '@/lib/utils'
import { useSession } from '@/session/session'

export function userInitials(me: { full_name?: string | null; email?: string | null } | null | undefined): string {
  return (me?.full_name || me?.email || '?')
    .split(/[\s@.]+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase())
    .join('')
}

/** The person's avatar, opening theme, row density, shortcuts and sign-out. `rail` sits on the dark rail and opens to its right. */
export function UserMenu({ onShortcuts, variant = 'top' }: { onShortcuts: () => void; variant?: 'top' | 'rail' | 'drawer' }) {
  const { me, signOut } = useSession()
  const { theme, setTheme, density, setDensity } = usePreferences()
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          aria-label="Account and preferences"
          className={cn(
            'rounded-full text-[13px] font-semibold',
            variant === 'top' && 'bg-secondary max-sm:size-11',
            variant === 'rail' && 'size-9 shrink-0 bg-white/10 text-sidebar-foreground hover:bg-white/20 hover:text-white',
            variant === 'drawer' && 'size-11 shrink-0 bg-white/10 text-sidebar-foreground hover:bg-white/20 hover:text-white',
          )}
        >
          {userInitials(me)}
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align={variant === 'top' ? 'end' : 'start'} side={variant === 'rail' ? 'right' : variant === 'drawer' ? 'top' : 'bottom'} className="w-64">
        <div className="px-2 py-2">
          <div className="truncate text-sm font-medium">{me?.full_name || me?.email}</div>
          <div className="truncate text-xs text-muted-foreground">{me?.email}</div>
          <div className="text-xs text-muted-foreground">{me?.role_display}</div>
        </div>
        <DropdownMenuSeparator />
        <DropdownMenuLabel>Theme</DropdownMenuLabel>
        <DropdownMenuRadioGroup value={theme} onValueChange={(v) => setTheme(v as Theme)}>
          <DropdownMenuRadioItem value="light"><Sun /> Light</DropdownMenuRadioItem>
          <DropdownMenuRadioItem value="dark"><Moon /> Dark</DropdownMenuRadioItem>
          <DropdownMenuRadioItem value="system"><Monitor /> Match my device</DropdownMenuRadioItem>
        </DropdownMenuRadioGroup>
        <DropdownMenuLabel>Rows</DropdownMenuLabel>
        <DropdownMenuRadioGroup value={density} onValueChange={(v) => setDensity(v as Density)}>
          <DropdownMenuRadioItem value="comfortable"><Rows3 /> Comfortable</DropdownMenuRadioItem>
          <DropdownMenuRadioItem value="compact"><Rows3 /> Compact</DropdownMenuRadioItem>
        </DropdownMenuRadioGroup>
        <DropdownMenuSeparator />
        <DropdownMenuItem onSelect={onShortcuts}>
          <Keyboard /> Keyboard shortcuts <Kbd className="ml-auto">?</Kbd>
        </DropdownMenuItem>
        <DropdownMenuItem onSelect={() => void signOut()}>
          <LogOut /> Sign out
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  )
}
