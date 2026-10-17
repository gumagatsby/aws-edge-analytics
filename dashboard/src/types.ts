// The shape of insights/data.json, written by pipeline/publish.py.

export interface Daily {
  day: string
  requests: number
  gb: number
  hit_ratio: number | null
  bot_share: number
  errors_4xx: number
  errors_5xx: number
}

export interface Edge {
  edge: string
  city: string
  country: string
  pricing_region: string
  price_class: string
  requests: number
  gb: number
  hit_ratio: number | null
  ttfb_hit_p50_ms: number | null
  ttfb_miss_p50_ms: number | null
  ttfb_miss_p90_ms: number | null
  errors_5xx: number
}

export interface Country {
  country: string
  requests: number
  human_requests: number
  gb: number
  hit_ratio: number | null
}

export interface AbTest {
  rate_a: number
  rate_b: number
  difference: number
  relative_lift: number
  ci95: [number, number]
  z: number
  p_value: number
  significant: boolean
}

export interface BotRow {
  class: 'human' | 'known_bot' | 'suspected_bot'
  reason: string
  requests: number
  share: number
}

export interface ErrorRow {
  status: number
  path: string
  edge: string
  day: string
  requests: number
}

export interface CacheRow {
  day: string
  arrived_with_tracking: boolean
  normalised: boolean
  cacheable: number
  hit_ratio: number | null
}

export interface PriceClass {
  usd: number
  gb_served_from_further_away: number
  saving_vs_all: number
}

export interface Source {
  daily: Daily[]
  totals: { requests: number; gb: number; hit_ratio: number | null; bot_share: number | null; days: number }
  edges: Edge[]
  countries: Country[]
  ab: { groups: Record<'A' | 'B', { visitors: number; converters: number }>; test: AbTest }
  bots: BotRow[]
  errors: ErrorRow[]
  cache: CacheRow[]
  cost: {
    by_region: { pricing_region: string; price_class: string; gb: number; usd_per_gb: number | null; usd: number }[]
    total_usd: number
    price_classes: Record<'PriceClass_100' | 'PriceClass_200' | 'PriceClass_All', PriceClass>
  }
}

export interface Run {
  day: string
  source: string
  raw_lines: string
  clean_rows: string
  quarantined_rows: string
  balanced: string
  finished_at: string
}

export interface Insights {
  generated_at: string
  price_source: string
  sources: Record<'synthetic' | 'real', Source>
  pipeline: { runs: Run[] }
}
