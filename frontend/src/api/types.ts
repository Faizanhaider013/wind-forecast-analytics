// TypeScript interfaces mirroring the backend response schemas exactly.
// These were confirmed against the live endpoints running on the January 2026
// database; field names and nullability match the API, not assumptions.

export interface CoverageCount {
  half_hour_periods: number;
  expected: number;
  complete: boolean;
}

export interface ForecastCoverageCount {
  target_hours: number;
  expected: number;
  vintages: number;
  complete: boolean;
}

export interface AvailableDate {
  date: string; // YYYY-MM-DD
  actuals: CoverageCount;
  forecasts: ForecastCoverageCount;
  complete: boolean;
}

export interface AvailableDatesResponse {
  dates: AvailableDate[];
  summary: {
    total_dates: number;
    complete_dates: number;
    actuals_complete_dates: number;
    forecasts_complete_dates: number;
  };
}

export interface CutoffInfo {
  hour_local: number;
  timezone: string;
  local_time?: string; // present on /decision
  utc_time?: string; // present on /decision
  rule: string;
}

export interface DecisionPeriod {
  hour_utc: string; // ISO UTC, e.g. 2026-01-15T00:00:00Z
  forecast_mw: number | null;
  forecast_publish_time: string | null;
  actual_mean_mw: number | null;
  actual_n_half_hours: number;
  actual_complete: boolean;
  error_mw: number | null; // forecast - actual (positive => overpredict)
  matched: boolean;
}

export interface DecisionSummary {
  forecast: {
    avg_mw: number | null;
    total_mwh: number;
    hours_with_forecast: number;
  };
  actual: {
    avg_mw: number | null;
    total_mwh_hourly_basis: number;
    total_mwh_halfhourly_basis: number;
    hours_complete: number;
    half_hours_present: number;
  };
}

export interface DecisionCoverage {
  expected_hours: number;
  forecast_hours_present: number;
  actual_hours_complete: number;
  matched_hours: number;
  missing_forecast_hours: string[];
  incomplete_actual_hours: string[];
  fully_covered: boolean;
}

export interface DecisionResponse {
  delivery_date: string;
  cutoff: CutoffInfo;
  granularity_note: string;
  periods: DecisionPeriod[];
  summary: DecisionSummary;
  coverage: DecisionCoverage;
}

export interface Metrics {
  n: number;
  mae_mw: number | null;
  rmse_mw: number | null;
  bias_mw: number | null;
  wmape_fraction: number | null;
  wmape_percent: number | null;
  sum_actual_mw: number;
  note: string | null;
}

export interface PersistenceBenchmark extends Metrics {
  definition: string;
  included: boolean;
  // Paired comparison over the same hours the benchmark covers (added so skill
  // is not computed across two different samples).
  model_mae_mw_same_sample: number | null;
  model_rmse_mw_same_sample: number | null;
  skill_mae_percent: number | null;
  comparison_note?: string;
}

export interface AccuracyResponse {
  from: string;
  to: string;
  cutoff: CutoffInfo;
  metrics: Metrics;
  persistence_benchmark: PersistenceBenchmark;
  coverage: {
    expected_hours: number;
    matched_hours: number;
    excluded_missing_forecast: number;
    excluded_incomplete_actual: number;
    matched_fraction: number | null;
  };
}

export interface HorizonBucket {
  bucket: string;
  lead_hours_from: number | null; // null => open lower bound (-inf)
  lead_hours_to: number | null; // null => open upper bound (+inf)
  n: number;
  mae_mw: number | null;
  rmse_mw: number | null;
  bias_mw: number | null;
}

export interface HorizonResponse {
  from: string;
  to: string;
  cutoff_hour: number | null;
  cutoff_applied: boolean;
  horizon_convention: string;
  excluded_after_cutoff: number;
  buckets: HorizonBucket[];
  total_scored_vintages: number;
}
