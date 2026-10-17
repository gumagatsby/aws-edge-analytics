import { useEffect, useState } from 'react'
import { BarChart } from '@/components/charts/bar-chart'
import { Bar } from '@/components/charts/bar'
import { BarXAxis } from '@/components/charts/bar-x-axis'
import { Grid } from '@/components/charts/grid'
import { ChartTooltip } from '@/components/charts/tooltip'
import { int, ms, pct } from '@/format'
import type { Source } from '@/types'
import { Code, Status, Scroll, Section } from '@/ui'

const SLOW_MS = 250

// Sixteen edge codes need about 640px to stay legible; narrower screens get eight.
function useWide() {
  const query = '(min-width: 640px)'
  const [wide, setWide] = useState(() => window.matchMedia(query).matches)
  useEffect(() => {
    const m = window.matchMedia(query)
    const on = () => setWide(m.matches)
    m.addEventListener('change', on)
    return () => m.removeEventListener('change', on)
  }, [])
  return wide
}

export function SpeedSection({ s }: { s: Source }) {
  const [all, setAll] = useState(false)
  const wide = useWide()
  const sorted = [...s.edges].sort((a, b) => (b.ttfb_miss_p50_ms ?? 0) - (a.ttfb_miss_p50_ms ?? 0))
  const shown = all ? sorted : sorted.slice(0, 12)
  const bars = wide ? 16 : 8
  const chart = sorted.slice(0, bars).map((e) => ({ edge: e.edge, miss: Math.round(e.ttfb_miss_p50_ms ?? 0), hit: Math.round(e.ttfb_hit_p50_ms ?? 0) }))

  return (
    <Section
      title="Where the site is slow"
      question="Time to first byte at each edge location. A cache miss goes back to the origin in London, so distance shows up there."
      source={<>From <Code>agg_edge_daily</Code>. Medians and 90th percentiles are exact.</>}
    >
      <div className="h-[220px] min-w-0">
        <BarChart data={chart} xDataKey="edge" aspectRatio="auto" className="h-full" margin={{ left: 8, right: 8, top: 8, bottom: 28 }} barGap={0.3}>
          <Grid horizontal />
          <Bar dataKey="miss" fill="var(--accent)" lineCap="butt" />
          <Bar dataKey="hit" fill="var(--mute)" lineCap="butt" />
          <BarXAxis showAllLabels />
          <ChartTooltip />
        </BarChart>
      </div>
      <div className="flex flex-wrap gap-4 text-xs text-mute">
        <span className="inline-flex items-center gap-2"><span className="size-2.5 rounded-sm bg-accent" />Cache miss, median ms</span>
        <span className="inline-flex items-center gap-2"><span className="size-2.5 rounded-sm bg-mute" />Cache hit, median ms</span>
        <span>The {Math.min(bars, sorted.length)} slowest locations. Exact values are in the table.</span>
      </div>
      <Scroll>
        <table>
          <thead>
            <tr>
              <th>Edge location</th>
              <th className="n">Requests</th>
              <th className="n">Hit ratio</th>
              <th className="n">Hit, median</th>
              <th className="n">Miss, median</th>
              <th className="n">Miss, 90th</th>
              <th className="n">5xx</th>
            </tr>
          </thead>
          <tbody>
            {shown.map((e) => (
              <tr key={e.edge}>
                <td>
                  <span translate="no" className="font-display font-semibold">{e.edge}</span>{' '}
                  <span className="text-mute">{e.city}</span>
                </td>
                <td className="n">{int(e.requests)}</td>
                <td className="n">{pct(e.hit_ratio)}</td>
                <td className="n">{ms(e.ttfb_hit_p50_ms)}</td>
                <td className="n">{(e.ttfb_miss_p50_ms ?? 0) >= SLOW_MS ? <Status tone="warn">{ms(e.ttfb_miss_p50_ms)}</Status> : ms(e.ttfb_miss_p50_ms)}</td>
                <td className="n">{ms(e.ttfb_miss_p90_ms)}</td>
                <td className="n">{e.errors_5xx > 0 ? <Status tone="bad">{int(e.errors_5xx)}</Status> : '0'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Scroll>
      {sorted.length > 12 && (
        <button
          type="button"
          onClick={() => setAll(!all)}
          className="justify-self-start p-0 text-[13px] font-medium text-accent underline decoration-1 underline-offset-4 hover:text-ink"
        >
          {all ? 'Show the 12 slowest' : `Show all ${sorted.length} edge locations`}
        </button>
      )}
    </Section>
  )
}
