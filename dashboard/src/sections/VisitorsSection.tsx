import { RingChart } from '@/components/charts/ring-chart'
import { Ring } from '@/components/charts/ring'
import { RingCenter } from '@/components/charts/ring-center'
import { int, pct } from '@/format'
import type { BotRow, Source } from '@/types'
import { Code, Section } from '@/ui'

const NAME: Record<BotRow['class'], string> = { human: 'People', known_bot: 'Known crawlers', suspected_bot: 'Suspected bots' }
const COLOUR = ['var(--accent)', 'var(--ink-2)', 'var(--warn)', 'var(--bad)', 'var(--mute)']

export function VisitorsSection({ s }: { s: Source }) {
  const rows = [...s.bots].sort((a, b) => b.requests - a.requests)
  const total = rows.reduce((a, r) => a + r.requests, 0)
  const label = (r: BotRow) => (r.reason === 'none' ? NAME[r.class] : `${NAME[r.class]}: ${r.reason}`)
  const data = rows.map((r, i) => ({ label: label(r), value: r.requests, maxValue: total, color: COLOUR[i] }))

  return (
    <Section
      title="Who is visiting"
      question="Requests by visitor type. Each ring is that type's share of all requests."
      source={<>From <Code>agg_bots_daily</Code>. Rules run in order: known crawler, scripted or missing user agent, request rate, pages without stylesheets or images.</>}
    >
      <div className="grid items-center gap-6 sm:grid-cols-[200px_minmax(0,1fr)]">
        <div className="relative mx-auto">
          <RingChart data={data} size={200} strokeWidth={11} ringGap={5}>
            {data.map((d, i) => (
              <Ring key={d.label} index={i} color={d.color} showGlow={false} lineCap="butt" />
            ))}
            <RingCenter defaultLabel="Requests" />
          </RingChart>
        </div>
        <ul className="m-0 grid list-none gap-2 p-0 text-[13.5px]">
          {rows.map((r, i) => (
            <li key={label(r)} className="grid grid-cols-[10px_minmax(0,1fr)_auto_auto] items-center gap-3">
              <span className="size-2.5 rounded-sm" style={{ background: COLOUR[i] }} />
              <span className="min-w-0">
                {NAME[r.class]}
                {r.reason !== 'none' && <span className="text-mute"> · {r.reason}</span>}
              </span>
              <span className="text-ink-2">{int(r.requests)}</span>
              <span className="w-12 text-right font-display font-bold">{pct(r.share)}</span>
            </li>
          ))}
        </ul>
      </div>
    </Section>
  )
}
