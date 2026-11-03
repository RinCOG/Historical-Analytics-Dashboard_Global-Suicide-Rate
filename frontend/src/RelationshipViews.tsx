import { useRef, useState } from 'react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  ErrorBar,
  ReferenceLine,
  ResponsiveContainer,
  Scatter,
  ScatterChart,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type {
  RelationshipBlock,
  RelationshipPoint,
  RelationshipRow,
  RelationshipStat,
  RelationshipVerdict,
  RelationshipsCompact,
  RelationshipsFull,
} from './api'
import { formatCount, formatInterval, formatRate } from './shared'

type ViewId = 'trend' | 'persistence' | 'coverage' | 'variability'
type BlockKey = 'B1' | 'B2' | 'B3' | 'B4'

function downloadCsv(filename: string, rows: object[]) {
  if (!rows.length) return
  const keys = Object.keys(rows[0])
  const quote = (value: unknown) => `"${String(value ?? '').replace(/"/g, '""')}"`
  const content = [keys.map(quote).join(','), ...rows.map((row) => keys.map((key) => quote((row as Record<string, unknown>)[key])).join(','))].join('\n')
  const link = document.createElement('a')
  link.href = URL.createObjectURL(new Blob([content], { type: 'text/csv;charset=utf-8' }))
  link.download = filename
  link.click()
  URL.revokeObjectURL(link.href)
}

function downloadPng(container: HTMLDivElement | null, filename: string) {
  const svg = container?.querySelector('svg')
  if (!svg) return
  const cloned = svg.cloneNode(true) as SVGSVGElement
  const bounds = svg.getBoundingClientRect()
  const styles = getComputedStyle(document.querySelector('.app') ?? document.body)
  const embeddedStyles = document.createElementNS('http://www.w3.org/2000/svg', 'style')
  embeddedStyles.textContent = `
    :root {
      --accent: ${styles.getPropertyValue('--accent')};
      --secondary: ${styles.getPropertyValue('--secondary')};
      --muted: ${styles.getPropertyValue('--muted')};
      --line: ${styles.getPropertyValue('--line')};
      --line-muted: ${styles.getPropertyValue('--line-muted')};
    }
    .recharts-text { fill: var(--muted); }
    .recharts-cartesian-grid line { stroke: var(--line); }
  `
  cloned.insertBefore(embeddedStyles, cloned.firstChild)
  cloned.setAttribute('xmlns', 'http://www.w3.org/2000/svg')
  cloned.setAttribute('width', String(Math.ceil(bounds.width)))
  cloned.setAttribute('height', String(Math.ceil(bounds.height)))
  const image = new Image()
  const url = URL.createObjectURL(new Blob([new XMLSerializer().serializeToString(cloned)], { type: 'image/svg+xml;charset=utf-8' }))
  image.onload = () => {
    const canvas = document.createElement('canvas')
    canvas.width = Math.ceil(bounds.width * 2)
    canvas.height = Math.ceil(bounds.height * 2)
    const context = canvas.getContext('2d')
    if (context) {
      context.scale(2, 2)
      context.fillStyle = getComputedStyle(document.body).getPropertyValue('--surface').trim() || '#ffffff'
      context.fillRect(0, 0, bounds.width, bounds.height)
      context.drawImage(image, 0, 0, bounds.width, bounds.height)
      const link = document.createElement('a')
      link.download = filename
      link.href = canvas.toDataURL('image/png')
      link.click()
    }
    URL.revokeObjectURL(url)
  }
  image.onerror = () => URL.revokeObjectURL(url)
  image.src = url
}

function ExportButtons({ rows, name, chartRef }: { rows: object[]; name: string; chartRef: React.RefObject<HTMLDivElement | null> }) {
  return (
    <div className="export-actions" aria-label={`${name} download options`}>
      <button type="button" onClick={() => downloadCsv(`${name}.csv`, rows)} aria-label={`Download ${name} as CSV`}>CSV</button>
      <button type="button" onClick={() => downloadPng(chartRef.current, `${name}.png`)} aria-label={`Download ${name} as PNG`}>PNG</button>
    </div>
  )
}

function verdictSlug(label: RelationshipVerdict['label']) {
  return label === 'Not Favourable' ? 'not-favourable' : label.toLowerCase()
}

export function VerdictBadge({ verdict }: { verdict: RelationshipVerdict }) {
  return (
    <span
      className={`verdict-badge verdict-badge--${verdictSlug(verdict.label)}`}
      role="status"
      aria-label={`${verdict.label}, judged on ${verdict.judged_on}`}
    >
      <span className="verdict-icon" aria-hidden="true">{verdict.icon}</span>
      <strong>{verdict.label}</strong>
      <span className="verdict-judged">Judged on: {verdict.judged_on}</span>
    </span>
  )
}

function pointCsv(block: RelationshipBlock) {
  return block.points.map((point) => ({
    entity: point.entity,
    code: point.code,
    x: point.x,
    y: point.y,
    x_observations: point.x_obs,
    y_observations: point.y_obs,
    former_state: point.former_state,
  }))
}

function HiddenPointTable({ block }: { block: RelationshipBlock }) {
  return (
    <div className="sr-only">
      <table>
        <caption>{block.title} data table</caption>
        <thead>
          <tr><th scope="col">Entity</th><th scope="col">{block.x_label}</th><th scope="col">{block.y_label}</th><th scope="col">Observations</th><th scope="col">Former state</th></tr>
        </thead>
        <tbody>
          {block.points.map((point) => (
            <tr key={point.entity}>
              <td>{point.entity}</td>
              <td>{formatRate(point.x)}</td>
              <td>{formatRate(point.y)}</td>
              <td>{point.x_obs} / {point.y_obs}</td>
              <td>{point.former_state ? 'Yes' : 'No'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

function StatStrip({ block }: { block: RelationshipBlock }) {
  return (
    <p className="relationship-stats" aria-label={`Statistics for ${block.title}`}>
      <span><strong>{formatCount(block.n)}</strong> n</span>
      <span><strong>{formatRate(block.pearson)}</strong> Pearson r <span className="stat-interval">[{formatInterval(block.pearson_ci)}]</span></span>
      <span><strong>{formatRate(block.spearman)}</strong> Spearman rho <span className="stat-interval">[{formatInterval(block.spearman_ci)}]</span></span>
    </p>
  )
}

function SensitivityTable({ block }: { block: RelationshipBlock }) {
  if (!block.sensitivity.length) return null
  return (
    <div className="table-scroll relationship-sensitivity">
      <table>
        <caption className="sr-only">{block.title} sensitivity checks</caption>
        <thead>
          <tr><th scope="col">Sensitivity</th><th scope="col">n</th><th scope="col">Pearson r</th><th scope="col">Spearman rho</th></tr>
        </thead>
        <tbody>
          {block.sensitivity.map((row: RelationshipStat) => (
            <tr key={row.id}>
              <td>{row.label}</td>
              <td>{formatCount(row.n)}</td>
              <td>{formatRate(row.pearson)}</td>
              <td>{formatRate(row.spearman)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

type PointShapeProps = { cx?: number; cy?: number; payload?: RelationshipPoint }

function ScatterPointShape(props: PointShapeProps, selectedEntity: string, xLabel: string, yLabel: string, showLabels: boolean) {
  const { cx, cy, payload } = props
  if (cx === undefined || cy === undefined || !payload) return <g />
  const selected = payload.entity === selectedEntity
  const label = `${payload.entity}: ${xLabel} ${formatRate(payload.x)}, ${yLabel} ${formatRate(payload.y)}, ${payload.x_obs} and ${payload.y_obs} observations${selected ? ', selected country' : ''}`
  const common = {
    fill: selected ? 'var(--accent-dark)' : payload.former_state ? 'var(--secondary)' : 'var(--accent)',
    stroke: selected ? 'var(--ink)' : 'var(--surface)',
    strokeWidth: selected ? 2 : 1,
  }
  return (
    <g
      className={`scatter-point${selected ? ' scatter-point--selected' : ''}`}
      tabIndex={0}
      role="img"
      aria-label={label}
    >
      <title>{label}</title>
      {payload.former_state ? (
        <rect x={cx - (selected ? 5 : 4)} y={cy - (selected ? 5 : 4)} width={selected ? 10 : 8} height={selected ? 10 : 8} {...common} />
      ) : (
        <circle cx={cx} cy={cy} r={selected ? 6 : 4} {...common} />
      )}
      {showLabels && payload.label_rank !== null && payload.label_rank <= 10 && (
        <text x={cx + 7} y={cy - 7} className="scatter-label">{payload.entity}</text>
      )}
    </g>
  )
}

function ScatterTooltip({ active, payload, block }: { active?: boolean; payload?: Array<{ payload?: RelationshipPoint }>; block: RelationshipBlock }) {
  if (!active || !payload?.length) return null
  const point = payload[0]?.payload
  if (!point) return null
  return (
    <div className="chart-tooltip">
      <strong>{point.entity}</strong>
      <div>{block.x_label}: {formatRate(point.x)} <span>· {point.x_obs} observations</span></div>
      <div>{block.y_label}: {formatRate(point.y)} <span>· {point.y_obs} observations</span></div>
      <div>{point.former_state ? 'Former-state entity' : 'Current ISO entity'}</div>
    </div>
  )
}

function ScatterPlot({ block, selectedEntity, height = 300, showLabels = false }: {
  block: RelationshipBlock
  selectedEntity: string
  height?: number
  showLabels?: boolean
}) {
  const xValues = block.points.map((point) => point.x)
  const yValues = block.points.map((point) => point.y)
  const maxValue = Math.max(1, ...xValues, ...yValues)
  const commonDomain: [number, number] = [0, Math.ceil(maxValue * 1.05)]
  const xDomain: [number, number] = block.reference_line ? commonDomain : [0, Math.ceil(Math.max(1, ...xValues) * 1.05)]
  const yDomain: [number, number] = block.reference_line ? commonDomain : [0, Math.ceil(Math.max(1, ...yValues) * 1.05)]
  const renderPoint = (props: unknown) => ScatterPointShape(props as PointShapeProps, selectedEntity, block.x_label, block.y_label, showLabels)
  return (
    <div className="chart-wrap relationship-scatter" style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <ScatterChart margin={{ top: 16, right: 22, bottom: 34, left: 10 }}>
          <CartesianGrid strokeDasharray="3 5" />
          <XAxis
            type="number"
            dataKey="x"
            name={block.x_label}
            domain={xDomain}
            tickCount={6}
            label={{ value: block.x_label, position: 'insideBottom', offset: -18 }}
          />
          <YAxis
            type="number"
            dataKey="y"
            name={block.y_label}
            domain={yDomain}
            tickCount={6}
            width={58}
            label={{ value: block.y_label, angle: -90, position: 'insideLeft', offset: 4 }}
          />
          <Tooltip content={<ScatterTooltip block={block} />} />
          {block.reference_line && (
            <ReferenceLine
              segment={[{ x: 0, y: 0 }, { x: commonDomain[1], y: commonDomain[1] }]}
              stroke="var(--line-muted)"
              strokeDasharray="4 5"
              label={{ value: 'equal rates in both periods', position: 'insideTopLeft', fontSize: 10 }}
            />
          )}
          {block.cutoff !== undefined && (
            <ReferenceLine
              x={block.cutoff}
              stroke="var(--line-muted)"
              strokeDasharray="4 5"
              label={{ value: block.cutoff_label ?? `${block.cutoff}-year cutoff`, position: 'insideTopRight', fontSize: 10 }}
            />
          )}
          <Scatter
            data={block.points}
            name={block.title}
            isAnimationActive={false}
            shape={renderPoint}
          />
        </ScatterChart>
      </ResponsiveContainer>
    </div>
  )
}

function AChart({ rows, height = 190 }: { rows: RelationshipRow[]; height?: number }) {
  const data = rows.map((row) => ({
    axisLabel: `${row.id} · n=${formatCount(row.n)}`,
    label: row.label,
    pearson: row.pearson,
    ci_error: row.pearson_ci && row.pearson !== null
      ? [Math.max(0, row.pearson - row.pearson_ci[0]), Math.max(0, row.pearson_ci[1] - row.pearson)]
      : [0, 0],
    interval: row.pearson_ci,
    n: row.n,
  }))
  return (
    <div className="chart-wrap relationship-a-chart" style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <BarChart data={data} layout="vertical" margin={{ top: 8, right: 24, bottom: 4, left: 8 }}>
          <CartesianGrid strokeDasharray="3 5" horizontal={false} />
          <XAxis type="number" domain={[-0.8, 0.9]} tickCount={6} />
          <YAxis type="category" dataKey="axisLabel" width={105} tick={{ fontSize: 11 }} />
          <Tooltip
            content={({ active, payload }: { active?: boolean; payload?: ReadonlyArray<{ payload?: { label?: string; pearson?: number; interval?: number[]; n?: number } }> }) => {
              if (!active || !payload?.length) return null
              const point = payload[0]?.payload
              if (!point) return null
              return (
                <div className="chart-tooltip">
                  <strong>{point.label}</strong>
                  <div>Pearson r: {formatRate(point.pearson)}</div>
                  <div>95% interval: {formatInterval(point.interval)}</div>
                  <div>n: {formatCount(point.n)}</div>
                </div>
              )
            }}
          />
          <ReferenceLine x={0} stroke="var(--line-muted)" strokeDasharray="4 5" />
          <Bar dataKey="pearson" name="Pearson r" fill="var(--accent)" barSize={13}>
            <ErrorBar dataKey="ci_error" direction="x" width={4} stroke="var(--muted)" />
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

function AStatRows({ rows }: { rows: RelationshipRow[] }) {
  return (
    <ul className="relationship-a-stats">
      {rows.map((row) => (
        <li key={row.id}>
          <strong>{row.id}</strong> {row.label}: n = {formatCount(row.n)}, r = {formatRate(row.pearson)}
          <span className="stat-interval"> [{formatInterval(row.pearson_ci)}]</span>
        </li>
      ))}
    </ul>
  )
}

function HiddenATable({ rows }: { rows: RelationshipRow[] }) {
  return (
    <div className="sr-only">
      <table>
        <caption>Trend correlation rows</caption>
        <thead><tr><th scope="col">Row</th><th scope="col">Definition</th><th scope="col">n</th><th scope="col">Pearson r</th><th scope="col">95% interval</th></tr></thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.id}><td>{row.id}</td><td>{row.label}</td><td>{row.n}</td><td>{formatRate(row.pearson)}</td><td>{formatInterval(row.pearson_ci)}</td></tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function CompactRelationships({ data, selectedEntity, from, to }: {
  data: RelationshipsCompact | null
  selectedEntity: string
  from: number
  to: number
}) {
  const [view, setView] = useState<ViewId>('trend')
  const chartRef = useRef<HTMLDivElement>(null)
  if (!data) {
    return (
      <section className="panel" id="relationships" aria-labelledby="relationships-title">
        <div className="panel-heading"><div><p className="eyebrow">06 · RELATIONSHIPS</p><h2 id="relationships-title">How rates relate across countries</h2><p className="panel-caption">Descriptive correlations on fixed periods · per 100,000</p></div></div>
        <p className="panel-note">Relationship statistics are loading.</p>
      </section>
    )
  }
  const views: Array<{ id: ViewId; label: string; block: BlockKey }> = [
    { id: 'trend', label: 'Trend correlation', block: 'B1' },
    { id: 'persistence', label: 'Persistence', block: 'B1' },
    { id: 'coverage', label: 'Coverage vs level', block: 'B3' },
    { id: 'variability', label: 'Variability', block: 'B4' },
  ]
  const active = views.find((item) => item.id === view) ?? views[0]
  const block = view === 'trend' ? null : data.block_b[active.block as 'B1' | 'B3' | 'B4']

  const takeaway = view === 'trend' ? data.takeaways.A : data.takeaways[active.block]
  const verdict = view === 'trend' ? data.block_a.verdict : block?.verdict
  const csvRows = view === 'trend'
    ? data.block_a.rows.map((row) => ({ row: row.id, definition: row.label, n: row.n, pearson: row.pearson, interval_low: row.pearson_ci?.[0] ?? null, interval_high: row.pearson_ci?.[1] ?? null }))
    : block ? pointCsv(block) : []
  const selectedPresent = block ? block.points.some((point) => point.entity === selectedEntity) : false
  return (
    <section className="panel" id="relationships" aria-labelledby="relationships-title">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">06 · RELATIONSHIPS</p>
          <h2 id="relationships-title">How rates relate across countries</h2>
          <p className="panel-caption">Descriptive correlations on fixed periods · per 100,000</p>
        </div>
        <ExportButtons rows={csvRows} name={`relationships-${view}`} chartRef={chartRef} />
      </div>
      <div className="topnav relationship-tabs" role="tablist" aria-label="Relationship views">
        {views.map((item) => (
          <button
            key={item.id}
            type="button"
            role="tab"
            aria-selected={view === item.id}
            className={view === item.id ? 'topnav-link active' : 'topnav-link'}
            onClick={() => setView(item.id)}
          >
            {item.label}
          </button>
        ))}
      </div>
      <div ref={chartRef} role="group" aria-label={view === 'trend' ? 'Dot and bar chart of Pearson r with bootstrap intervals for four inclusion rules' : `Scatter plot of ${block?.x_label} against ${block?.y_label}`}>
        {view === 'trend' ? <AChart rows={data.block_a.rows} /> : block ? <ScatterPlot block={block} selectedEntity={selectedEntity} height={300} showLabels={view === 'persistence'} /> : null}
      </div>
      {view === 'trend' ? <AStatRows rows={data.block_a.rows} /> : block ? <StatStrip block={block} /> : null}
      <p className="relationship-takeaway">{takeaway}</p>
      <div className="relationship-meta">
        {verdict && <VerdictBadge verdict={verdict} />}
        <a className="see-full-link" href={`/analysis?from=${from}&to=${to}&entity=${encodeURIComponent(selectedEntity)}`}>See full analysis</a>
      </div>
      <p className="panel-note">{data.note} Descriptive only: no causes or forecasts; correlation does not establish causation. {view !== 'trend' && block ? (selectedPresent ? `${selectedEntity} is highlighted.` : `${selectedEntity} has no data in this fixed view.`) : ''}</p>
      {view === 'trend' ? <HiddenATable rows={data.block_a.rows} /> : block ? <HiddenPointTable block={block} /> : null}
    </section>
  )
}

function blockMethod(key: BlockKey, data: RelationshipsFull): string {
  if (key === 'B1' || key === 'B2') {
    const window = data.methods.windows[key] as { x: number[]; y: number[]; minimum_observations: number }
    return `Each entity contributes one point: its mean over available years in ${window.x[0]}–${window.x[1]} on the x-axis and ${window.y[0]}–${window.y[1]} on the y-axis. The main row requires at least ${window.minimum_observations} observation in each window; sensitivity rows require at least 3 and exclude the six OWID former-state entities. The dashed line is y = x, not a fitted line. ${data.methods.bootstrap}`
  }
  if (key === 'B3') {
    return `Each entity contributes one point: years reported and the mean of all its available yearly rates. The vertical dashed line marks the 10-year cutoff. The subset row repeats the association among entities with at least 10 years. ${data.methods.bootstrap}`
  }
  return `Each entity with at least 10 observations contributes its country mean and the sample standard deviation of its yearly rates. Sensitivity rows repeat the calculation at 5, 10, and 20 observations. ${data.methods.bootstrap}`
}

function blockInterpretation(key: BlockKey, block: RelationshipBlock, data: RelationshipsFull) {
  const sensitivity = block.sensitivity.map((row) => `${row.label.toLowerCase()}: r = ${formatRate(row.pearson)}, rho = ${formatRate(row.spearman)}`).join('; ')
  const common = `Rule applied: ${block.verdict.rule} ${block.verdict.reason}`
  if (key === 'B1' || key === 'B2') {
    return (
      <>
        With n = {formatCount(block.n)}, Pearson r = {formatRate(block.pearson)} and Spearman rho = {formatRate(block.spearman)}, so the ordering of country means is highly persistent between the fixed windows. {common} The sensitivity checks do not change that reading ({sensitivity}). What could change this: a different window definition, many countries with only one observation in a window, or a future revision of the source series. <br />Conclusion: a correlation is present and strong between country means over the fixed windows (Pearson r = ${block.pearson}, Spearman rho = ${block.spearman}), so the ordering-persistence finding is Favourable under the applied verdict rule. <br />Reason: Spearman rho is at or above 0.80 with n at or above 30 in both the main and sensitivity rows, so country rankings are stable across the fixed windows. Descriptive only: these are observed associations, not causes or forecasts; correlation does not establish causation.
      </>
    )
  }
  if (key === 'B3') {
    return (
      <>
        Across all {formatCount(block.n)} entities the coverage–level association is weak (Pearson r = {formatRate(block.pearson)}, Spearman rho = {formatRate(block.spearman)}), and among the {formatCount(block.subset?.n ?? 0)} entities with at least 10 years it is essentially absent (r = {formatRate(block.subset?.pearson ?? null)}). {common} The sensitivity rows ({sensitivity}) show the same weak pattern. What could change this: a different minimum-years rule or a cohort of countries with very different reporting histories. <br />Conclusion: the coverage-level association is weak and effectively absent among the subset with at least 10 years, so there is no meaningful correlation; under the applied verdict rule the judgement is Mixed. <br />Reason: the full-sample association is weak (Pearson r = ${block.pearson}, Spearman rho = ${block.spearman}) and essentially absent among the well-covered subset (r = ${block.subset?.pearson ?? null}), so coverage and level are not meaningfully linked. Descriptive only: no causes, no forecasts; correlation does not establish causation.
      </>
    )
  }
  return (
    <>
      Among the {formatCount(block.n)} entities with at least 10 observations, country mean and yearly variability correlate at Pearson r = {formatRate(block.pearson)} (Spearman rho = {formatRate(block.spearman)}). {common} This matters for the <a className="see-full-link" href="#anomalies">anomaly screening</a>: one pooled z-score threshold can flag countries with larger natural variability more often. A within-country standardisation would flag {formatCount(data.anomaly_sensitivity.within_country_zscore_flags)} changes instead of {formatCount(data.anomaly_sensitivity.pooled_zscore_flags)}, changing the status of {formatCount(data.anomaly_sensitivity.status_changes)} rows; this is a sensitivity note only and the existing anomaly table is unchanged. What could change this: standardising within country, a different variability measure, or a different minimum-observation rule. <br />Conclusion: a correlation between country mean and variability is present (Pearson r = ${block.pearson}, Spearman rho = ${block.spearman}), and the pooled-screening verdict is Not Favourable; descriptive only: no causes, no forecasts; correlation does not establish causation. <br />Reason: country mean and yearly variability correlate (Pearson r = ${block.pearson}, Spearman rho = ${block.spearman}), so one pooled z-score threshold flags higher-variability countries more often, and the pooled screening rule is judged Not Favourable.
    </>
  )
}

function RelationshipInterpretation({ verdict, children }: { verdict: RelationshipVerdict; children: React.ReactNode }) {
  return (
    <aside className="interpretation-box" role="note" aria-label="Interpretation">
      <div className="interpretation-badge">
        <span className="interpretation-bubble" aria-hidden="true">i</span>
        <strong>Interpretation</strong>
      </div>
      <div className="relationship-verdict-line"><VerdictBadge verdict={verdict} /></div>
      <p>{children}</p>
    </aside>
  )
}

function FullBlock({ blockKey, block, data }: { blockKey: BlockKey; block: RelationshipBlock; data: RelationshipsFull }) {
  const chartRef = useRef<HTMLDivElement>(null)
  const anchor = `relationships-${blockKey.toLowerCase()}`
  return (
    <div id={anchor} className="chart-window relationship-block">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">{blockKey} · RELATIONSHIP</p>
          <h3>{block.title}</h3>
          <p className="panel-caption">{block.question}</p>
        </div>
        <ExportButtons rows={pointCsv(block)} name={`relationships-${blockKey.toLowerCase()}`} chartRef={chartRef} />
      </div>
      <div ref={chartRef}>
        <ScatterPlot block={block} selectedEntity="" height={340} showLabels={blockKey === 'B1'} />
      </div>
      <StatStrip block={block} />
      <SensitivityTable block={block} />
      <details className="relationship-method">
        <summary>How this was calculated</summary>
        <p>{blockMethod(blockKey, data)}</p>
        <p>{data.methods.no_pvalues}</p>
      </details>
      <RelationshipInterpretation verdict={block.verdict}>{blockInterpretation(blockKey, block, data)}</RelationshipInterpretation>
      <HiddenPointTable block={block} />
    </div>
  )
}

export function FullRelationships({ data, from, to }: { data: RelationshipsFull | null; from: number; to: number }) {
  const chartRef = useRef<HTMLDivElement>(null)
  if (!data) {
    return (
      <section id="relationships" className="panel" aria-labelledby="relationships-title">
        <div className="panel-heading"><div><p className="eyebrow">H · RELATIONSHIPS</p><h2 id="relationships-title">How rates relate across countries</h2><p className="panel-caption">Descriptive correlations, fixed windows, and full methods</p></div></div>
        <p className="panel-note">Relationship statistics are loading.</p>
      </section>
    )
  }
  return (
    <section id="relationships" className="panel" aria-labelledby="relationships-title">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">H · RELATIONSHIPS</p>
          <h2 id="relationships-title">How rates relate across countries</h2>
          <p className="panel-caption">Descriptive correlations, fixed windows, and full methods</p>
        </div>
        <ExportButtons rows={data.block_a.rows.map((row) => ({ row: row.id, definition: row.label, n: row.n, pearson: row.pearson, interval_low: row.pearson_ci?.[0] ?? null, interval_high: row.pearson_ci?.[1] ?? null }))} name="relationships-block-a" chartRef={chartRef} />
      </div>
      <p className="panel-note">
        Fixed period: 1980–1989, 1990–1999, and 2000–2005 windows; not affected by the year range {from}–{to}.{' '}
        <a className="see-full-link" href="/#relationships">Back to dashboard panel</a>
      </p>
      <div id="relationships-a" className="chart-window relationship-block">
        <div className="panel-heading"><div><p className="eyebrow">A · TREND CORRELATION</p><h3>{data.block_a.title}</h3><p className="panel-caption">{data.block_a.question}</p></div></div>
        <div ref={chartRef}><AChart rows={data.block_a.rows} height={240} /></div>
        <div className="table-scroll">
          <table>
            <caption className="sr-only">Trend correlation rows</caption>
            <thead><tr><th scope="col">Row</th><th scope="col">Definition</th><th scope="col">n</th><th scope="col">Entities</th><th scope="col">Pearson r</th><th scope="col">95% cluster-bootstrap interval</th></tr></thead>
            <tbody>
              {data.block_a.rows.map((row) => (
                <tr key={row.id}><td>{row.id}</td><td>{row.label}</td><td>{formatCount(row.n)}</td><td>{formatCount(row.entities)}</td><td>{formatRate(row.pearson)}</td><td>{formatInterval(row.pearson_ci)}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="chart-explanation">
          <p>{data.block_a.chart_note}</p>
          <p>{data.methods.block_a} {data.methods.bootstrap}</p>
          <p>{data.methods.no_pvalues}</p>
          <p>Correlation does not establish causation.</p>
        </div>
        <RelationshipInterpretation verdict={data.block_a.verdict}>
          {data.block_a.message} {data.block_a.verdict.rule} {data.block_a.verdict.reason} What could change this: a different inclusion rule, a different year window, or a different treatment of the eight complete panels. <br />Conclusion: the year–rate correlation is about zero overall but present within the complete panels and 0.72 for their yearly average, so a correlation is present and the verdict (Not Favourable on data reliability) follows from the inclusion rule; descriptive only: no causes, no forecasts; correlation does not establish causation. <br />Reason: the year–rate correlation moves from about -0.02 (all records) to 0.72 (yearly average of the eight complete panels) depending on who is included, so the answer depends on the inclusion rule and the verdict is Not Favourable.
        </RelationshipInterpretation>
        <HiddenATable rows={data.block_a.rows} />
      </div>
      {(['B1', 'B2', 'B3', 'B4'] as const).map((key) => (
        <FullBlock key={key} blockKey={key} block={data.block_b[key]} data={data} />
      ))}
      <div className="chart-explanation">
        <p><strong>Methods summary.</strong> {data.methods.no_pvalues}</p>
        <p>All relationship statistics are descriptive. The fixed windows, minimum-observation rules, entity-cluster bootstrap, and verdict thresholds are stored with the results and repeated in the findings register and methods section.</p>
      </div>
    </section>
  )
}
