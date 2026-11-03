export const LABELS = {
  observationMean: 'Observation mean',
  median: 'Median',
  peakYear: 'Peak year',
  peakValue: 'Peak year average',
  topEligibleCountry: 'Top eligible country',
  entitiesWithReportedRates: 'Entities with reported rates',
  entities: 'Entities',
  records: 'Records',
  coverageYears: 'Years reported',
  countryMean: 'Country mean',
  period: 'Period',
  pearson: 'Pearson r',
  spearman: 'Spearman rho',
  sampleSize: 'n',
} as const

export type MetricFormat = 'rate2' | 'zscore3' | 'count0' | 'year' | 'text' | 'range' | 'list'

const FORMATTERS: Record<MetricFormat, (value: number | string | null | undefined) => string> = {
  rate2: (value) =>
    value === null || value === undefined || Number.isNaN(Number(value))
      ? '—'
      : Number(value).toLocaleString('en', { minimumFractionDigits: 2, maximumFractionDigits: 2 }),
  zscore3: (value) =>
    value === null || value === undefined || Number.isNaN(Number(value)) ? '—' : Number(value).toFixed(3),
  count0: (value) =>
    value === null || value === undefined || Number.isNaN(Number(value))
      ? '—'
      : Math.round(Number(value)).toLocaleString('en', { maximumFractionDigits: 0 }),
  year: (value) => (value === null || value === undefined ? '—' : String(Math.trunc(Number(value)))),
  text: (value) => (value === null || value === undefined ? '—' : String(value)),
  range: (value) => (value === null || value === undefined ? '—' : String(value)),
  list: (value) => (value === null || value === undefined ? '—' : String(value)),
}

export function formatMetric(value: number | string | null | undefined, format: MetricFormat): string {
  return FORMATTERS[format](value)
}

export function formatRate(value: number | null | undefined): string {
  return formatMetric(value, 'rate2')
}

export function formatZScore(value: number | null | undefined): string {
  return formatMetric(value, 'zscore3')
}

export function formatCount(value: number | null | undefined): string {
  return formatMetric(value, 'count0')
}

export function formatYearRange(from: number, to: number): string {
  return `${from}–${to}`
}

export function formatInterval(interval: number[] | null | undefined): string {
  if (!interval || interval.length < 2) return '—'
  return `${formatRate(interval[0])} to ${formatRate(interval[1])}`
}
