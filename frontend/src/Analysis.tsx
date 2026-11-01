import { useEffect, useMemo, useRef, useState } from 'react'
import { Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { api, type AnomalySummary, type AnalysisQuality, type AnalysisTrend, type CompareMultiRow, type CoverageDeep, type Decomposition, type Finding, type RateDistribution, type TopCountry } from './api'

function formatRate(value: number) {
  return value.toLocaleString('en', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
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

function PanelHeading({ eyebrow, title, caption }: { eyebrow: string; title: string; caption: string }) {
  return (
    <div className="panel-heading">
      <div>
        <p className="eyebrow">{eyebrow}</p>
        <h2>{title}</h2>
        <p className="panel-caption">{caption}</p>
      </div>
    </div>
  )
}

function ChartWindow({ eyebrow, title, caption, children }: { eyebrow: string; title: string; caption?: string; children: React.ReactNode }) {
  return (
    <div className="chart-window">
      <div className="panel-heading">
        <div>
          <p className="eyebrow">{eyebrow}</p>
          <h2>{title}</h2>
          {caption ? <p className="panel-caption">{caption}</p> : null}
        </div>
      </div>
      {children}
    </div>
  )
}

const TOC_SECTIONS = [
  { id: 'overview', label: 'Overview' },
  { id: 'data', label: 'Data foundation' },
  { id: 'top', label: 'Top countries' },
  { id: 'trend', label: 'Global trend' },
  { id: 'compare', label: 'Country comparison' },
  { id: 'anomalies', label: 'Anomalies' },
  { id: 'coverage', label: 'Coverage' },
  { id: 'findings', label: 'Findings' },
  { id: 'methods', label: 'Methods and context' },
]

export default function Analysis({ focusSection }: { focusSection?: string | null }) {
  const [from, setFrom] = useState(1950)
  const [to, setTo] = useState(2005)
  const [entity, setEntity] = useState<string>('Lithuania')
  const [compareEntities, setCompareEntities] = useState<string>('Lithuania')
  const [minYears, setMinYears] = useState(10)
  const [panelSeries, setPanelSeries] = useState<'all' | 'raw' | 'fixed' | 'wide' | 'median'>('all')
  const [activeSection, setActiveSection] = useState('overview')

  const [quality, setQuality] = useState<AnalysisQuality | null>(null)
  const [distribution, setDistribution] = useState<RateDistribution | null>(null)
  const [topCountries, setTopCountries] = useState<TopCountry[]>([])
  const [trend, setTrend] = useState<AnalysisTrend | null>(null)
  const [decomposition, setDecomposition] = useState<Decomposition | null>(null)
  const [compare, setCompare] = useState<CompareMultiRow[]>([])
  const [anomalySummary, setAnomalySummary] = useState<AnomalySummary | null>(null)
  const [coverage, setCoverage] = useState<CoverageDeep | null>(null)
  const [findings, setFindings] = useState<Finding[]>([])

  const trendRefHolder = useRef<HTMLDivElement | null>(null)
  const topRefHolder = useRef<HTMLDivElement | null>(null)
  const compareRefHolder = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    let active = true
    const load = async () => {
      try {
        const [q, d, top, tr, dec, cmp, an, cov, fnd] = await Promise.all([
          api.analysisQuality(),
          api.analysisDistribution(),
          api.analysisTopCountries(minYears, from, to),
          api.analysisTrend(from, to),
          api.analysisDecomposition(entity),
          api.analysisCompareMulti(compareEntities),
          api.analysisAnomalies(),
          api.analysisCoverage(),
          api.analysisFindings(),
        ])
        if (!active) return
        setQuality(q)
        setDistribution(d)
        setTopCountries(top)
        setTrend(tr)
        setDecomposition(dec)
        setCompare(cmp)
        setAnomalySummary(an)
        setCoverage(cov)
        setFindings(fnd)
      } catch {
        if (active) {
          setQuality(null)
          setDistribution(null)
          setTopCountries([])
          setTrend(null)
          setDecomposition(null)
          setCompare([])
          setAnomalySummary(null)
          setCoverage(null)
          setFindings([])
        }
      }
    }
    load()
    return () => { active = false }
  }, [from, to, entity, compareEntities, minYears])

  useEffect(() => {
    const onScroll = () => {
      const scrollPos = window.scrollY + 160
      let current = TOC_SECTIONS[0].id
      for (const section of TOC_SECTIONS) {
        const el = document.getElementById(section.id)
        if (el && el.offsetTop <= scrollPos) current = section.id
      }
      setActiveSection(current)
    }
    window.addEventListener('scroll', onScroll)
    onScroll()
    return () => window.removeEventListener('scroll', onScroll)
  }, [])

  useEffect(() => {
    if (focusSection) {
      const el = document.getElementById(focusSection)
      if (el) el.scrollIntoView({ behavior: 'smooth' })
    }
  }, [focusSection])

  useEffect(() => {
    const params = new URLSearchParams(window.location.search)
    const qFrom = Number(params.get('from'))
    const qTo = Number(params.get('to'))
    const qEntity = params.get('entity')
    const qCompare = params.get('compare')
    const qMinYears = Number(params.get('min_years'))
    setFrom(Number.isFinite(qFrom) ? Math.max(1950, Math.min(2005, qFrom)) : 1950)
    setTo(Number.isFinite(qTo) ? Math.max(1950, Math.min(2005, qTo)) : 2005)
    if (qEntity) setEntity(qEntity)
    if (qCompare) setCompareEntities(qCompare)
    if (Number.isFinite(qMinYears) && qMinYears >= 1) setMinYears(Math.min(56, Math.floor(qMinYears)))
  }, [])

  useEffect(() => {
    const params = new URLSearchParams()
    params.set('from', String(from))
    params.set('to', String(to))
    if (entity) params.set('entity', entity)
    if (compareEntities) params.set('compare', compareEntities)
    if (minYears) params.set('min_years', String(minYears))
    window.history.replaceState(null, '', `?${params.toString()}`)
  }, [from, to, entity, compareEntities, minYears])

  const trendChartData = useMemo(() => {
    if (!trend) return [] as Array<Record<string, string | number | null>>
    const fixed = new Map(trend.fixed_panel.map((row) => [row.year, row.avg_rate]))
    const wide = new Map(trend.wide_panel.map((row) => [row.year, row.avg_rate]))
    const median = new Map(trend.median.map((row) => [row.year, row.avg_rate]))
    return trend.yearly.map((row) => ({
      year: row.year,
      raw: row.avg_rate,
      fixed: fixed.get(row.year) ?? null,
      wide: wide.get(row.year) ?? null,
      median: median.get(row.year) ?? null,
      countries_reporting: row.countries_reporting,
    }))
  }, [trend])

  const peakRows = useMemo(() => {
    if (!trend) return { raw: null, fixed: null, wide: null, median: null }
    const pick = (rows: Array<{ year: number; avg_rate: number }> | undefined) => {
      if (!rows || !rows.length) return null
      const peak = rows.reduce((best, row) => (row.avg_rate > best.avg_rate ? row : best), rows[0])
      return { year: peak.year, avg_rate: peak.avg_rate }
    }
    return {
      raw: pick(trend.yearly),
      fixed: pick(trend.fixed_panel),
      wide: pick(trend.wide_panel),
      median: pick(trend.median),
    }
  }, [trend])

  if (!quality || !distribution || !trend) {
    return (
      <main id="main" className="dashboard">
        <section className="panel">
          <div className="panel-heading">
            <div>
              <h2>In-Depth Analysis</h2>
              <p className="panel-caption">Loading the expanded analytical view…</p>
            </div>
          </div>
        </section>
      </main>
    )
  }

  const summary = quality.summary
  const outliers = [...(distribution.outliers ?? [])].sort((a, b) => b.rate - a.rate).slice(0, 15)
  type FlaggedRow = { entity: string; year: number; change: number; z_score: number; zscore_flag: boolean; iqr_flag: boolean }
  const flaggedRows: FlaggedRow[] = (anomalySummary?.flagged_rows ?? []) as unknown as FlaggedRow[]

  return (
    <main id="main" className="dashboard">
      <section className="page-intro" aria-labelledby="analysis-title">
        <div className="intro-copy">
          <h1 id="analysis-title">In-Depth Analysis</h1>
          <p className="intro-description">A deeper, evidence-first read of the Global Suicide Rates dashboard: data quality, trends, comparisons, anomalies, and coverage with explicit caveats.</p>
        </div>
      </section>

      <nav className="toc" aria-label="In-depth analysis sections">
        <div className="toc-sticky">
          <p className="eyebrow">SECTIONS</p>
          <ul>
            {TOC_SECTIONS.map((section) => (
              <li key={section.id}>
                <a href={`#${section.id}`} className={activeSection === section.id ? 'toc-active' : undefined}>{section.label}</a>
              </li>
            ))}
          </ul>
        </div>
      </nav>

      <section id="overview" className="panel" aria-labelledby="overview-title">
        <PanelHeading eyebrow="A · OVERVIEW" title="Overview" caption="Purpose, framing, and the headline numbers" />
        <p>The in-depth analysis expands every dashboard objective with explicit evidence, calculation notes, caveats, and confidence context. It is descriptive only; no causal or predictive claims are made.</p>
        <div className="kpi-grid">
          <article className="kpi-card"><div className="kpi-label">Observation mean</div><div className="kpi-value">{formatRate(summary.mean)}</div><div className="kpi-unit">per 100,000 · across records</div></article>
          <article className="kpi-card"><div className="kpi-label">Median</div><div className="kpi-value">{formatRate(summary.median)}</div><div className="kpi-unit">per 100,000</div></article>
          <article className="kpi-card"><div className="kpi-label">Peak year</div><div className="kpi-value">{summary.global_peak_year}</div><div className="kpi-unit">{formatRate(summary.global_peak_avg_rate)} per 100,000</div></article>
          <article className="kpi-card"><div className="kpi-label">Top eligible country</div><div className="kpi-value kpi-country">{topCountries[0]?.entity ?? '—'}</div><div className="kpi-unit">{topCountries[0] ? `${formatRate(topCountries[0].avg_rate)} mean · ${topCountries[0].years_reported} yrs` : 'Requires 10+ observations'}</div></article>
        </div>
        <p className="panel-note">How to read this page: each objective pairs a short answer with visual evidence, calculation notes, caveats, and a link back to the dashboard panel. Headline figures are means of country-year observations, not world rates.</p>
      </section>

      <section className="panel" aria-labelledby="terms-title">
        <div className="panel-heading">
          <div>
            <p className="eyebrow">A · KEY TERMS</p>
            <h2 id="terms-title">Key terms and definitions</h2>
            <p className="panel-caption">Plain-language definitions for the statistics used in this analysis.</p>
          </div>
        </div>
        <div className="terms-grid">
          <div className="term-card">
            <p className="term-card-label">ISO</p>
            <p className="term-card-definition">ISO stands for the International Organization for Standardization, the body that maintains the global country coding system. In this dataset, every country entity is tagged with its ISO country code, a three-letter alpha-3 code such as <span className="term-value">LTU</span> for Lithuania, so rates from different sources can be matched reliably. The analysis recognizes 190 current ISO entities, plus six historical entities that use publisher-specific codes beginning with <span className="term-value">OWID_</span>.</p>
          </div>
          <div className="term-card">
            <p className="term-card-label">IQR</p>
            <p className="term-card-definition">The interquartile range (IQR) is a measure of statistical spread, calculated as the difference between the third quartile (Q3) and the first quartile (Q1). It describes the distance between the 25th and 75th percentiles of the observed values; here it is 9.88 per 100,000 for the dataset's suicide rates.</p>
          </div>
          <div className="term-card">
            <p className="term-card-label">IQR fences</p>
            <p className="term-card-definition">IQR fences are the outlier-detection bounds derived from the interquartile range using Tukey's method: a lower fence of Q1 - 1.5 × IQR and an upper fence of Q3 + 1.5 × IQR. Here the upper fence is 30.92 per 100,000, and any observed rate above it is flagged as a statistical outlier.</p>
          </div>
          <div className="term-card">
            <p className="term-card-label">Outliers</p>
            <p className="term-card-definition">An outlier is a value that falls outside a statistical fence. In this analysis, outliers are rates beyond the Tukey IQR fence, or year-over-year changes beyond the |z| &gt; 2 threshold. Eighty-two rates exceeded the upper IQR fence, with the largest value being 44.35 per 100,000 for Lithuania in 1996. Flagged outliers are retained rather than corrected, because a statistical outlier alone is not evidence of an invalid record.</p>
          </div>
          <div className="term-card">
            <p className="term-card-label">Confidence level</p>
            <p className="term-card-definition">The confidence level labels each finding in the findings register (for example, High) as a qualitative assessment of how strongly the descriptive evidence supports a statement, given caveats such as coverage gaps and retained outliers. It is not a statistical confidence interval on the estimate itself.</p>
          </div>
          <div className="term-card">
            <p className="term-card-label">Effect decomposition</p>
            <p className="term-card-definition">A year-over-year change in a mean rate is decomposed into two effects: the within-country effect, the average change among countries present in both years, and the composition effect, the change arising from shifts in the mix of reporting countries. The total change equals the sum of both: total change = within-country effect + composition effect. For example, a total change of <span className="term-value">0.47</span> may consist of a within-country effect of <span className="term-value">0.18</span> and a composition effect of <span className="term-value">0.29</span>.</p>
          </div>
        </div>
      </section>

      <section id="data" className="panel" aria-labelledby="data-title">
        <PanelHeading eyebrow="B · DATA FOUNDATION" title="Data foundation and quality" caption="Distribution, outliers, and integrity checks" />
        <p>Descriptive statistics computed from {quality.row_count.toLocaleString()} validated country-year records across {quality.entity_count} entities ({quality.iso_entity_count} current ISO entities plus {Object.keys(quality.former_state_entities ?? {}).length} former-state entities).</p>
        <div className="kpi-grid">
          <article className="kpi-card"><div className="kpi-label">Records</div><div className="kpi-value">{quality.row_count}</div><div className="kpi-unit">country-year observations</div></article>
          <article className="kpi-card"><div className="kpi-label">Entities</div><div className="kpi-value">{quality.entity_count}</div><div className="kpi-unit">with reported rates</div></article>
          <article className="kpi-card"><div className="kpi-label">IQR fences</div><div className="kpi-value">{formatRate(distribution.rate_iqr_fences[0])}</div><div className="kpi-unit">{formatRate(distribution.rate_iqr_fences[1])} upper fence</div></article>
          <article className="kpi-card"><div className="kpi-label">Outliers</div><div className="kpi-value">{quality.quality.rate_outlier_count}</div><div className="kpi-unit">above Tukey fences</div></article>
        </div>
        <ChartWindow eyebrow="B · DISTRIBUTION" title="Rate distribution" caption="Histogram of validated country-year rates per 100,000">
          <div className="chart-wrap" ref={(node) => { trendRefHolder.current = node }}>
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={distribution.histogram} margin={{ top: 10, right: 10, bottom: 0, left: -20 }}>
                <CartesianGrid strokeDasharray="3 5" vertical={false} />
                <XAxis dataKey="range" />
                <YAxis allowDecimals={false} />
                <Tooltip />
                <Bar dataKey="count" name="Records" fill="var(--accent)" />
              </BarChart>
            </ResponsiveContainer>
          </div>
          <div className="chart-explanation">
            <p>The histogram bins all {quality.row_count.toLocaleString()} validated country-year suicide rates into fixed ranges, measured per 100,000 people. Most observations fall in the 5–15 range (820 records, about 29% of all data), with progressively fewer records in the higher bands.</p>
            <p>The long right tail is driven by high observed rates; 82 rates exceed the Tukey upper fence of 30.92 per 100,000, and the largest value is 44.35 for Lithuania in 1996. The fences are derived from the interquartile range (Q1 = 6.22, Q3 = 16.10, IQR = 9.88; upper fence = Q3 + 1.5 × IQR = 30.92). Flagged outliers are retained rather than corrected, because a statistical outlier alone is not evidence of an invalid record.</p>
          </div>
        </ChartWindow>
        <div className="table-scroll">
          <table>
            <caption className="sr-only">Rates above Tukey outlier fences</caption>
            <thead><tr><th scope="col">Entity</th><th scope="col">Code</th><th scope="col">Year</th><th scope="col">Rate</th></tr></thead>
            <tbody>
              {outliers.map((row) => (
                <tr key={`${row.entity}-${row.year}`}><td>{row.entity}</td><td>{row.code}</td><td>{row.year}</td><td>{formatRate(row.rate)}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section id="top" className="panel" aria-labelledby="top-title">
        <div className="panel-controls">
          <label htmlFor="min-years">Minimum years required</label>
          <select id="min-years" value={minYears} onChange={(event) => setMinYears(Number(event.target.value))}>
            {[1, 3, 5, 10, 20, 56].map((value) => <option key={value} value={value}>{value}</option>)}
          </select>
        </div>
        <ChartWindow eyebrow="C · OBJECTIVE 1 + Q2" title="Top countries by historical mean" caption="Coverage-qualified ranking with minimum-years sensitivity">
          <div className="chart-wrap" ref={(node) => { topRefHolder.current = node }}>
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={topCountries} layout="vertical" margin={{ top: 0, right: 42, bottom: 0, left: 10 }}>
                <CartesianGrid strokeDasharray="3 5" horizontal={false} />
                <XAxis type="number" domain={[0, 'auto']} />
                <YAxis type="category" dataKey="entity" width={122} tick={{ fontSize: 12 }} />
                <Tooltip />
                <Bar dataKey="avg_rate" name="Mean rate" fill="var(--accent)" radius={[0, 5, 5, 0]} barSize={18} />
              </BarChart>
            </ResponsiveContainer>
          </div>
          <ExportButtons rows={topCountries} name="analysis-top" chartRef={topRefHolder} />
          <div className="chart-explanation">
            <p>The horizontal bar chart ranks countries by their historical mean suicide rate, computed as the mean of country-year observations. With the default minimum of 10 observed years, Lithuania ranks first at 35.13 per 100,000 across 23 observations, ahead of Russia (30.77, n = 24) and Hungary (29.85, n = 51).</p>
            <p>The ranking is coverage-qualified: without the minimum-years rule, short series such as Guyana (3 observations, 30.85 mean) would enter the ranking, so the rule keeps sparse series from dominating. The full ranked list is shown in the table below.</p>
          </div>
        </ChartWindow>
        <div className="table-scroll">
          <table>
            <caption className="sr-only">Top countries by mean rate</caption>
            <thead><tr><th scope="col">Rank</th><th scope="col">Entity</th><th scope="col">Mean rate</th><th scope="col">Years reported</th></tr></thead>
            <tbody>
              {topCountries.map((row, index) => (
                <tr key={row.entity}><td>{index + 1}</td><td>{row.entity}</td><td>{formatRate(row.avg_rate)}</td><td>{row.years_reported}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section id="trend" className="panel" aria-labelledby="trend-title">
        <div className="panel-controls">
          <label htmlFor="panel-series">Compare series</label>
          <select id="panel-series" value={panelSeries} onChange={(event) => setPanelSeries(event.target.value as typeof panelSeries)}>
            <option value="all">All series</option>
            <option value="raw">Raw annual mean</option>
            <option value="fixed">Fixed panel</option>
            <option value="wide">Wider panel (&ge; 40 years)</option>
            <option value="median">Annual median</option>
          </select>
        </div>
        <ChartWindow eyebrow="D · OBJECTIVE 2 + Q1" title="Global trend" caption="Raw mean, fixed panel, wider panel, and median">
          <div className="chart-wrap" ref={(node) => { trendRefHolder.current = node }}>
          <ResponsiveContainer width="100%" height="100%">
            {panelSeries === 'all' ? (
              <LineChart data={trendChartData} margin={{ top: 14, right: 18, bottom: 4, left: 0 }}>
                <CartesianGrid strokeDasharray="3 5" vertical={false} />
                <XAxis dataKey="year" type="number" domain={['dataMin', 'dataMax']} tickCount={8} />
                <YAxis domain={[0, 'auto']} width={48} />
                <Tooltip />
                <Legend />
                <Line type="monotone" dataKey="raw" name="Raw mean" stroke="var(--accent)" strokeWidth={3} dot={false} />
                <Line type="monotone" dataKey="fixed" name="Fixed panel" stroke="var(--secondary)" strokeWidth={2} dot={false} strokeDasharray="5 4" />
                <Line type="monotone" dataKey="wide" name="Wide panel" stroke="var(--accent-dark)" strokeWidth={2} dot={false} />
                <Line type="monotone" dataKey="median" name="Median" stroke="#8a6fb8" strokeWidth={2} dot={false} strokeDasharray="2 3" />
              </LineChart>
            ) : (
              <LineChart data={trendChartData} margin={{ top: 14, right: 18, bottom: 4, left: 0 }}>
                <CartesianGrid strokeDasharray="3 5" vertical={false} />
                <XAxis dataKey="year" type="number" domain={['dataMin', 'dataMax']} tickCount={8} />
                <YAxis domain={[0, 'auto']} width={48} />
                <Tooltip />
                <Legend />
                <Line type="monotone" dataKey={panelSeries === 'raw' ? 'raw' : panelSeries === 'fixed' ? 'fixed' : panelSeries === 'wide' ? 'wide' : 'median'} name={panelSeries} stroke="var(--accent)" strokeWidth={3} dot={false} />
              </LineChart>
            )}
          </ResponsiveContainer>
        </div>
        <ExportButtons rows={trend.yearly} name="analysis-trend" chartRef={trendRefHolder} />
          <div className="chart-explanation">
            <p>The annual mean rate across reporting entities fluctuates over 1950–2005; the unweighted yearly mean peaks at 14.76 per 100,000 in 1982, when 52 entities reported.</p>
            <p>The chart overlays four series — raw mean, fixed eight-entity panel, wider panel, and annual median — so the same years can be compared. Because the set of reporting entities shifts over time, raw averages can move with coverage; the reporting counts chart below shows coverage rising from 10 entities in 1950 to 191 in 2004–2005.</p>
          </div>
          <div className="chart-explanation">
            <p><strong>Raw mean</strong> is the simple, unweighted average of every entity that reported a rate in that year, so it reflects both real changes and changes in who is reporting.</p>
            <p><strong>Fixed panel</strong> averages only the eight entities that report in every single year from 1950 to 2005 (Australia, Canada, Ireland, Japan, Netherlands, New Zealand, United Kingdom, United States), giving a stable like-for-like comparison.</p>
            <p><strong>Wider panel</strong> averages entities with at least 40 years of observations, a middle ground between the raw mean and the strict fixed panel.</p>
            <p><strong>Annual median</strong> is the middle value of that year's reported rates, which is less affected by extreme outliers than the mean.</p>
            <p>In the comparison table, <strong>Global mean</strong> is the unweighted average of all reporters that year, while <strong>Panel mean</strong> is the average of the fixed eight-entity panel for that same year. The panel mean is usually lower and smoother than the global mean because it excludes the high-coverage, high-rate countries added in later years.</p>
          </div>
        </ChartWindow>
        <ChartWindow eyebrow="D · OBJECTIVE 2 + Q1" title="Reporting counts" caption="Entities reporting per year">
          <div className="chart-wrap" ref={(node) => { trendRefHolder.current = node }}>
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={trend.reporting_counts ?? []} margin={{ top: 10, right: 10, bottom: 0, left: -20 }}>
              <CartesianGrid strokeDasharray="3 5" vertical={false} />
              <XAxis dataKey="year" type="number" domain={['dataMin', 'dataMax']} padding={{ left: 0, right: 0 }} />
              <YAxis allowDecimals={false} />
              <Tooltip />
              <Bar dataKey="countries_reporting" name="Countries reporting" fill="var(--secondary)" />
            </BarChart>
          </ResponsiveContainer>
        </div>
          <div className="chart-explanation">
            <p>The bar chart shows how many entities reported a suicide rate in each year, from 10 in 1950 to 191 in 2004 and 2005. Coverage is uneven and jumps sharply in nearby years — for example, 62 entities in 2001, 190 in 2002, and 55 in 2003 — meaning annual averages can shift even when underlying rates do not.</p>
          </div>
        </ChartWindow>
        <ChartWindow eyebrow="D · OBJECTIVE 2 + Q1" title="Reporting counts (Part 2): Country vs. Global & Panel baselines" caption="Selected entity against global and fixed-panel baselines">
          <div className="table-scroll">
            <table>
              <caption className="sr-only">Country comparison rows</caption>
              <thead><tr><th scope="col">Entity</th><th scope="col">Year</th><th scope="col">Country rate</th><th scope="col">Global mean</th><th scope="col">Panel mean</th></tr></thead>
              <tbody>
                {compare.filter((row) => row.entity === compareEntities).slice(0, 60).map((row) => (
                  <tr key={`${row.entity}-${row.year}`}><td>{row.entity}</td><td>{row.year}</td><td>{formatRate(row.country_rate)}</td><td>{formatRate(row.global_avg)}</td><td>{formatRate(row.panel_avg)}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="chart-explanation">
            <p>The table lists, for each year the selected country reported a rate, that country's rate alongside the global mean and the fixed-panel mean for the same year. It is the detailed record behind the comparison chart, so you can see year by year whether the country sits above or below the global and panel baselines.</p>
            <p>Lithuania is featured here because it ranks #1 among eligible countries by historical mean rate. Global mean is the unweighted average of all reporters that year, while Panel mean is the average of the fixed eight-entity panel, a stable like-for-like benchmark. A country consistently above both lines carries a higher rate than typical, and crossings or divergences over time reveal when its trajectory separated from the broader pattern.</p>
          </div>
        </ChartWindow>
        <ChartWindow eyebrow="D · DECOMPOSITION" title="Lithuania year-over-year changes" caption="Total change split into within-country and composition effects">
          {decomposition && decomposition.pairs.length > 0 ? (
            decomposition.pairs.map((pair) => (
              <p className="panel-note" key={`${pair.from_year}-${pair.to_year}`}>
                {decomposition.entity}: {pair.from_year} to {pair.to_year} — total change {formatRate(pair.total_change)} = within-country effect {formatRate(pair.within_effect)} + composition effect {formatRate(pair.composition_effect)}.
              </p>
            ))
          ) : null}
          <div className="chart-explanation">
            <p>Each line decomposes a year-over-year change in Lithuania's rate into two parts: the within-country effect (the average change among entities present in both years) and the composition effect (the change arising from shifts in which countries are reporting). The total change equals the sum of the two.</p>
          </div>
        </ChartWindow>
        <div className="table-scroll">
          <table>
            <caption className="sr-only">Peak year sensitivity by series</caption>
            <thead><tr><th scope="col">Series</th><th scope="col">Peak year</th><th scope="col">Peak mean</th></tr></thead>
            <tbody>
              <tr><td>Raw annual mean</td><td>{peakRows.raw?.year ?? '—'}</td><td>{peakRows.raw ? formatRate(peakRows.raw.avg_rate) : '—'}</td></tr>
              <tr><td>Fixed panel</td><td>{peakRows.fixed?.year ?? '—'}</td><td>{peakRows.fixed ? formatRate(peakRows.fixed.avg_rate) : '—'}</td></tr>
              <tr><td>Wider panel (&ge; 40 years)</td><td>{peakRows.wide?.year ?? '—'}</td><td>{peakRows.wide ? formatRate(peakRows.wide.avg_rate) : '—'}</td></tr>
              <tr><td>Annual median</td><td>{peakRows.median?.year ?? '—'}</td><td>{peakRows.median ? formatRate(peakRows.median.avg_rate) : '—'}</td></tr>
            </tbody>
          </table>
        </div>
        <div className="chart-explanation">
          <p>The apparent peak year of the global suicide rate depends heavily on which series and coverage rule you use. The raw mean peaks in 1982 at 14.76 per 100,000, the fixed eight-entity panel peaks in 1998 at 12.21, the wider panel peaks in 1984 at 13.01, and the annual median peaks in 1988 at 13.64. No single year is "the" peak — each series tells a different story about when rates were highest.</p>
          <p>This shows that the peak is not a fixed fact but is sensitive to coverage and method. The raw 1982 peak reflects the particular mix of 52 reporting entities that year, while the fixed panel's later 1998 peak reflects a stable, complete-coverage subset. Comparing these series helps separate a genuine rise in rates from an artifact of changing who reports.</p>
        </div>
      </section>

      <section id="compare" className="panel" aria-labelledby="compare-title">
        <ChartWindow eyebrow="E · OBJECTIVE 3 + Q3" title="Country and global baseline" caption="Selected entities against global and fixed-panel baselines">
          <div className="chart-wrap" ref={(node) => { compareRefHolder.current = node }}>
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={compare} margin={{ top: 12, right: 10, bottom: 4, left: 0 }}>
              <CartesianGrid strokeDasharray="3 5" vertical={false} />
              <XAxis dataKey="year" type="number" domain={['dataMin', 'dataMax']} tickCount={6} />
              <YAxis domain={[0, 'auto']} width={42} />
              <Tooltip />
              <Legend />
              <Line type="monotone" dataKey="country_rate" name={compare[0]?.entity ?? 'Country'} stroke="var(--accent)" strokeWidth={2.5} dot={false} />
              <Line type="monotone" dataKey="global_avg" name="Global mean" stroke="var(--secondary)" strokeWidth={2} dot={false} strokeDasharray="5 4" />
              <Line type="monotone" dataKey="panel_avg" name="Fixed panel" stroke="#8a6fb8" strokeWidth={2} dot={false} strokeDasharray="2 3" />
            </LineChart>
          </ResponsiveContainer>
        </div>
          <div className="chart-explanation">
            <p>The line chart compares the selected country against the global mean and the fixed-panel mean for each year the country reported.</p>
            <p>The global mean is the unweighted average among entities reporting in that year, while the fixed panel is the small set of countries reporting every year from 1950 through 2005. Only years with a reported value for the selected country are plotted; missing years are not interpolated.</p>
          </div>
        </ChartWindow>
      </section>
      <section id="anomalies" className="panel" aria-labelledby="anomalies-title">
        <PanelHeading eyebrow="F · OBJECTIVE 4" title="Unusual annual changes" caption="Statistical flags with explicit caveats" />
        <div className="kpi-grid">
          <article className="kpi-card"><div className="kpi-label">Consecutive changes</div><div className="kpi-value">{anomalySummary?.consecutive_changes ?? 0}</div><div className="kpi-unit">year pairs evaluated</div></article>
          <article className="kpi-card"><div className="kpi-label">|z| &gt; 2 flags</div><div className="kpi-value">{anomalySummary?.zscore_count ?? 0}</div><div className="kpi-unit">z-score method</div></article>
          <article className="kpi-card"><div className="kpi-label">1.5xIQR flags</div><div className="kpi-value">{anomalySummary?.iqr_count ?? 0}</div><div className="kpi-unit">IQR method</div></article>
          <article className="kpi-card"><div className="kpi-label">Both methods</div><div className="kpi-value">{anomalySummary?.both_count ?? 0}</div><div className="kpi-unit">overlap count</div></article>
        </div>
        <div className="table-scroll">
          <table>
            <caption className="sr-only">Flagged anomalies</caption>
            <thead><tr><th scope="col">Entity</th><th scope="col">Year</th><th scope="col">Change</th><th scope="col">z-score</th><th scope="col">Z-score flag</th><th scope="col">IQR flag</th></tr></thead>
            <tbody>
              {flaggedRows.map((row) => (
                <tr key={`${row.entity}-${row.year}`}>
                  <td>{row.entity}</td>
                  <td>{row.year}</td>
                  <td>{row.change > 0 ? '+' : ''}{formatRate(row.change)}</td>
                  <td>{row.z_score.toFixed(2)}</td>
                  <td><span className={row.zscore_flag ? 'flag-badge flag-badge--yes' : 'flag-badge flag-badge--no'} title={row.zscore_flag ? 'Flagged by z-score method' : 'Not flagged'}>{row.zscore_flag ? 'Flagged' : '—'}</span></td>
                  <td><span className={row.iqr_flag ? 'flag-badge flag-badge--yes' : 'flag-badge flag-badge--no'} title={row.iqr_flag ? 'Flagged by IQR method' : 'Not flagged'}>{row.iqr_flag ? 'Flagged' : '—'}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="chart-explanation">
          <p>These rows list year-over-year changes in a country's suicide rate that were flagged as statistically unusual. Each row is a consecutive-year pair for one entity, with the signed change, its z-score, and which screening rules it tripped. A change is flagged by the z-score method when its absolute z-score exceeds 2 (more than two standard deviations from the pooled mean of all changes), and by the IQR method when it falls outside the Tukey fences built from the interquartile range of all changes.</p>
          <p>The KPIs summarize the screening: how many consecutive-year pairs were evaluated, how many were flagged by each method, and how many were flagged by both. These are descriptive screening flags, not proof of data errors or explanations of causes — an unusual change may reflect a real shift, a reporting change, or noise, and only the data themselves can distinguish these.</p>
        </div>
      </section>

      <section id="coverage" className="panel" aria-labelledby="coverage-title">
        <PanelHeading eyebrow="G · OBJECTIVE 5" title="Reporting coverage" caption="Coverage tiers, gaps, and entity counts" />
        <div className="kpi-grid">
          <article className="kpi-card"><div className="kpi-label">Entities tracked</div><div className="kpi-value">{coverage ? quality.entity_count : 0}</div><div className="kpi-unit">in coverage report</div></article>
          <article className="kpi-card"><div className="kpi-label">Years in range</div><div className="kpi-value">{to - from + 1}</div><div className="kpi-unit">{from}–{to}</div></article>
          <article className="kpi-card"><div className="kpi-label">Coverage rows</div><div className="kpi-value">{coverage?.coverage.length ?? 0}</div><div className="kpi-unit">entities listed</div></article>
          <article className="kpi-card"><div className="kpi-label">Gaps (observed span)</div><div className="kpi-value">{coverage?.coverage.reduce((sum, row) => sum + (row.gaps ?? 0), 0) ?? 0}</div><div className="kpi-unit">missing year slots</div></article>
        </div>
        <div className="table-scroll">
          <table>
            <caption className="sr-only">Coverage rows</caption>
            <thead><tr><th scope="col">Entity</th><th scope="col">Years reported</th><th scope="col">First year</th><th scope="col">Last year</th><th scope="col">Gaps</th></tr></thead>
            <tbody>
              {(coverage?.coverage ?? []).slice(0, 40).map((row) => (
                <tr key={row.entity}><td>{row.entity}</td><td>{row.years_reported}</td><td>{row.first_year ?? '—'}</td><td>{row.last_year ?? '—'}</td><td>{row.gaps ?? 0}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="chart-explanation">
          <p>Reporting coverage describes how completely each entity is observed across the period. Each row shows one entity, how many years it reported, its first and last reporting year, and the gaps — years missing between its first and last report. The KPIs summarize how many entities are tracked, how many years the selected range spans, how many entities appear in the report, and the total missing year slots within observed spans.</p>
          <p>Uneven coverage matters because the annual averages are unweighted means of whoever reported that year. An entity added or dropped between years changes the composition of the average, so a rise or fall in the yearly mean can reflect changing coverage as much as changing rates. Entities with fewer than the required years are excluded from rankings, and missing years are never interpolated.</p>
        </div>
      </section>

      <section id="findings" className="panel" aria-labelledby="findings-title">
        <PanelHeading eyebrow="H · FINDINGS REGISTER" title="Findings register" caption="Numbered findings with caveats and confidence" />
        <p className="panel-note">The findings register is a summary of the key patterns across all charts on this page; it aligns with the findings and evidence presented in each chart's in-depth explanation above.</p>
        <div className="table-scroll">
          <table>
            <caption className="sr-only">Analysis findings register</caption>
            <thead><tr><th scope="col">No.</th><th scope="col">Finding</th><th scope="col">Detail</th><th scope="col">Caveat</th><th scope="col">Confidence</th></tr></thead>
            <tbody>
              {findings.map((finding) => (
                <tr key={finding.number}>
                  <td>{finding.number}</td>
                  <td>{finding.title}</td>
                  <td>{finding.detail}</td>
                  <td>{finding.caveat}</td>
                  <td>{finding.confidence}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section id="methods" className="panel" aria-labelledby="methods-title">
        <PanelHeading eyebrow="I · METHODS AND CONTEXT" title="Methods, limitations, context" caption="How the numbers are produced and how to interpret them" />
        <div className="about-content">
          <p><strong>Source:</strong> SDG-3 suicide rates by country, age-adjusted suicides per 100,000 people. Original dataset: <a href="https://github.com/liadkeller/Suicides-Data-Analysis-DSE200X/blob/master/suicide-rates-by-country.csv" target="_blank" rel="noreferrer">Suicides Data Analysis (liadkeller/Suicides-Data-Analysis-DSE200X)<span className="sr-only"> (opens in a new tab)</span></a>. Analysis accessed October 23, 2026. Data range: 1950–2005.</p>
          <p><strong>Method:</strong> Yearly averages are unweighted means of entities with an observation in that year. Country ranking requires at least 10 observations; six former-state entities with publisher-specific codes remain available in historical views but are not ranked as current countries.</p>
          <p><strong>Limitations:</strong> Data ends in 2005; country coverage and years reported are uneven. Outliers are retained. The data are descriptive only; no causal or predictive claims are made. Correlation does not establish causation.</p>
          <p><strong>Safe messaging:</strong> If you or someone you know needs support, contact a local crisis service. <a href="https://findahelpline.com/" target="_blank" rel="noreferrer">Find international crisis resources at findahelpline.com<span className="sr-only"> (opens in a new tab)</span></a>.</p>
        </div>
      </section>
    </main>
  )
}
