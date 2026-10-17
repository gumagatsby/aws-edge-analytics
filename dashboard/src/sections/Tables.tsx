import { int, shortDay } from '@/format'
import type { Run, Source } from '@/types'
import { Code, Status, Scroll, Section } from '@/ui'

export function ErrorsSection({ s }: { s: Source }) {
  const rows = [...s.errors].sort((a, b) => b.requests - a.requests).slice(0, 8)
  return (
    <Section
      title="Errors"
      question="The most frequent error responses, by path and edge location"
      source={<>From <Code>agg_errors_daily</Code>. Server errors by edge location are also in the speed table.</>}
    >
      <Scroll>
        <table>
          <thead>
            <tr><th>Status</th><th>Path</th><th>Edge</th><th>Day</th><th className="n">Requests</th></tr>
          </thead>
          <tbody>
            {rows.map((e) => (
              <tr key={`${e.status}${e.path}${e.edge}${e.day}`}>
                <td><Status tone={e.status >= 500 ? 'bad' : 'warn'}>{e.status}</Status></td>
                <td className="max-w-[16rem] truncate" translate="no">{e.path}</td>
                <td translate="no" className="font-display font-semibold">{e.edge}</td>
                <td>{shortDay(e.day)}</td>
                <td className="n">{int(e.requests)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Scroll>
    </Section>
  )
}

export function PipelineSection({ runs }: { runs: Run[] }) {
  const rows = [...runs].sort((a, b) => a.day.localeCompare(b.day))
  return (
    <Section
      title="Pipeline"
      question="Every run has to account for every log line, or it fails"
      source={<>From <Code>run_audit</Code>. Log lines = clean rows + quarantined rows.</>}
    >
      <Scroll>
        <table>
          <thead>
            <tr><th>Day</th><th className="n">Log lines</th><th className="n">Clean</th><th className="n">Quarantined</th><th>Balanced</th></tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr key={r.day + r.source}>
                <td>{shortDay(r.day)}</td>
                <td className="n">{int(Number(r.raw_lines))}</td>
                <td className="n">{int(Number(r.clean_rows))}</td>
                <td className="n">{int(Number(r.quarantined_rows))}</td>
                <td>{r.balanced === 'true' ? <Status tone="good">Yes</Status> : <Status tone="bad">No</Status>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Scroll>
    </Section>
  )
}
