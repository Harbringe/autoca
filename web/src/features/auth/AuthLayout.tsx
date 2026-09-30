import type { ReactNode } from 'react'
import { Card } from '@/components/ui/card'

export function Brand({ className }: { className?: string }) {
  return (
    <div className={`flex items-center gap-2.5 ${className ?? ''}`}>
      <span className="grid size-8 place-items-center rounded-md bg-[#2f6f62] text-[13px] font-bold tracking-tight text-white" aria-hidden>
        CA
      </span>
      <span className="text-lg font-semibold tracking-tight">AutoCA</span>
    </div>
  )
}

/** The frame every signed-out screen shares: the brand, one card, nothing else to look at. */
export function AuthLayout({ title, subtitle, children }: { title: string; subtitle?: ReactNode; children: ReactNode }) {
  return (
    <main className="grid min-h-svh place-items-center bg-background p-4">
      <div className="w-full max-w-sm">
        <Brand className="mb-6 justify-center" />
        <Card className="p-6">
          <h1 className="text-xl font-semibold leading-tight">{title}</h1>
          {subtitle && <p className="mt-1.5 text-sm text-muted-foreground">{subtitle}</p>}
          <div className="mt-5">{children}</div>
        </Card>
      </div>
    </main>
  )
}
