import { useEffect, useMemo, useRef, useState } from 'react'
import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
  Bar,
  BarChart,
} from 'recharts'
import { api, type Anomaly, type CompareRow, type Country, type Coverage, type Insight, type KPI, type TopCountry, type TrendRow } from './api'

const ALL_YEARS = { from: 1950, to: 2005 }
type DashboardData = {
  kpis: KPI | null
  trend: TrendRow[]
  top: TopCountry[]
  compare: CompareRow[]
  anomalies: Anomaly[]
  coverage: Coverage[]
  countries: Country[]
  insights: Insight[]
}

const emptyData: DashboardData = {
  kpis: null, trend: [], top: [], compare: [], anomalies: [], coverage: [], countries: [], insights: [],
}

function formatRate(value: number) {
  return value.toLocaleString('en', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
}

function formatExact(value: number) {
  return String(value)
}

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

function PanelHeader({ eyebrow, title, caption, rows, name, chartRef }: {
  eyebrow: string; title: string; caption: string; rows: object[]; name: string; chartRef: React.RefObject<HTMLDivElement | null>
}) {
  return (
    <div className="panel-heading">
      <div>
        <p className="eyebrow">{eyebrow}</p>
        <h2>{title}</h2>
        <p className="panel-caption">{caption}</p>
      </div>
      <ExportButtons rows={rows} name={name} chartRef={chartRef} />
    </div>
  )
}

function App() {
  const [range, setRange] = useState(ALL_YEARS)
  const [selectedEntity, setSelectedEntity] = useState('')
  const [search, setSearch] = useState('')
  const [darkMode, setDarkMode] = useState(false)
  const [data, setData] = useState(emptyData)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const trendRef = useRef<HTMLDivElement>(null)
  const topRef = useRef<HTMLDivElement>(null)
  const compareRef = useRef<HTMLDivElement>(null)
  const coverageRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    api.countries().then((countries) => {
      setData((current) => ({ ...current, countries }))
      const defaultCountry = countries.find((country) => country.entity === 'Lithuania')?.entity ?? countries[0]?.entity ?? ''
      setSelectedEntity((current) => current || defaultCountry)
      setSearch((current) => current || defaultCountry)
    }).catch((caught: Error) => setError(caught.message))
    api.insights().then((insights) => setData((current) => ({ ...current, insights })))
      .catch((caught: Error) => setError(caught.message))
  }, [])

  useEffect(() => {
    if (!selectedEntity) return
    let active = true
    setLoading(true)
    setError('')
    Promise.all([
      api.kpis(range.from, range.to),
      api.trend(range.from, range.to),
      api.top(range.from, range.to),
      api.compare(selectedEntity, range.from, range.to),
      api.anomalies(selectedEntity, range.from, range.to),
      api.coverage(range.from, range.to),
    ]).then(([kpis, trend, top, compare, anomalies, coverage]) => {
      if (active) setData((current) => ({ ...current, kpis, trend, top, compare, anomalies, coverage }))
    }).catch((caught: Error) => {
      if (active) setError(caught.message)
    }).finally(() => {
      if (active) setLoading(false)
    })
    return () => { active = false }
  }, [range, selectedEntity])

  const selectedCountry = useMemo(() => data.countries.find((country) => country.entity === selectedEntity), [data.countries, selectedEntity])
  const updateFrom = (value: number) => setRange((current) => ({ ...current, from: Math.max(1950, Math.min(Math.trunc(value || 1950), current.to)) }))
  const updateTo = (value: number) => setRange((current) => ({ ...current, to: Math.min(2005, Math.max(Math.trunc(value || 2005), current.from)) }))

  return (
    <div className={darkMode ? 'app theme-dark' : 'app'}>
      <header className="topbar">
        <a className="brand" href="#main" aria-label="Global health data home">
          <span className="brand-mark" aria-hidden="true">GH</span>
          <span>Global health data</span>
        </a>
        <div className="topbar-actions">
          <span className="dataset-badge"><span aria-hidden="true" className="status-dot" /> Historical dataset · 1950—2005</span>
          <button className="theme-toggle" onClick={() => setDarkMode((value) => !value)} aria-label={`Switch to ${darkMode ? 'light' : 'dark'} theme`}>
            {darkMode ? 'Light theme' : 'Dark theme'}
          </button>
        </div>
      </header>

      <main id="main" className="dashboard">
        <section className="page-intro" aria-labelledby="page-title">
          <div className="intro-copy">
            <p className="eyebrow">PUBLIC HEALTH · HISTORICAL INDICATORS</p>
            <h1 id="page-title">Global Suicide Rates:<br /><span>Historical Analytics Dashboard</span></h1>
            <p className="intro-description">A descriptive view of reported age-adjusted rates to support careful comparison and resource planning.</p>
          </div>
          <div className="range-control" aria-label="Global year range filter">
            <div className="range-heading">
              <span className="eyebrow">YEAR RANGE</span>
              <span className="range-values">{range.from} — {range.to}</span>
            </div>
            <div className="range-fields">
              <label>From <input type="number" min="1950" max={range.to} step="1" value={range.from} onChange={(event) => updateFrom(Number(event.target.value))} aria-label="Start year" /></label>
              <label>To <input type="number" min={range.from} max="2005" step="1" value={range.to} onChange={(event) => updateTo(Number(event.target.value))} aria-label="End year" /></label>
            </div>
            <div className="range-sliders">
              <label className="sr-only" htmlFor="from-slider">Start year slider</label>
              <input id="from-slider" type="range" min="1950" max="2005" value={range.from} onChange={(event) => updateFrom(Number(event.target.value))} />
              <label className="sr-only" htmlFor="to-slider">End year slider</label>
              <input id="to-slider" type="range" min="1950" max="2005" value={range.to} onChange={(event) => updateTo(Number(event.target.value))} />
            </div>
          </div>
        </section>

        {error && <div role="alert" className="error-banner">Dashboard data could not be loaded: {error}</div>}
        <section className="kpi-grid" aria-label="Summary indicators">
          <article className="kpi-card"><div className="kpi-label">Global average <span className="info-dot" title="Mean of all country-year observations in the selected years." aria-label="Mean of all observed country-year records">i</span></div><div className="kpi-value">{data.kpis ? formatRate(data.kpis.global_avg) : '—'}</div><div className="kpi-unit">per 100,000 · observed records</div></article>
          <article className="kpi-card"><div className="kpi-label">Peak year average</div><div className="kpi-value">{data.kpis ? data.kpis.peak_year : '—'}</div><div className="kpi-unit">{data.kpis ? `${formatRate(data.kpis.peak_value)} per 100,000` : 'Selected period'}</div></article>
          <article className="kpi-card"><div className="kpi-label">Highest eligible country</div><div className="kpi-value kpi-country">{data.kpis?.top_country?.entity ?? '—'}</div><div className="kpi-unit">{data.kpis?.top_country ? `${formatRate(data.kpis.top_country.avg_rate)} mean · ${data.kpis.top_country.years_reported} years` : 'Requires 10+ observations'}</div></article>
          <article className="kpi-card"><div className="kpi-label">Entities reported</div><div className="kpi-value">{data.kpis?.country_count ?? '—'}</div><div className="kpi-unit">in selected year range</div></article>
        </section>
        {loading && <p className="loading-note" role="status">Updating the selected period…</p>}

        <section className="panel hero-panel" aria-labelledby="trend-title">
          <PanelHeader eyebrow="01 · GLOBAL TREND" title="A changing historical picture" caption="Mean rate across entities reporting in each year · per 100,000" rows={data.trend} name="global-trend" chartRef={trendRef} />
          <div className="chart-wrap hero-chart" ref={trendRef} role="img" aria-label="Line chart of the annual global average rate by year; hover or use chart data export for exact values">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={data.trend} margin={{ top: 14, right: 18, bottom: 4, left: 0 }}>
                <CartesianGrid strokeDasharray="3 5" vertical={false} />
                <XAxis dataKey="year" type="number" domain={['dataMin', 'dataMax']} tickCount={8} />
                <YAxis domain={[0, 'auto']} width={48} label={{ value: 'Per 100,000', angle: -90, position: 'insideLeft', offset: 10 }} />
                <Tooltip content={<ChartTooltip />} />
                <ReferenceLine y={data.kpis?.global_avg} stroke="var(--line-muted)" strokeDasharray="4 5" />
                <Line type="monotone" dataKey="avg_rate" name="Average rate" stroke="var(--accent)" strokeWidth={3} dot={false} activeDot={{ r: 5 }} />
              </LineChart>
            </ResponsiveContainer>
          </div>
          <div className="chart-footnote"><span className="legend-key" /> Annual average <span className="legend-dash" /> Selected-period observation mean ({data.kpis ? formatRate(data.kpis.global_avg) : '—'}) <span className="footnote-spacer" /> Annual reporting count is in the CSV export.</div>
        </section>

        <section className="panel" aria-labelledby="top-title">
          <PanelHeader eyebrow="02 · COUNTRY BENCHMARK" title="Highest average rates" caption="Country means for the selected period · minimum 10 reporting years" rows={data.top} name="top-countries" chartRef={topRef} />
          <div className="chart-wrap top-chart" ref={topRef} role="img" aria-label="Horizontal bar chart ranking the ten eligible countries by mean rate">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={data.top} layout="vertical" margin={{ top: 0, right: 42, bottom: 0, left: 10 }}>
                <CartesianGrid strokeDasharray="3 5" horizontal={false} />
                <XAxis type="number" domain={[0, 'auto']} />
                <YAxis type="category" dataKey="entity" width={122} tick={{ fontSize: 12 }} />
                <Tooltip content={<ChartTooltip />} />
                <Bar dataKey="avg_rate" name="Mean rate" fill="var(--accent)" radius={[0, 5, 5, 0]} barSize={18} />
              </BarChart>
            </ResponsiveContainer>
          </div>
          <p className="panel-note">A minimum of 10 observed years reduces rankings driven by sparse series. It excludes Guyana (3 observations), which ranks second if all means are shown without a coverage rule.</p>
        </section>

        <div className="two-column">
          <section className="panel compare-panel" aria-labelledby="compare-title">
            <PanelHeader eyebrow="03 · COUNTRY COMPARISON" title="Country and global baseline" caption="The global annual mean uses all entities reporting in each year." rows={data.compare} name="country-comparison" chartRef={compareRef} />
            <label className="country-search" htmlFor="country-select">Search or select an entity
              <input id="country-select" list="country-options" value={search} onChange={(event) => {
                setSearch(event.target.value)
                if (data.countries.some((country) => country.entity === event.target.value)) setSelectedEntity(event.target.value)
              }} onBlur={() => {
                if (!data.countries.some((country) => country.entity === search)) setSearch(selectedEntity)
              }} placeholder="Type a country or entity name" />
              <datalist id="country-options">{data.countries.map((country) => <option key={country.code} value={country.entity}>{country.code}</option>)}</datalist>
            </label>
            <div className="chart-wrap compare-chart" ref={compareRef} role="img" aria-label={`Line chart comparing ${selectedEntity} with the global reported-country mean`}>
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={data.compare} margin={{ top: 12, right: 10, bottom: 4, left: 0 }}>
                  <CartesianGrid strokeDasharray="3 5" vertical={false} />
                  <XAxis dataKey="year" type="number" domain={['dataMin', 'dataMax']} tickCount={6} />
                  <YAxis domain={[0, 'auto']} width={42} />
                  <Tooltip content={<ChartTooltip />} />
                  <Line type="monotone" dataKey="country_rate" name={selectedEntity} stroke="var(--accent)" strokeWidth={2.5} dot={false} activeDot={{ r: 4 }} />
                  <Line type="monotone" dataKey="global_avg" name="Global mean" stroke="var(--secondary)" strokeWidth={2} dot={false} strokeDasharray="5 4" />
                </LineChart>
              </ResponsiveContainer>
            </div>
            {selectedCountry && <p className="panel-note">Code: {selectedCountry.code}. Lines are shown only for years where {selectedEntity} has a reported rate.</p>}
          </section>

          <section className="panel anomaly-panel" aria-labelledby="anomaly-title">
            <div className="panel-heading">
              <div><p className="eyebrow">04 · YEAR-OVER-YEAR ANOMALIES</p><h2 id="anomaly-title">Unusual annual changes</h2><p className="panel-caption">For {selectedEntity} · pooled z-score threshold |z| &gt; 2</p></div>
              <button className="table-export" type="button" onClick={() => downloadCsv('country-anomalies.csv', data.anomalies)}>Download CSV</button>
            </div>
            {data.anomalies.length ? <div className="table-scroll"><table><caption className="sr-only">Unusual consecutive year-to-year changes for {selectedEntity}</caption><thead><tr><th scope="col">Year</th><th scope="col">Change</th><th scope="col">Direction</th><th scope="col">z-score</th></tr></thead><tbody>
              {data.anomalies.slice(0, 8).map((anomaly) => <tr key={`${anomaly.entity}-${anomaly.year}`}><td>{anomaly.year}</td><td>{anomaly.change > 0 ? '+' : ''}{formatRate(anomaly.change)}</td><td><span className={anomaly.change > 0 ? 'direction-up' : 'direction-down'}>{anomaly.change > 0 ? 'Increase' : 'Decrease'}</span></td><td>{anomaly.z_score.toFixed(2)}</td></tr>)}
            </tbody></table></div> : <div className="empty-state">No flagged consecutive-year changes for this entity in the selected range.</div>}
            <p className="panel-note">Z-scores are standardized against all consecutive-year entity changes. Sparse or missing years are not interpolated.</p>
          </section>
        </div>

        <section className="panel" aria-labelledby="coverage-title">
          <PanelHeader eyebrow="05 · DATA AVAILABILITY" title="Reporting coverage by entity" caption={`Observed years within ${range.from}–${range.to} · gaps count missing years between first and last report`} rows={data.coverage} name="reporting-coverage" chartRef={coverageRef} />
          <div className="coverage-scroll" role="region" aria-label="Reporting coverage for all entities; scroll to inspect every row" tabIndex={0}>
            <div className="coverage-image" ref={coverageRef} role="img" aria-label="Horizontal bar chart showing reporting years and gaps for every entity">
              <ResponsiveContainer width="100%" height={Math.max(440, data.coverage.length * 21)}>
                <BarChart data={data.coverage} layout="vertical" margin={{ top: 8, right: 35, bottom: 8, left: 4 }}>
                  <CartesianGrid strokeDasharray="3 5" horizontal={false} />
                  <XAxis type="number" domain={[0, Math.max(1, range.to - range.from + 1)]} allowDecimals={false} />
                  <YAxis type="category" dataKey="entity" width={125} tick={{ fontSize: 10 }} />
                  <Tooltip content={<ChartTooltip />} />
                  <Bar dataKey="years_reported" name="Years reported" fill="var(--secondary)" radius={[0, 4, 4, 0]} barSize={13} />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </div>
          <p className="panel-note">All entities are shown, including those with no reports in the selected range. Download CSV for first/last year and internal gap counts.</p>
        </section>

        <section className="insights-section" aria-labelledby="insights-title">
          <div className="insights-intro"><p className="eyebrow">ANALYSIS SUMMARY</p><h2 id="insights-title">Key insights</h2><p>Each finding is descriptive and includes a coverage or interpretation caveat.</p></div>
          <div className="insights-list">{data.insights.map((insight, index) => <article className="insight-card" key={insight.title}><span className="insight-number">{String(index + 1).padStart(2, '0')}</span><div><h3>{insight.title}</h3><p>{insight.detail}</p><p className="caveat"><strong>Caveat</strong> {insight.caveat}</p></div></article>)}</div>
        </section>

        <section className="about-panel" aria-labelledby="about-title">
          <div><p className="eyebrow">METHOD & SOURCE</p><h2 id="about-title">About the data</h2></div>
          <div className="about-content">
            <p><strong>Source:</strong> SDG-3 suicide rates by country, age-adjusted suicides per 100,000 people. Analysis accessed October 23, 2026. Data range: 1950–2005.</p>
            <p><strong>Method:</strong> Yearly averages are unweighted means of entities with an observation in that year. Country ranking requires at least 10 observations; six former-state entities with publisher-specific codes remain available in historical views but are not ranked as current countries.</p>
            <p><strong>Limitations:</strong> Data ends in 2005; country coverage and years reported are uneven. Outliers are retained. The data are descriptive only; no causal or predictive claims are made. Correlation does not establish causation.</p>
          </div>
        </section>

        <footer className="footer">
          <p>If you or someone you know needs support, contact a local crisis service. <a href="https://findahelpline.com/" target="_blank" rel="noreferrer">Find international crisis resources at findahelpline.com<span className="sr-only"> (opens in a new tab)</span></a>.</p>
          <span>Historical public health data · Use with care</span>
        </footer>
      </main>
    </div>
  )
}

function ChartTooltip({ active, payload, label }: { active?: boolean; payload?: Array<{ name?: string; value?: number; payload?: { countries_reporting?: number; years_reported?: number; gaps?: number } }>; label?: string | number }) {
  if (!active || !payload?.length) return null
  return <div className="chart-tooltip"><strong>{label}</strong>{payload.map((point) => <div key={point.name}>{point.name}: {typeof point.value === 'number' ? formatExact(point.value) : point.value}{point.payload?.countries_reporting !== undefined && <span> · {point.payload.countries_reporting} reporting</span>}{point.payload?.years_reported !== undefined && <span> · {point.payload.years_reported} years · {point.payload.gaps} gaps</span>}</div>)}</div>
}

export default App
