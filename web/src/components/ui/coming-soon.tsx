import type { ReactNode } from 'react'

/**
 * The page for a module that is planned but not built: a serif headline (one of the three places the
 * serif is allowed), one sentence about what it will do, and one line about what to use today.
 */
export function ComingSoon({ name, sentence, children }: { name: string; sentence: string; children: ReactNode }) {
  return (
    <div className="mx-auto grid max-w-prose justify-items-start gap-3 py-10 md:py-16">
      <h1 className="text-[22px] leading-7 md:text-[26px] md:leading-8">{name} is coming soon</h1>
      <p className="text-[15px] leading-6 text-muted-foreground">{sentence}</p>
      <p className="text-sm text-foreground">
        <span className="font-medium">Until then:</span> {children}
      </p>
    </div>
  )
}
