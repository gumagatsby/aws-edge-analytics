import NumberFlow from '@number-flow/react'
import type { Source } from '@/types'

/** The four answers a reader wants first, set large. NumberFlow animates them when the source changes. */
export function Figures({ s }: { s: Source }) {
  const errors = s.daily.reduce((a, d) => a + d.errors_4xx + d.errors_5xx, 0)
  const items = [
    {
      label: 'Requests',
      value: <NumberFlow value={s.totals.requests} locales="en-GB" />,
      note: `${s.totals.days} day${s.totals.days > 1 ? 's' : ''}, ${errors.toLocaleString('en-GB')} errors`,
    },
    {
      label: 'CDN cost estimate',
      value: (
        <NumberFlow
          value={s.cost.total_usd}
          locales="en-US"
          format={{ style: 'currency', currency: 'USD', maximumFractionDigits: s.cost.total_usd < 1 ? 4 : 2 }}
        />
      ),
      note: `${s.totals.gb < 1 ? (s.totals.gb * 1000).toFixed(1) + ' MB' : s.totals.gb.toFixed(1) + ' GB'} served, list price`,
    },
    {
      label: 'Cache hit ratio',
      value: <NumberFlow value={s.totals.hit_ratio ?? 0} format={{ style: 'percent', minimumFractionDigits: 1, maximumFractionDigits: 1 }} />,
      note: 'of requests the cache could serve',
    },
    {
      label: 'Bot traffic',
      value: <NumberFlow value={s.totals.bot_share ?? 0} format={{ style: 'percent', minimumFractionDigits: 1, maximumFractionDigits: 1 }} />,
      note: 'known crawlers and suspected bots',
    },
  ]
  return (
    <div className="grid grid-cols-2 gap-x-6 gap-y-6 lg:grid-cols-4">
      {items.map((i) => (
        <div key={i.label} className="grid min-w-0 gap-1">
          <span className="text-[13.5px] text-ink-2">{i.label}</span>
          <span className="font-display text-[clamp(28px,4.2vw,46px)] leading-none font-extrabold tracking-[-0.02em]">
            {i.value}
          </span>
          <span className="text-xs text-mute">{i.note}</span>
        </div>
      ))}
    </div>
  )
}
