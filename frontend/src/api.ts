export type KPI = {
  global_avg: number
  peak_year: number
  peak_value: number
  top_country: { entity: string; avg_rate: number; years_reported: number } | null
  country_count: number
}
export type TrendRow = { year: number; avg_rate: number; countries_reporting: number }
export type TopCountry = { entity: string; avg_rate: number; years_reported: number }
export type Country = { entity: string; code: string }
export type CompareRow = { year: number; country_rate: number; global_avg: number }
export type Anomaly = { entity: string; year: number; change: number; z_score: number }
export type AnalysisFlaggedRow = Anomaly & { zscore_flag: boolean; iqr_flag: boolean }
export type Coverage = { entity: string; years_reported: number; first_year: number | null; last_year: number | null; gaps: number }
export type Insight = { title: string; detail: string; caveat: string }

export type AnalysisSummary = {
  mean: number
  median: number
  std: number
  min: number
  max: number
  q1: number
  q3: number
  global_peak_year: number
  global_peak_avg_rate: number
  global_peak_countries_reporting: number
  fixed_panel_entities: string[]
  fixed_panel_average: number | null
  fixed_panel_peak_year: number | null
  fixed_panel_peak_avg_rate: number | null
  minimum_years_for_top_countries: number
  unfiltered_top_three: TopCountry[]
}
export type AnalysisQuality = {
  row_count: number
  entity_count: number
  iso_entity_count: number
  former_state_entities: Record<string, string>
  quality: {
    null_cells: number
    duplicate_entity_year_rows: number
    invalid_codes: number
    non_country_aggregates: unknown[]
    negative_or_zero_rates: number
    rate_iqr_fences: [number, number]
    rate_outlier_count: number
    outliers_retained: boolean
    country_year_gaps_within_observed_span: number
  }
  summary: AnalysisSummary
  coverage: Coverage[]
  coverage_count_distribution: Array<Record<string, number>>
}
export type RateDistribution = {
  histogram: Array<{ range: string; count: number }>
  outliers: Array<{ entity: string; code: string; year: number; rate: number }>
  rate_iqr_fences: [number, number]
  summary: AnalysisSummary
}
export type AnalysisTrend = {
  from: number
  to: number
  yearly: TrendRow[]
  fixed_panel: TrendRow[]
  wide_panel: TrendRow[]
  median: TrendRow[]
  reporting_counts: TrendRow[]
  panel_entities: string[]
}
export type DecompositionPair = {
  from_year: number
  to_year: number
  total_change: number
  within_effect: number
  composition_effect: number
  countries_in_both: number
}
export type Decomposition = {
  entity: string
  pairs: DecompositionPair[]
}
export type CompareMultiRow = {
  entity: string
  year: number
  country_rate: number
  global_avg: number
  panel_avg: number
}
export type AnomalySummary = {
  consecutive_changes: number
  change_mean: number
  change_std: number
  iqr_change_fences: number[]
  zscore_count: number
  iqr_count: number
  both_count: number
  flagged_rows: AnalysisFlaggedRow[]
}
export type CoverageDeep = {
  coverage: Coverage[]
  coverage_count_distribution: Array<Record<string, number>>
  summary: AnalysisSummary
}
export type Finding = {
  number: number
  title: string
  detail: string
  caveat: string
  confidence: string
  section: string
}

export type RelationshipRow = {
  id: string
  label: string
  description: string
  n: number
  entities: number
  pearson: number | null
  pearson_ci: number[] | null
}

export type RelationshipVerdict = {
  id: string
  label: 'Favourable' | 'Not Favourable' | 'Mixed'
  judged_on: string
  icon: string
  rule: string
  reason: string
}

export type RelationshipPoint = {
  entity: string
  code: string
  x: number
  y: number
  x_obs: number
  y_obs: number
  former_state: boolean
  label_rank: number | null
}

export type RelationshipStat = {
  id: string
  label: string
  n: number
  pearson: number | null
  pearson_ci: number[] | null
  spearman: number | null
  spearman_ci: number[] | null
}

export type RelationshipBlock = {
  id: string
  title: string
  question: string
  x_label: string
  y_label: string
  n: number
  pearson: number | null
  pearson_ci: number[] | null
  spearman: number | null
  spearman_ci: number[] | null
  points: RelationshipPoint[]
  sensitivity: RelationshipStat[]
  cutoff?: number
  cutoff_label?: string
  reference_line: boolean
  verdict: RelationshipVerdict
  subset?: RelationshipStat
  windows?: Record<string, number[]>
  min_observations?: number
}

export type RelationshipsFull = {
  version: number
  source: string
  period: { from: number; to: number }
  bootstrap: { method: string; resamples: number; seed: number; confidence: number; interval: string }
  verdict_rules: Record<string, unknown>
  block_a: {
    id: string
    title: string
    question: string
    rows: RelationshipRow[]
    verdict: RelationshipVerdict
    message: string
    chart_note: string
  }
  block_b: Record<'B1' | 'B2' | 'B3' | 'B4', RelationshipBlock>
  takeaways: Record<string, string>
  anomaly_sensitivity: {
    consecutive_changes: number
    pooled_zscore_flags: number
    within_country_zscore_flags: number
    status_changes: number
    note: string
  }
  findings: Finding[]
  methods: {
    block_a: string
    windows: Record<string, unknown>
    bootstrap: string
    verdict_rules: Record<string, unknown>
    no_pvalues: string
    causation: string
  }
}

export type RelationshipsCompact = {
  version: number
  source: string
  period: { from: number; to: number }
  bootstrap: RelationshipsFull['bootstrap']
  note: string
  anchors: Record<'A' | 'B1' | 'B2' | 'B3' | 'B4', string>
  block_a: {
    id: string
    title: string
    question: string
    rows: RelationshipRow[]
    verdict: RelationshipVerdict
    message: string
  }
  block_b: Record<'B1' | 'B3' | 'B4', RelationshipBlock>
  takeaways: Record<string, string>
}

export type RangeSummary = {
  from: number
  to: number
  mean: number
  median: number
  records: number
  entity_count: number
  peak_year: number | null
  peak_value: number | null
  peak_countries_reporting: number | null
  top_country: TopCountry | null
}


const API_BASE = import.meta.env.VITE_API_BASE ?? '/api/v1'

async function request<T>(path: string): Promise<T> {
  const url = `${API_BASE}${path}`
  let response: Response
  try {
    response = await fetch(url)
  } catch (error) {
    const reason = error instanceof Error ? error.message : String(error)
    throw new Error(`Could not reach API ${url}: ${reason}`)
  }

  const contentType = response.headers.get('content-type') ?? ''
  if (!contentType.includes('application/json')) {
    const responseKind = contentType || 'unknown content type'
    throw new Error(
      `API ${url} returned ${responseKind} instead of JSON (HTTP ${response.status}). Check the Vercel /api/* rewrite and backend deployment.`,
    )
  }

  if (!response.ok) {
    const body = await response.json().catch(() => ({}))
    throw new Error(body.message ?? `Request failed (${response.status})`)
  }
  return response.json() as Promise<T>
}

export function rangeQuery(from: number, to: number) {
  return `from=${from}&to=${to}`
}

export const api = {
  kpis: (from: number, to: number) => request<KPI>(`/kpis?${rangeQuery(from, to)}`),
  trend: (from: number, to: number) => request<TrendRow[]>(`/trend/global?${rangeQuery(from, to)}`),
  top: (from: number, to: number) => request<TopCountry[]>(`/countries/top?n=10&${rangeQuery(from, to)}`),
  countries: () => request<Country[]>('/countries'),
  compare: (entity: string, from: number, to: number) =>
    request<CompareRow[]>(`/compare?entity=${encodeURIComponent(entity)}&${rangeQuery(from, to)}`),
  anomalies: (entity: string, from: number, to: number) =>
    request<Anomaly[]>(`/anomalies?entity=${encodeURIComponent(entity)}&method=zscore&threshold=2&${rangeQuery(from, to)}`),
  coverage: (from: number, to: number) => request<Coverage[]>(`/coverage?limit=250&${rangeQuery(from, to)}`),
  insights: () => request<Insight[]>('/insights'),
  analysisQuality: () => request<AnalysisQuality>('/analysis/quality'),
  analysisDistribution: () => request<RateDistribution>('/analysis/distribution'),
  analysisTopCountries: (minYears: number, from: number, to: number) => request<TopCountry[]>(`/analysis/top-countries?min_years=${minYears}&${rangeQuery(from, to)}`),
  analysisTrend: (from: number, to: number) => request<AnalysisTrend>(`/analysis/trend?${rangeQuery(from, to)}`),
  analysisDecomposition: (entity: string) => request<Decomposition>(`/analysis/decomposition?entity=${encodeURIComponent(entity)}`),
  analysisCompareMulti: (entities: string) => request<CompareMultiRow[]>(`/analysis/compare-multi?entities=${encodeURIComponent(entities)}`),
  analysisAnomalies: () => request<AnomalySummary>('/analysis/anomalies'),
  analysisCoverage: () => request<CoverageDeep>('/analysis/coverage'),
  analysisFindings: () => request<Finding[]>('/analysis/findings'),
  analysisSummary: (from: number, to: number) => request<RangeSummary>(`/analysis/summary?${rangeQuery(from, to)}`),
  relationshipsFull: () => request<RelationshipsFull>('/analysis/relationships'),
  relationshipsCompact: () => request<RelationshipsCompact>('/analysis/relationships/compact'),
  analysisRegistry: () => request<Record<string, unknown>>('/analysis/registry'),
  analysisAlignment: (entity: string, from: number, to: number) =>
    request<Record<string, unknown>>(`/analysis/alignment?entity=${encodeURIComponent(entity)}&${rangeQuery(from, to)}`),
}
