import { useEffect, useMemo, useRef, useState } from 'react'
import { Bar, BarChart, CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { api, type AnomalySummary, type AnalysisFlaggedRow, type AnalysisQuality, type AnalysisTrend, type CompareMultiRow, type CoverageDeep, type Decomposition, type Finding, type RateDistribution, type TopCountry } from './api'

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

function InterpretationBox({ children }: { children: React.ReactNode }) {
  return (
    <aside className="interpretation-box" role="note" aria-label="Interpretation">
      <div className="interpretation-badge">
        <span className="interpretation-bubble" aria-hidden="true">i</span>
        <strong>Interpretation</strong>
      </div>
      <p>{children}</p>
    </aside>
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
  const [paramsInitialized, setParamsInitialized] = useState(false)

  const [quality, setQuality] = useState<AnalysisQuality | null>(null)
  const [distribution, setDistribution] = useState<RateDistribution | null>(null)
  const [topCountries, setTopCountries] = useState<TopCountry[]>([])
  const [trend, setTrend] = useState<AnalysisTrend | null>(null)
  const [decomposition, setDecomposition] = useState<Decomposition | null>(null)
  const [compare, setCompare] = useState<CompareMultiRow[]>([])
  const [anomalySummary, setAnomalySummary] = useState<AnomalySummary | null>(null)
  const [coverage, setCoverage] = useState<CoverageDeep | null>(null)
  const [findings, setFindings] = useState<Finding[]>([])
  const [loadErrors, setLoadErrors] = useState<string[]>([])
  const [loading, setLoading] = useState(true)

  const trendRefHolder = useRef<HTMLDivElement | null>(null)
  const topRefHolder = useRef<HTMLDivElement | null>(null)
  const compareRefHolder = useRef<HTMLDivElement | null>(null)

  useEffect(() => {
    if (!paramsInitialized) return
    let active = true
    setLoading(true)
    const load = async () => {
      const results = await Promise.allSettled([
        api.analysisQuality(),
        api.analysisDistribution(),
        api.analysisTopCountries(minYears, 1950, 2005),
        api.analysisTrend(from, to),
        api.analysisDecomposition(entity),
        api.analysisCompareMulti(compareEntities),
        api.analysisAnomalies(),
        api.analysisCoverage(),
        api.analysisFindings(),
      ])
      if (!active) return
      const [q, d, top, tr, dec, cmp, an, cov, fnd] = results
      setQuality(q.status === 'fulfilled' ? q.value : null)
      setDistribution(d.status === 'fulfilled' ? d.value : null)
      setTopCountries(top.status === 'fulfilled' ? top.value : [])
      setTrend(tr.status === 'fulfilled' ? tr.value : null)
      setDecomposition(dec.status === 'fulfilled' ? dec.value : null)
      setCompare(cmp.status === 'fulfilled' ? cmp.value : [])
      setAnomalySummary(an.status === 'fulfilled' ? an.value : null)
      setCoverage(cov.status === 'fulfilled' ? cov.value : null)
      setFindings(fnd.status === 'fulfilled' ? fnd.value : [])
      const names = ['quality', 'distribution', 'top countries', 'trend', 'decomposition', 'comparison', 'anomalies', 'coverage', 'findings']
      setLoadErrors(results.flatMap((result, index) => result.status === 'rejected'
        ? [`${names[index]}: ${result.reason instanceof Error ? result.reason.message : String(result.reason)}`]
        : []))
      setLoading(false)
    }
    load()
    return () => { active = false }
  }, [from, to, entity, compareEntities, minYears, paramsInitialized])

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
    const parseYear = (key: string, fallback: number) => {
      const raw = params.get(key)
      const value = raw === null ? fallback : Number(raw)
      return Number.isInteger(value) ? Math.max(1950, Math.min(2005, value)) : fallback
    }
    const qFrom = parseYear('from', 1950)
    const qTo = parseYear('to', 2005)
    const qEntity = params.get('entity')
    const qCompare = params.get('compare')
    const qMinYears = Number(params.get('min_years'))
    if (qFrom <= qTo) {
      setFrom(qFrom)
      setTo(qTo)
    } else {
      setFrom(1950)
      setTo(2005)
    }
    if (qEntity) setEntity(qEntity)
    if (qCompare) setCompareEntities(qCompare)
    if (Number.isFinite(qMinYears) && qMinYears >= 1) setMinYears(Math.min(56, Math.floor(qMinYears)))
    setParamsInitialized(true)
  }, [])

  useEffect(() => {
    if (!paramsInitialized) return
    const params = new URLSearchParams()
    params.set('from', String(from))
    params.set('to', String(to))
    if (entity) params.set('entity', entity)
    if (compareEntities) params.set('compare', compareEntities)
    if (minYears) params.set('min_years', String(minYears))
    window.history.replaceState(null, '', `?${params.toString()}`)
  }, [from, to, entity, compareEntities, minYears, paramsInitialized])

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
  const trendYearDomain: [number, number] | ['dataMin', 'dataMax'] = trendChartData.length === 1
    ? [Number(trendChartData[0].year) - 1, Number(trendChartData[0].year) + 1]
    : ['dataMin', 'dataMax']
  const reportingChartData = trend?.reporting_counts ?? []

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
              <p className="panel-caption">{loading ? 'Loading the expanded analytical view…' : 'Some required analysis data could not be loaded.'}</p>
            </div>
          </div>
          {loadErrors.length > 0 && <div role="alert" className="error-banner"><strong>API loading errors</strong><ul>{loadErrors.map((error) => <li key={error}>{error}</li>)}</ul></div>}
        </section>
      </main>
    )
  }

  const summary = quality.summary
  const outliers = [...(distribution.outliers ?? [])].sort((a, b) => b.rate - a.rate).slice(0, 15)
  const flaggedRows: AnalysisFlaggedRow[] = anomalySummary?.flagged_rows ?? []
  const topCountry = topCountries[0]
  const outlierCounts = distribution.outliers.reduce<Record<string, number>>((counts, row) => {
    counts[row.entity] = (counts[row.entity] ?? 0) + 1
    return counts
  }, {})
  const topOutlierCountries = Object.entries(outlierCounts).sort((a, b) => b[1] - a[1]).slice(0, 3)
  const topThreeOutlierShare = distribution.outliers.length
    ? topOutlierCountries.reduce((sum, [, count]) => sum + count, 0) / distribution.outliers.length
    : 0
  const histogramFiveToTen = distribution.histogram.find((bin) => bin.range === '5–10')?.count ?? 0
  const histogramTenToFifteen = distribution.histogram.find((bin) => bin.range === '10–15')?.count ?? 0
  const changeFlagCounts = flaggedRows.filter((row) => row.zscore_flag).reduce<Record<string, number>>((counts, row) => {
    counts[row.entity] = (counts[row.entity] ?? 0) + 1
    return counts
  }, {})
  const topChangeFlagCountries = Object.entries(changeFlagCounts).sort((a, b) => b[1] - a[1]).slice(0, 3)
  const topThreeChangeFlagShare = anomalySummary?.zscore_count
    ? topChangeFlagCountries.reduce((sum, [, count]) => sum + count, 0) / anomalySummary.zscore_count
    : 0
  const selectedComparison = compare.filter((row) => row.entity === compareEntities && row.year >= from && row.year <= to)
  const bothBaselineShare = selectedComparison.length
    ? selectedComparison.filter((row) => row.country_rate > row.global_avg && row.country_rate > row.panel_avg).length / selectedComparison.length
    : 0
  const globalGaps = selectedComparison.map((row) => row.country_rate - row.global_avg)
  const panelGaps = selectedComparison.map((row) => row.country_rate - row.panel_avg)
  const gapRange = (gaps: number[]) => gaps.length
    ? `${formatRate(Math.min(...gaps))} to ${formatRate(Math.max(...gaps))}`
    : 'no observed years'
  const reportingCounts = trend.reporting_counts.map((row) => row.countries_reporting)
  const decompositionExample = decomposition?.pairs.find((pair) => pair.from_year === 2002 && pair.to_year === 2003)
    ?? decomposition?.pairs.reduce<typeof decomposition.pairs[number] | undefined>(
      (largest, pair) => !largest || Math.abs(pair.composition_effect) > Math.abs(largest.composition_effect) ? pair : largest,
      undefined,
    )
  const coverageComplete = coverage?.coverage.filter((row) => row.years_reported === 56).length ?? 0
  const coverageSparse = coverage?.coverage.filter((row) => row.years_reported <= 3).length ?? 0

  return (
    <main id="main" className="dashboard">
      <section className="page-intro" aria-labelledby="analysis-title">
        <div className="intro-copy">
          <h1 id="analysis-title">In-Depth Analysis</h1>
          <p className="intro-description">A deeper, evidence-first read of the Global Suicide Rates dashboard: data quality, trends, comparisons, anomalies, and coverage with explicit caveats.</p>
        </div>
      </section>
      {loadErrors.length > 0 && <div role="alert" className="error-banner"><strong>Some analysis sections could not load</strong><ul>{loadErrors.map((error) => <li key={error}>{error}</li>)}</ul></div>}

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
          <article className="kpi-card"><div className="kpi-label">Top eligible country</div><div className="kpi-value kpi-country">{topCountries[0]?.entity ?? '—'}</div><div className="kpi-unit">{topCountries[0] ? `${formatRate(topCountries[0].avg_rate)} mean · ${topCountries[0].years_reported} yr` : 'Requires 10+ observations'}</div></article>
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
            <p className="term-card-definition">ISO stands for the International Organization for Standardization, the body that maintains the global country coding system. The dataset includes 190 current ISO alpha-3 codes, such as <span className="term-value">LTU</span> for Lithuania, plus six historical entities whose publisher-specific codes begin with <span className="term-value">OWID_</span>; those six are not ISO codes.</p>
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
            <p className="term-card-definition">A change in the global mean is decomposed into the within-country effect, the average rate change among entities present at both endpoints, and the composition effect, the residual from changes in reporting composition. The total global-mean change equals within-country effect + composition effect. This describes the global mean, not Lithuania's own rate.</p>
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
        <InterpretationBox>
          The CSV contains {quality.quality.null_cells} null cells, {quality.quality.duplicate_entity_year_rows} duplicate entity-year rows, {quality.quality.invalid_codes} invalid codes, and {quality.quality.non_country_aggregates.length} non-country aggregates. Its {quality.entity_count} entities use {quality.iso_entity_count} ISO alpha-3 codes and {Object.keys(quality.former_state_entities ?? {}).length} publisher-specific historical codes. No records are removed for statistical extremity.
        </InterpretationBox>
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
            <p>The histogram bins all {quality.row_count.toLocaleString()} validated country-year suicide rates into fixed ranges, measured per 100,000 people. The 5–10 bin contains {histogramFiveToTen.toLocaleString()} observations ({(histogramFiveToTen / quality.row_count * 100).toFixed(1)}%); the combined 5–15 range contains {(histogramFiveToTen + histogramTenToFifteen).toLocaleString()} ({((histogramFiveToTen + histogramTenToFifteen) / quality.row_count * 100).toFixed(1)}%).</p>
            <p>The long right tail includes {distribution.outliers.length} values above the Tukey upper fence of {formatRate(distribution.rate_iqr_fences[1])} per 100,000; the maximum is {formatRate(summary.max)} for Lithuania in 1996. The fences use linear-interpolated quartiles (Q1 = {formatRate(summary.q1)}, Q3 = {formatRate(summary.q3)}; IQR = {formatRate(summary.q3 - summary.q1)}). Flagged outliers are retained because a statistical outlier alone is not evidence of an invalid record.</p>
          </div>
          <InterpretationBox>
            The 5–10 rate band is the largest single bin, while the combined 5–15 interval contains {(histogramFiveToTen + histogramTenToFifteen).toLocaleString()} of {quality.row_count.toLocaleString()} observations. The upper fence flags {distribution.outliers.length} rates across {Object.keys(outlierCounts).length} entities; {topOutlierCountries.map(([name, count]) => `${name} (${count})`).join(', ')} account for {(topThreeOutlierShare * 100).toFixed(1)}% of them, so the high tail is concentrated rather than broadly distributed. These are statistical flags, not invalid records by themselves.
          </InterpretationBox>
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
        <ChartWindow eyebrow="C · OBJECTIVE 1 + Q2" title="Top countries by historical mean" caption={`Historical period 1950–2005 · at least ${minYears} reported years`}>
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
            <p>The horizontal bar chart ranks current ISO-coded entities by their historical mean from 1950–2005. With a minimum of {minYears} reported years, {topCountries.slice(0, 3).map((row) => `${row.entity} (${formatRate(row.avg_rate)}, n=${row.years_reported})`).join(', ')} are the top entries.</p>
            <p>The minimum-years threshold limits the influence of sparse series; each row reports its observation count so coverage can be considered alongside the mean. This is a descriptive ranking, not a judgment about people, health systems, or policy performance.</p>
          </div>
          <InterpretationBox>
            {topCountry
              ? `${topCountry.entity} has the highest eligible historical mean at ${formatRate(topCountry.avg_rate)} per 100,000 from ${topCountry.years_reported} observations. The minimum is ${minYears} years; compare the observation counts in the table because fewer years make a mean less representative of a full series.`
              : `No entity meets the selected minimum of ${minYears} observations. Lowering the threshold may admit shorter and less comparable series.`}
          </InterpretationBox>
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
                <XAxis dataKey="year" type="number" domain={trendYearDomain} tickCount={trendChartData.length === 1 ? 3 : 8} />
                <YAxis domain={[0, 'auto']} width={48} />
                <Tooltip />
                <Legend />
                <Line type="monotone" dataKey="raw" name="Raw mean" stroke="var(--accent)" strokeWidth={3} dot={trendChartData.length === 1 ? { r: 5 } : false} />
                <Line type="monotone" dataKey="fixed" name="Fixed panel" stroke="var(--secondary)" strokeWidth={2} dot={trendChartData.length === 1 ? { r: 5 } : false} strokeDasharray="5 4" />
                <Line type="monotone" dataKey="wide" name="Wide panel" stroke="var(--accent-dark)" strokeWidth={2} dot={trendChartData.length === 1 ? { r: 5 } : false} />
                <Line type="monotone" dataKey="median" name="Median" stroke="#8a6fb8" strokeWidth={2} dot={trendChartData.length === 1 ? { r: 5 } : false} strokeDasharray="2 3" />
              </LineChart>
            ) : (
              <LineChart data={trendChartData} margin={{ top: 14, right: 18, bottom: 4, left: 0 }}>
                <CartesianGrid strokeDasharray="3 5" vertical={false} />
                <XAxis dataKey="year" type="number" domain={trendYearDomain} tickCount={trendChartData.length === 1 ? 3 : 8} />
                <YAxis domain={[0, 'auto']} width={48} />
                <Tooltip />
                <Legend />
                <Line type="monotone" dataKey={panelSeries === 'raw' ? 'raw' : panelSeries === 'fixed' ? 'fixed' : panelSeries === 'wide' ? 'wide' : 'median'} name={panelSeries} stroke="var(--accent)" strokeWidth={3} dot={trendChartData.length === 1 ? { r: 5 } : false} />
              </LineChart>
            )}
          </ResponsiveContainer>
        </div>
        {trendChartData.length === 1 && <p className="panel-note">Selected year: {trendChartData[0].year} · raw mean {formatRate(Number(trendChartData[0].raw))} per 100,000. Select a wider year range to see the historical trend.</p>}
        <ExportButtons rows={trend.yearly} name="analysis-trend" chartRef={trendRefHolder} />
          <div className="chart-explanation">
            <p>The annual mean rate across reporting entities is shown for {from}–{to}. Across the full historical dataset, the unweighted yearly mean peaks at 14.76 per 100,000 in 1982, when 52 entities reported.</p>
            <p>The chart overlays four series — raw mean, fixed eight-entity panel, wider panel, and annual median — so the same years can be compared. Because the set of reporting entities shifts over time, raw averages can move with coverage; the reporting counts chart below shows coverage rising from 10 entities in 1950 to 191 in 2004–2005.</p>
          </div>
          <div className="chart-explanation">
            <p><strong>Raw mean</strong> is the simple, unweighted average of every entity that reported a rate in that year, so it reflects both real changes and changes in who is reporting.</p>
            <p><strong>Fixed panel</strong> averages only the eight entities that report in every single year from 1950 to 2005 (Australia, Canada, Ireland, Japan, Netherlands, New Zealand, United Kingdom, United States), giving a stable like-for-like comparison.</p>
            <p><strong>Wider panel</strong> averages entities with at least 40 years of observations, a middle ground between the raw mean and the strict fixed panel.</p>
            <p><strong>Annual median</strong> is the middle value of that year's reported rates, which is less affected by extreme outliers than the mean.</p>
            <p>In the comparison table, <strong>Global mean</strong> is the unweighted average of all reporters that year, while <strong>Panel mean</strong> is the average of the fixed eight-entity panel. From 1950–2001 the panel mean is lower than the raw mean in 52 of 52 years; from 2002–2005 it is higher in 3 of 4 years. The comparison therefore reverses late in the series and should not be summarized as uniformly lower.</p>
          </div>
          <InterpretationBox>
            {peakRows.raw && peakRows.fixed && peakRows.wide && peakRows.median
              ? `Within ${from}–${to}, the raw mean peaks in ${peakRows.raw.year} (${formatRate(peakRows.raw.avg_rate)}), the fixed panel in ${peakRows.fixed.year} (${formatRate(peakRows.fixed.avg_rate)}), the ≥40-year panel in ${peakRows.wide.year} (${formatRate(peakRows.wide.avg_rate)}), and the annual median in ${peakRows.median.year} (${formatRate(peakRows.median.avg_rate)}). Different peak years show that a single “global peak” depends on series and reporting coverage.`
              : `The selected interval ${from}–${to} does not contain enough observations to calculate all four series.`}
          </InterpretationBox>
        </ChartWindow>
        <ChartWindow eyebrow="D · OBJECTIVE 2 + Q1" title="Reporting counts" caption="Entities reporting per year">
          <div className="chart-wrap" ref={(node) => { trendRefHolder.current = node }}>
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={reportingChartData} margin={{ top: 10, right: 10, bottom: 0, left: -20 }}>
              <CartesianGrid strokeDasharray="3 5" vertical={false} />
              <XAxis dataKey="year" interval="preserveStartEnd" />
              <YAxis allowDecimals={false} />
              <Tooltip />
              <Bar dataKey="countries_reporting" name="Countries reporting" fill="var(--secondary)" minPointSize={4} />
            </BarChart>
          </ResponsiveContainer>
        </div>
          {reportingChartData.length === 1 && <p className="panel-note">Selected year: {reportingChartData[0].year} · {reportingChartData[0].countries_reporting} entities reporting. Choose a wider year range to see the historical trend.</p>}
          <div className="chart-explanation">
            <p>The bar chart shows how many entities reported a suicide rate in each year in the selected range. Across 1950–2005, coverage ranges from 10 in 1950 to 191 in 2004 and 2005, with sharp nearby-year changes including 62 in 2001, 190 in 2002, and 55 in 2003.</p>
          </div>
          <InterpretationBox>
            {reportingCounts.length
              ? `For ${from}–${to}, annual reporting ranges from ${Math.min(...reportingCounts)} to ${Math.max(...reportingCounts)} entities. Abrupt coverage changes can shift a raw annual mean through composition as well as rate changes; reporter counts describe availability, not whether rates improved or worsened.`
              : `There are no reporting-count observations in the selected period ${from}–${to}.`}
          </InterpretationBox>
        </ChartWindow>
        <ChartWindow eyebrow="E · OBJECTIVE 3 + Q3" title="Country comparison table" caption="Selected entity against global and fixed-panel baselines">
          <div className="table-scroll">
            <table>
              <caption className="sr-only">Country comparison rows</caption>
              <thead><tr><th scope="col">Entity</th><th scope="col">Year</th><th scope="col">Country rate</th><th scope="col">Global mean</th><th scope="col">Panel mean</th></tr></thead>
              <tbody>
                {selectedComparison.slice(0, 60).map((row) => (
                  <tr key={`${row.entity}-${row.year}`}><td>{row.entity}</td><td>{row.year}</td><td>{formatRate(row.country_rate)}</td><td>{formatRate(row.global_avg)}</td><td>{formatRate(row.panel_avg)}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="chart-explanation">
            <p>The table lists, for each year the selected country reported a rate, that country's rate alongside the global mean and the fixed-panel mean for the same year. It is the detailed record behind the comparison chart, so you can see year by year whether the country sits above or below the global and panel baselines.</p>
            <p>{compareEntities} is shown against the unweighted average of that year's reporting entities and the average for the eight entities observed in every year from 1950 through 2005. The comparison is descriptive; it does not rank countries as better or worse.</p>
          </div>
          <InterpretationBox>
            {selectedComparison.length
              ? `${compareEntities} is above both baselines in ${selectedComparison.filter((row) => row.country_rate > row.global_avg && row.country_rate > row.panel_avg).length} of ${selectedComparison.length} reported years (${(bothBaselineShare * 100).toFixed(1)}%). Its country-minus-global gap ranges from ${gapRange(globalGaps)} and country-minus-panel from ${gapRange(panelGaps)} per 100,000. Missing years are not interpolated.`
              : `No comparison rows are available for ${compareEntities} in ${from}–${to}. Select a country and range containing reported observations.`}
          </InterpretationBox>
        </ChartWindow>
        <ChartWindow eyebrow="F · DECOMPOSITION" title="Global mean change decomposition" caption="The total change is within-country effect plus composition effect">
          {decomposition && decomposition.pairs.length > 0 ? (
            decomposition.pairs.map((pair) => (
              <p className="panel-note" key={`${pair.from_year}-${pair.to_year}`}>
                {decomposition.entity}: {pair.from_year} to {pair.to_year} — total change {formatRate(pair.total_change)} = within-country effect {formatRate(pair.within_effect)} + composition effect {formatRate(pair.composition_effect)}.
              </p>
            ))
          ) : null}
          <div className="chart-explanation">
            <p>Each row decomposes a change in the global mean, not Lithuania's own rate. The within-country effect is the mean rate change among entities present in both endpoint years; the composition effect is the residual from changes in who reports. The two parts sum to the change in the global mean.</p>
            <p>The 2000–2002 row is an additional two-year comparison next to consecutive-year pairs; it spans an omitted year and is not a one-year change.</p>
          </div>
          <InterpretationBox>
            {decompositionExample
              ? `From ${decompositionExample.from_year} to ${decompositionExample.to_year}, the global mean changes by ${formatRate(decompositionExample.total_change)} per 100,000: ${formatRate(decompositionExample.within_effect)} within-country and ${formatRate(decompositionExample.composition_effect)} composition. ${Math.abs(decompositionExample.composition_effect) > Math.abs(decompositionExample.within_effect) ? 'Composition is larger in absolute size, so this mean movement is substantially affected by the reporting mix.' : 'The within-country component is at least as large as the composition component.'} This is not a change in Lithuania's own rate.`
              : 'No decomposition rows are available.'}
          </InterpretationBox>
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
          <p>The apparent peak year depends on which series and coverage rule are used. Across the selected {from}–{to} interval, the raw mean peaks in {peakRows.raw ? `${peakRows.raw.year} at ${formatRate(peakRows.raw.avg_rate)}` : '—'}, the fixed eight-entity panel in {peakRows.fixed ? `${peakRows.fixed.year} at ${formatRate(peakRows.fixed.avg_rate)}` : '—'}, the wider panel in {peakRows.wide ? `${peakRows.wide.year} at ${formatRate(peakRows.wide.avg_rate)}` : '—'}, and the annual median in {peakRows.median ? `${peakRows.median.year} at ${formatRate(peakRows.median.avg_rate)}` : '—'} per 100,000.</p>
          <p>These differing peak years demonstrate method sensitivity; the chart alone cannot determine which series represents an unobserved world population best.</p>
        </div>
        <InterpretationBox>
          The selected period's peaks are {peakRows.raw?.year ?? 'unavailable'} for the raw mean, {peakRows.fixed?.year ?? 'unavailable'} for the fixed panel, {peakRows.wide?.year ?? 'unavailable'} for the wider panel, and {peakRows.median?.year ?? 'unavailable'} for the annual median. Different peak years show that one method-independent global maximum cannot be inferred from these series.
        </InterpretationBox>
      </section>

      <section id="compare" className="panel" aria-labelledby="compare-title">
        <ChartWindow eyebrow="E · OBJECTIVE 3 + Q3" title="Country and global baseline" caption="Selected entities against global and fixed-panel baselines">
          <div className="chart-wrap" ref={(node) => { compareRefHolder.current = node }}>
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={selectedComparison} margin={{ top: 12, right: 10, bottom: 4, left: 0 }}>
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
          <InterpretationBox>
            {selectedComparison.length
              ? `${compareEntities} is above both reference series in ${(bothBaselineShare * 100).toFixed(1)}% of its ${selectedComparison.length} reported years. The country-to-global gap ranges ${gapRange(globalGaps)} per 100,000; the country-to-panel gap ranges ${gapRange(panelGaps)}. A comparison describes differences in the observed series and does not explain their causes.`
              : `No values for ${compareEntities} are present in the selected ${from}–${to} interval; no missing values are filled in.`}
          </InterpretationBox>
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
                  <td>{row.z_score.toFixed(3)}</td>
                  <td><span className={row.zscore_flag ? 'flag-badge flag-badge--yes' : 'flag-badge flag-badge--no'} title={row.zscore_flag ? 'Flagged by z-score method' : 'Not flagged'}>{row.zscore_flag ? 'Flagged' : '—'}</span></td>
                  <td><span className={row.iqr_flag ? 'flag-badge flag-badge--yes' : 'flag-badge flag-badge--no'} title={row.iqr_flag ? 'Flagged by IQR method' : 'Not flagged'}>{row.iqr_flag ? 'Flagged' : '—'}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="chart-explanation">
          <p>These rows list year-over-year changes in a country's suicide rate that were flagged as statistically unusual. Each row is a consecutive-year pair for one entity, with the signed change, its z-score, and which screening rules it tripped. A change is flagged by the z-score method when its absolute z-score strictly exceeds 2, and by the IQR method when it falls outside the Tukey fences built from the interquartile range of all consecutive changes.</p>
          <p>The KPIs summarize the screening: how many consecutive-year pairs were evaluated, how many were flagged by each method, and how many were flagged by both. These are descriptive screening flags, not proof of data errors or explanations of causes — an unusual change may reflect a real shift, a reporting change, or noise, and only the data themselves can distinguish these.</p>
        </div>
        <InterpretationBox>
          {anomalySummary
            ? `Across ${anomalySummary.consecutive_changes.toLocaleString()} consecutive-year changes, ${anomalySummary.zscore_count} (${(anomalySummary.zscore_count / anomalySummary.consecutive_changes * 100).toFixed(2)}%) exceed |z| > 2, close to the 4.6% normal-reference share. All ${anomalySummary.zscore_count} z-score flags are also among the ${anomalySummary.iqr_count} IQR flags; the top three flagged entities (${topChangeFlagCountries.map(([name, count]) => `${name} (${count})`).join(', ')}) account for ${(topThreeChangeFlagShare * 100).toFixed(1)}% of z flags. Flags locate unusual changes; they do not prove an error or cause.`
            : 'Anomaly counts are loading.'}
        </InterpretationBox>
      </section>

      <section id="coverage" className="panel" aria-labelledby="coverage-title">
        <PanelHeading eyebrow="G · OBJECTIVE 5" title="Reporting coverage" caption="Coverage tiers, gaps, and entity counts" />
        <div className="kpi-grid">
          <article className="kpi-card"><div className="kpi-label">Entities tracked</div><div className="kpi-value">{coverage ? quality.entity_count : 0}</div><div className="kpi-unit">in coverage report</div></article>
          <article className="kpi-card"><div className="kpi-label">Historical coverage period</div><div className="kpi-value">56</div><div className="kpi-unit">years · 1950–2005</div></article>
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
          <p>Reporting coverage describes how completely each entity is observed during 1950–2005. Each row shows one entity, how many years it reported, its first and last reporting year, and the gaps — years missing between its first and last report. The KPIs summarize entities in the report, the 56-year coverage period, listed entities, and total missing year slots within observed spans.</p>
          <p>Uneven coverage matters because the annual averages are unweighted means of whoever reported that year. An entity added or dropped between years changes the composition of the average, so a rise or fall in the yearly mean can reflect changing coverage as much as changing rates. Entities with fewer than the required years are excluded from rankings, and missing years are never interpolated.</p>
        </div>
        <InterpretationBox>
          {coverage
            ? `Only ${coverageComplete} of ${coverage.coverage.length} entities report in every year from 1950–2005; ${coverageSparse} entities have three or fewer observations. This uneven coverage limits how representative year-to-year global averages and short country series can be.`
            : 'Coverage statistics are loading.'}
        </InterpretationBox>
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
        <InterpretationBox>
          The findings summarize descriptive patterns, not causal explanations. Read each confidence label alongside its stated caveat and the underlying coverage: the labels are qualitative evidence-strength assessments, not statistical confidence intervals.
        </InterpretationBox>
      </section>

      <section id="methods" className="panel" aria-labelledby="methods-title">
        <PanelHeading eyebrow="I · METHODS AND CONTEXT" title="Methods, limitations, context" caption="How the numbers are produced and how to interpret them" />
        <div className="about-content">
          <p><strong>Source:</strong> SDG-3 suicide rates by country, age-adjusted suicides per 100,000 people. Original dataset: <a href="https://github.com/liadkeller/Suicides-Data-Analysis-DSE200X/blob/master/suicide-rates-by-country.csv" target="_blank" rel="noreferrer">Suicides Data Analysis (liadkeller/Suicides-Data-Analysis-DSE200X)<span className="sr-only"> (opens in a new tab)</span></a>. Analysis accessed October 23, 2026. Data range: 1950–2005.</p>
          <p><strong>Method:</strong> Yearly averages are unweighted means of entities with an observation in that year. Country ranking requires at least 10 observations; six former-state entities with publisher-specific codes remain available in historical views but are not ranked as current countries.</p>
          <p><strong>Limitations:</strong> Data ends in 2005; country coverage and years reported are uneven. Outliers are retained. The data are descriptive only; no causal or predictive claims are made. Correlation does not establish causation.</p>
          <p><strong>Safe messaging:</strong> If you or someone you know needs support, contact a local crisis service. <a href="https://findahelpline.com/" target="_blank" rel="noreferrer">Find international crisis resources at findahelpline.com<span className="sr-only"> (opens in a new tab)</span></a>.</p>
        </div>
        <InterpretationBox>
          All results are descriptive summaries of the available 1950–2005 records. Uneven coverage, historical boundaries, and missing observations limit comparisons; no result establishes causation or predicts future rates.
        </InterpretationBox>
      </section>
    </main>
  )
}
