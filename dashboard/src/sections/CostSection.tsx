import { motion } from 'motion/react'
import { PRICE_CLASS, pct, size, usd } from '@/format'
import type { Source } from '@/types'
import { Code, Scroll, Section } from '@/ui'

export function CostSection({ s }: { s: Source }) {
  const regions = [...s.cost.by_region].sort((a, b) => b.usd - a.usd)
  const max = Math.max(...regions.map((r) => r.usd), Number.EPSILON)
  const pcs = s.cost.price_classes
  return (
    <Section
      title="What the CDN costs"
      question="Estimated data transfer cost by pricing region, and what a cheaper price class would save"
      source={<>From <Code>agg_cost_daily</Code> at list price (AWS Pricing API, first 10 TB a month). The free tier of 1 TB a month is not deducted.</>}
    >
      {/* Labelled bars: every region's name and amount are readable without hovering. */}
      <ul className="m-0 grid list-none gap-2 p-0">
        {regions.map((r) => (
          <li key={r.pricing_region} className="grid grid-cols-[8.5rem_minmax(0,1fr)_4.5rem] items-center gap-3 text-[13.5px]">
            <span className="truncate">{r.pricing_region}</span>
            <span className="h-2.5 overflow-hidden rounded-sm bg-canvas">
              <motion.span
                className="block h-full rounded-sm bg-accent"
                initial={false}
                animate={{ width: `${(r.usd / max) * 100}%` }}
                transition={{ type: 'spring', bounce: 0, duration: 0.5 }}
              />
            </span>
            <span className="text-right font-medium">{usd(r.usd)}</span>
          </li>
        ))}
      </ul>
      <Scroll>
        <table>
          <thead>
            <tr>
              <th>If the distribution used</th>
              <th className="n">Cost</th>
              <th className="n">Saving</th>
              <th className="n">Served from further away</th>
            </tr>
          </thead>
          <tbody>
            {(['PriceClass_All', 'PriceClass_200', 'PriceClass_100'] as const).map((k) => {
              const p = pcs[k]
              return (
                <tr key={k}>
                  <td>{PRICE_CLASS[k]}</td>
                  <td className="n">{usd(p.usd)}</td>
                  <td className="n">{p.saving_vs_all ? pct(p.saving_vs_all) : '–'}</td>
                  <td className="n">
                    {p.gb_served_from_further_away
                      ? `${size(p.gb_served_from_further_away)} (${pct(p.gb_served_from_further_away / s.totals.gb, 0)})`
                      : '–'}
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </Scroll>
    </Section>
  )
}
