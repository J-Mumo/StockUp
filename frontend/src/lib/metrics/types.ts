// Types for the Learn Mode metric registry.
//
// A MetricDefinition is the single source of truth for how a metric is
// described to the user — its label, plain-English explanation, sector
// applicability, and interpretation rules.

export type MetricSector = 'all' | 'bank' | 'insurance' | 'industrial' | 'reit';

export type MetricUnit =
  | 'currency'
  | 'percent'      // stored as 0.15 for 15%
  | 'percent_pts'  // stored as 15 for 15% (already scaled)
  | 'ratio'
  | 'multiple'
  | 'count'
  | 'years'
  | 'score';       // 0-100 scorecard axis

export type MetricCategory =
  | 'valuation'
  | 'profitability'
  | 'solvency'
  | 'liquidity'
  | 'growth'
  | 'efficiency'
  | 'risk'
  | 'income'
  | 'scorecard';

export type MetricVerdict = 'good' | 'ok' | 'caution' | 'bad';

export interface MetricThreshold {
  // Ranges are lower-bound inclusive, upper-bound exclusive.
  // null means unbounded on that side.
  // Values are in the same unit as the stored metric value.
  min: number | null;
  max: number | null;
  verdict: MetricVerdict;
  note?: string;
}

export interface MetricDefinition {
  key: string;
  label: string;
  short_label?: string;
  unit: MetricUnit;
  sectors: MetricSector[];
  category: MetricCategory;

  // Learn-mode copy — all required, kept short.
  one_liner: string;               // ≤ 100 chars, shown in tooltip
  what_it_measures: string;
  how_its_calculated: string;
  what_high_means: string;
  what_low_means: string;
  watch_outs: string[];
  rule_of_thumb?: string;

  // Interpretation
  higher_is_better: boolean | 'context';
  thresholds?: MetricThreshold[];

  related_metrics?: string[];
}
