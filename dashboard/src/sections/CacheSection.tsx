import { LineChart } from '@/components/charts/line-chart'
import { Line } from '@/components/charts/line'
import { Grid } from '@/components/charts/grid'
import { XAxis } from '@/components/charts/x-axis'
import { YAxis } from '@/components/charts/y-axis'
import { ReferenceArea } from '@/components/charts/reference-area'
import { ChartTooltip } from '@/components/charts/tooltip'
import { pct, shortDay } from '@/format'
import type { Source } from '@/types'
import { Code, Section } from '@/ui'

const ratio = (rows: { cacheable: number; hit_ratio: number | null }[]) => {
  const n = rows.reduce((a, r) => a + r.cacheable, 0)
  return n ? rows.reduce((a, r) => a + r.cacheable * (r.hit_ratio ?? 0), 0) / n : null
}

export function CacheSection({ s }: { s: Source }) {
  const tracked = s.cache.filter((c) => c.arrived_with_tracking)
  const kept = tracked.filter((c) => !c.normalised)
  const stripped = tracked.filter((c) => c.normalised)
  const plain = ratio(s.cache.filter((c) => !c.arrived_with_tracking))
  const days = [...new Set(tracked.map((c) => c.day))].sort()
  const series = days.map((d) => ({ date: new Date(`${d}T12:00:00Z`), hit: (ratio(tracked.filter((c) => c.day === d)) ?? 0) * 100 }))
  const firstStripped = stripped.map((c) => c.day).sort()[0]

  return (
    <Section
      title="Tracking links and the cache"
      question="Homepage visits that arrive with utm_ or gclid parameters, before and after the edge function strips them"
      source={<>From <Code>agg_cache_daily</Code>. Stripping happens in the viewer-request function, before the cache lookup.</>}
    >
      <div className="grid grid-cols-3 gap-4">
        {[
          ['Parameters kept', ratio(kept)],
          ['Parameters stripped', ratio(stripped)],
          ['No parameters', plain],
        ].map(([label, v]) => (
          <div key={label as string} className="grid gap-1">
            <span className="text-xs text-mute">{label as string}</span>
            <span className="font-display text-[clamp(22px,3vw,30px)] leading-none font-extrabold">{pct(v as number | null, 0)}</span>
            <span className="text-xs text-mute">hit ratio</span>
          </div>
        ))}
      </div>
      {series.length > 1 && (
        <div className="h-[180px] min-w-0">
          <LineChart data={series} xDataKey="date" aspectRatio="auto" className="h-full" margin={{ left: 40, right: 12, top: 12, bottom: 28 }}>
            <Grid horizontal />
            {firstStripped && (
              <ReferenceArea x1={new Date(`${firstStripped}T00:00:00Z`)} x2={series[series.length - 1].date} fill="var(--accent-soft)" fillOpacity={0.6} />
            )}
            <Line dataKey="hit" stroke="var(--accent)" strokeWidth={2} showMarkers />
            <YAxis numTicks={3} formatValue={(v) => `${Math.round(v)}%`} />
            <XAxis tickMode="data" />
            <ChartTooltip />
          </LineChart>
        </div>
      )}
      {series.length > 1 && firstStripped && (
        <p className="m-0 text-xs text-mute">Shaded from {shortDay(firstStripped)}, when stripping was switched on.</p>
      )}
    </Section>
  )
}
