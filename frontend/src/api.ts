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
  flagged_rows: Anomaly[]
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

const API_BASE = import.meta.env.VITE_API_BASE ?? '/api/v1'

async function request<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`)
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
}
