import { createFileRoute } from '@tanstack/react-router'
import { PaletteProvider } from '@/features/shell/CommandPalette'
import { NotFound } from '@/features/shell/NotFound'
import { Shell } from '@/features/shell/Shell'
import { HotkeyProvider } from '@/lib/hotkeys'

// `notFoundComponent` is drawn in place of the page, inside the shell, for any address that is not a screen.
export const Route = createFileRoute('/_app')({ component: App, notFoundComponent: NotFound })

function App() {
  return (
    <HotkeyProvider>
      <PaletteProvider>
        <Shell />
      </PaletteProvider>
    </HotkeyProvider>
  )
}
