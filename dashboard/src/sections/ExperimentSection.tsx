import { motion } from 'motion/react'
import { int } from '@/format'
import type { Source } from '@/types'
import { Code, Status, Section } from '@/ui'

const pts = (x: number) => `${x >= 0 ? '+' : ''}${(x * 100).toFixed(2)} pts`

export function ExperimentSection({ s }: { s: Source }) {
  const { groups, test } = s.ab
  const rate = (g: 'A' | 'B') => groups[g].converters / groups[g].visitors
  const max = Math.max(rate('A'), rate('B'))
  // Interval scale: from the lower of zero and the interval's low end, to the higher of zero and its high end.
  const lo = Math.min(test.ci95[0], 0), hi = Math.max(test.ci95[1], 0)
  const pad = (hi - lo) * 0.15 || 0.01
  const x = (v: number) => ((v - (lo - pad)) / (hi - lo + 2 * pad)) * 100

  return (
    <Section
      title="Did the new homepage work?"
      question="Visitors shown design A or B, and how many of them bought"
      source={<>From <Code>agg_ab_daily</Code>. Groups are assigned at the edge and kept by cookie. People only. Two-sided z-test with a 95% interval.</>}
    >
      <p className="m-0 text-[15px]">
        {test.significant ? <Status tone="good">Design B converts better.</Status> : <Status tone="warn">Too few visitors to tell yet.</Status>}
      </p>
      <div className="grid gap-3">
        {(['A', 'B'] as const).map((g) => (
          <div key={g} className="grid grid-cols-[2rem_minmax(0,1fr)_auto] items-center gap-3">
            <span className="font-display text-xl font-extrabold">{g}</span>
            <span className="h-3 overflow-hidden rounded-sm bg-canvas">
              <motion.span
                className="block h-full rounded-sm"
                style={{ background: g === 'B' ? 'var(--accent)' : 'var(--mute)' }}
                initial={false}
                animate={{ width: `${(rate(g) / max) * 100}%` }}
                transition={{ type: 'spring', bounce: 0, duration: 0.5 }}
              />
            </span>
            <span className="text-right text-[13.5px]">
              <span className="font-display text-base font-bold">{(rate(g) * 100).toFixed(2)}%</span>{' '}
              <span className="text-mute">{int(groups[g].converters)} of {int(groups[g].visitors)}</span>
            </span>
          </div>
        ))}
      </div>
      <figure className="m-0 grid gap-2">
        <svg viewBox="0 0 100 20" preserveAspectRatio="none" className="h-8 w-full" role="img"
          aria-label={`B minus A is ${pts(test.difference)}, 95% interval ${pts(test.ci95[0])} to ${pts(test.ci95[1])}`}>
          <line x1={x(0)} x2={x(0)} y1="2" y2="18" stroke="var(--mute)" strokeWidth="1" strokeDasharray="2 2" vectorEffect="non-scaling-stroke" />
          <motion.line y1="10" y2="10" stroke="var(--accent)" strokeWidth="4" vectorEffect="non-scaling-stroke"
            initial={false} animate={{ x1: x(test.ci95[0]), x2: x(test.ci95[1]) }} transition={{ type: 'spring', bounce: 0, duration: 0.5 }} />
          <motion.circle cy="10" r="2.2" fill="var(--ink)" initial={false} animate={{ cx: x(test.difference) }}
            transition={{ type: 'spring', bounce: 0, duration: 0.5 }} />
        </svg>
        <figcaption className="flex flex-wrap justify-between gap-2 text-xs text-mute">
          <span>{pts(test.ci95[0])}</span>
          <span>
            B minus A <b className="font-display text-sm text-ink">{pts(test.difference)}</b>{' '}
            (p {test.p_value < 0.001 ? '< 0.001' : `= ${test.p_value.toFixed(2)}`})
          </span>
          <span>{pts(test.ci95[1])}</span>
        </figcaption>
      </figure>
    </Section>
  )
}
