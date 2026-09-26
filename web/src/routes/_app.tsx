import { createFileRoute } from '@tanstack/react-router'
import { PaletteProvider } from '@/features/shell/CommandPalette'
import { Shell } from '@/features/shell/Shell'
import { HotkeyProvider } from '@/lib/hotkeys'

export const Route = createFileRoute('/_app')({ component: App })

function App() {
  return (
    <HotkeyProvider>
      <PaletteProvider>
        <Shell />
      </PaletteProvider>
    </HotkeyProvider>
  )
}
