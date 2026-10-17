import type { ReactNode } from 'react'
import { cn } from '@/lib/utils'

/** One band of the page: a question as the heading, the answer, and where the numbers come from. */
export function Section({
  title,
  question,
  source,
  children,
  className,
}: {
  title: string
  question: string
  source: ReactNode
  children: ReactNode
  className?: string
}) {
  return (
    <section className={cn('grid min-w-0 content-start gap-4 rounded-[10px] bg-surface p-5 sm:p-6', className)}>
      <div className="grid gap-1">
        <h2 className="m-0 text-lg font-semibold">{title}</h2>
        <p className="m-0 text-[13.5px] text-mute">{question}</p>
      </div>
      {children}
      <p className="m-0 pt-1 text-xs text-mute">{source}</p>
    </section>
  )
}

export function Code({ children }: { children: ReactNode }) {
  return <code className="rounded bg-canvas px-1 py-px text-[11.5px] text-ink-2">{children}</code>
}

type Tone = 'good' | 'warn' | 'bad' | 'plain'
const TONES: Record<Tone, string> = {
  good: 'text-good',
  warn: 'text-warn',
  bad: 'text-bad',
  plain: 'text-accent',
}

/** A value or verdict marked by colour and weight alone. */
export function Status({ tone, children, className }: { tone: Tone; children: ReactNode; className?: string }) {
  return (
    <span className={cn('font-semibold whitespace-nowrap', TONES[tone], className)}>
      {children}
    </span>
  )
}

export function Scroll({ children }: { children: ReactNode }) {
  return <div className="-mx-1 overflow-x-auto px-1">{children}</div>
}
