import { useEffect, useState } from 'react'
import { shortDay } from '@/format'
import type { Insights } from '@/types'
import { CacheSection } from '@/sections/CacheSection'
import { CostSection } from '@/sections/CostSection'
import { ExperimentSection } from '@/sections/ExperimentSection'
import { Figures } from '@/sections/Figures'
import { MapSection } from '@/sections/MapSection'
import { SpeedSection } from '@/sections/SpeedSection'
import { ErrorsSection, PipelineSection } from '@/sections/Tables'
import { VisitorsSection } from '@/sections/VisitorsSection'

type SourceKey = 'synthetic' | 'real'

const NOTES: Record<SourceKey, string> = {
  synthetic:
    "Seven days of generated logs in CloudFront's own format, with answers planted so the reports can be checked: design B converts 0.6 points better, about 12% of requests are bots, one product link is broken and Singapore had a 502 incident.",
  real: "Genuine CloudFront logs from a load generator on a laptop and from GitHub's runners in the US. Volumes are small, so rates move a lot.",
}

async function load(): Promise<Insights> {
  // In development the sample copy is used; the deployed page reads the file the pipeline publishes next to it.
  // A glob rather than an import, so a fresh checkout without the sample still builds.
  if (import.meta.env.DEV) {
    const sample = import.meta.glob<{ default: unknown }>('./dev/data.sample.json')['./dev/data.sample.json']
    if (sample) return (await sample()).default as Insights
  }
  const r = await fetch('./data.json', { cache: 'no-cache' })
  if (!r.ok) throw new Error(`data.json returned ${r.status}`)
  return r.json()
}

const fromHash = (): SourceKey => (location.hash === '#real' ? 'real' : 'synthetic')

export default function App() {
  const [data, setData] = useState<Insights | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [source, setSource] = useState<SourceKey>(fromHash)

  useEffect(() => {
    load().then(setData, (e: Error) => setError(e.message))
    const onHash = () => setSource(fromHash())
    window.addEventListener('hashchange', onHash)
    return () => window.removeEventListener('hashchange', onHash)
  }, [])

  const choose = (k: SourceKey) => {
    setSource(k)
    history.replaceState(null, '', k === 'real' ? '#real' : location.pathname + location.search)
  }

  if (error) {
    return (
      <main className="mx-auto max-w-xl px-4 py-16">
        <h1 className="text-2xl font-bold">Edge insights</h1>
        <p>The report data could not be loaded ({error}). The pipeline publishes it after each daily run; try again after the next run, or check the pipeline's alerts.</p>
      </main>
    )
  }
  if (!data) {
    return <main className="mx-auto max-w-xl px-4 py-16 text-mute" aria-live="polite">Loading the latest report…</main>
  }

  const s = data.sources[source]
  const days = s.daily.map((d) => d.day).sort()
  const period = days.length > 1 ? `${shortDay(days[0])} to ${shortDay(days[days.length - 1])} ${days[0].slice(0, 4)}` : `${shortDay(days[0])} ${days[0].slice(0, 4)}`
  const published = new Intl.DateTimeFormat('en-GB', { dateStyle: 'medium', timeStyle: 'short', timeZone: 'UTC' }).format(new Date(data.generated_at))

  return (
    <>
    <a href="#report" className="absolute left-4 -top-20 z-10 rounded-md bg-ink px-3 py-2 text-sm text-surface focus:top-4">
      Skip to the report
    </a>
    <main className="mx-auto grid max-w-[1200px] gap-5 pt-8 pb-14" style={{ paddingLeft: 'max(16px, env(safe-area-inset-left, 0px))', paddingRight: 'max(16px, env(safe-area-inset-right, 0px))' }}>
      <header className="flex flex-wrap items-end justify-between gap-4">
        <div className="grid gap-1">
          <h1 className="m-0 text-[clamp(28px,4vw,40px)] leading-none font-extrabold tracking-[-0.02em]">Edge insights</h1>
          <p className="m-0 text-[13.5px] text-ink-2"><span translate="no">Example Outfitters</span>, from <span translate="no">CloudFront</span> logs · {period}</p>
        </div>
        <div role="group" aria-label="Traffic shown" className="inline-flex gap-5">
          {(['synthetic', 'real'] as const).map((k) => (
            <button
              key={k}
              type="button"
              aria-pressed={source === k}
              onClick={() => choose(k)}
              className="py-1.5 text-[13.5px] font-medium text-mute decoration-2 underline-offset-[6px] transition-colors hover:text-ink aria-pressed:text-ink aria-pressed:underline"
            >
              {k === 'synthetic' ? 'Synthetic week' : 'Real traffic'}
            </button>
          ))}
        </div>
      </header>
      <p className="m-0 max-w-[78ch] text-[13.5px] text-ink-2">{NOTES[source]}</p>

      <div id="report" tabIndex={-1} className="scroll-mt-4 rounded-[10px] bg-surface p-5 outline-none sm:p-6" aria-live="polite">
        <Figures s={s} />
      </div>

      <MapSection s={s} synthetic={source === 'synthetic'} />

      <div className="grid gap-5 lg:grid-cols-2">
        <CostSection s={s} />
        <ExperimentSection s={s} />
      </div>

      <SpeedSection s={s} />

      <div className="grid gap-5 lg:grid-cols-2">
        <CacheSection s={s} />
        <VisitorsSection s={s} />
      </div>

      <div className="grid gap-5 lg:grid-cols-2">
        <ErrorsSection s={s} />
        <PipelineSection runs={data.pipeline.runs.filter((r) => r.source === source)} />
      </div>

      <footer className="grid max-w-[90ch] gap-1 pt-2 text-xs text-mute">
        <p className="m-0">
          Built from CloudFront standard logs by a Glue and Athena pipeline in eu-west-2. No IP addresses are kept beyond the raw logs, which are deleted after 7 days. Visitor identifiers are keyed hashes that analysts cannot see.
        </p>
        <p className="m-0">Published {published} UTC by the pipeline's publish step.</p>
      </footer>
    </main>
    </>
  )
}
