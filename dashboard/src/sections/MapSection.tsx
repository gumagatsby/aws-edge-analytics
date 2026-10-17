import { useMemo } from 'react'
import type { Feature, FeatureCollection, Geometry } from 'geojson'
import { feature } from 'topojson-client'
import type { GeometryCollection, Topology } from 'topojson-specification'
import world from 'world-atlas/countries-110m.json'
import {
  ChoroplethChart,
  ChoroplethFeatureComponent,
  ChoroplethTooltip,
  type ChoroplethFeatureProperties,
} from '@/components/charts/choropleth'
import { COUNTRIES, countryName } from '@/countries'
import { int, pct } from '@/format'
import type { Source } from '@/types'
import { Code, Section } from '@/ui'

const topology = world as unknown as Topology<{ countries: GeometryCollection<ChoroplethFeatureProperties> }>
const allCountries = feature(topology, topology.objects.countries) as FeatureCollection<Geometry, ChoroplethFeatureProperties>
const land: FeatureCollection<Geometry, ChoroplethFeatureProperties> = {
  type: 'FeatureCollection',
  features: allCountries.features.filter((f: Feature<Geometry, ChoroplethFeatureProperties>) => f.properties?.name !== 'Antarctica'),
}

// Five steps from the accent's lightest tint to the accent itself.
const STEPS = ['color-mix(in oklab, var(--accent) 18%, var(--map-empty))', 'color-mix(in oklab, var(--accent) 38%, var(--map-empty))',
  'color-mix(in oklab, var(--accent) 58%, var(--map-empty))', 'color-mix(in oklab, var(--accent) 78%, var(--map-empty))', 'var(--accent)']

export function MapSection({ s, synthetic }: { s: Source; synthetic: boolean }) {
  const byNumeric = useMemo(() => {
    const m = new Map<string, { code: string; requests: number; hit: number | null }>()
    for (const c of s.countries) {
      const n = COUNTRIES[c.country]?.numeric
      if (n) m.set(n, { code: c.country, requests: c.requests, hit: c.hit_ratio })
    }
    return m
  }, [s])
  const max = Math.max(...s.countries.map((c) => c.requests), 1)
  const step = (v: number) => STEPS[Math.min(STEPS.length - 1, Math.floor(Math.sqrt(v / max) * STEPS.length))]
  const top = [...s.countries].sort((a, b) => b.requests - a.requests).slice(0, 8)
  const total = s.countries.reduce((a, c) => a + c.requests, 0)

  return (
    <Section
      title="Where the traffic comes from"
      question="Requests by viewer country, as CloudFront geolocates them"
      source={<>From <Code>agg_country_daily</Code>. Shading is on a square-root scale so smaller markets stay visible.{synthetic
        ? ' Countries are generated with the synthetic audience.'
        : ' Zimbabwe leads because the load generator ran on a test laptop there, and the US share is GitHub\'s runners. Neither reflects where the retailer\'s customers are.'}</>}
    >
      <div className="grid min-w-0 gap-6 lg:grid-cols-[minmax(0,1fr)_280px] lg:items-center">
        <div className="min-w-0">
          <ChoroplethChart data={land} aspectRatio="1.8 / 1" zoomEnabled={false}>
            <ChoroplethFeatureComponent
              stroke="var(--surface)"
              strokeWidth={0.5}
              getFeatureColor={(f) => {
                const hit = byNumeric.get(String(f.id ?? f.properties?.id ?? ''))
                return hit ? step(hit.requests) : 'var(--map-empty)'
              }}
            />
            <ChoroplethTooltip
              getFeatureValue={(f) => byNumeric.get(String(f.id ?? ''))?.requests}
              formatValue={(v) => `${int(v)} requests`}
            />
          </ChoroplethChart>
        </div>
        <ol className="m-0 grid list-none gap-2 p-0">
          {top.map((c) => (
            <li key={c.country} className="grid grid-cols-[minmax(0,1fr)_auto] items-baseline gap-3 text-[13.5px]">
              <span className="truncate">{countryName(c.country)}</span>
              <span className="text-ink-2">
                {int(c.requests)} <span className="text-mute">· {pct(c.requests / total, 0)}</span>
              </span>
            </li>
          ))}
        </ol>
      </div>
    </Section>
  )
}
