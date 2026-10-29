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
}
