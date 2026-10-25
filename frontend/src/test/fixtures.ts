// Schema-accurate fixtures for tests (shapes confirmed against the live API).

import type {
  AccuracyResponse,
  AvailableDatesResponse,
  DecisionResponse,
  HorizonResponse,
} from "../api/types";

export const availableDatesFixture: AvailableDatesResponse = {
  dates: [
    {
      date: "2026-01-15",
      actuals: { half_hour_periods: 48, expected: 48, complete: true },
      forecasts: { target_hours: 24, expected: 24, vintages: 584, complete: true },
      complete: true,
    },
    {
      date: "2026-01-16",
      actuals: { half_hour_periods: 48, expected: 48, complete: true },
      forecasts: { target_hours: 24, expected: 24, vintages: 560, complete: true },
      complete: true,
    },
  ],
  summary: {
    total_dates: 2,
    complete_dates: 2,
    actuals_complete_dates: 2,
    forecasts_complete_dates: 2,
  },
};

export function decisionFixture(overrides: Partial<DecisionResponse> = {}): DecisionResponse {
  const periods = Array.from({ length: 24 }, (_, h) => {
    const hh = String(h).padStart(2, "0");
    return {
      hour_utc: `2026-01-15T${hh}:00:00Z`,
      forecast_mw: 10000 + h * 100,
      forecast_publish_time: "2026-01-14T09:30:00Z",
      actual_mean_mw: 9500 + h * 90,
      actual_n_half_hours: 2,
      actual_complete: true,
      error_mw: 500 + h * 10,
      matched: true,
    };
  });
  return {
    delivery_date: "2026-01-15",
    cutoff: {
      hour_local: 10,
      timezone: "Europe/London",
      local_time: "2026-01-14T10:00:00+0000",
      utc_time: "2026-01-14T10:00:00Z",
      rule: "10:00 Europe/London on the day 1 before delivery; later vintages excluded",
    },
    granularity_note:
      "Forecasts are hourly (WINDFOR). Actuals are half-hourly (FUELHH) aggregated to hourly mean.",
    periods,
    summary: {
      forecast: { avg_mw: 11150, total_mwh: 267600, hours_with_forecast: 24 },
      actual: {
        avg_mw: 10535,
        total_mwh_hourly_basis: 252840,
        total_mwh_halfhourly_basis: 252840,
        hours_complete: 24,
        half_hours_present: 48,
      },
    },
    coverage: {
      expected_hours: 24,
      forecast_hours_present: 24,
      actual_hours_complete: 24,
      matched_hours: 24,
      missing_forecast_hours: [],
      incomplete_actual_hours: [],
      fully_covered: true,
    },
    ...overrides,
  };
}

export function accuracyFixture(overrides: Partial<AccuracyResponse> = {}): AccuracyResponse {
  return {
    from: "2026-01-01",
    to: "2026-01-31",
    cutoff: {
      hour_local: 10,
      timezone: "Europe/London",
      rule: "10:00 Europe/London on the day before each delivery date",
    },
    metrics: {
      n: 744,
      mae_mw: 2122.811,
      rmse_mw: 2616.689,
      bias_mw: 1840.296,
      wmape_fraction: 0.18331,
      wmape_percent: 18.331,
      sum_actual_mw: 8616068.5,
      note: null,
    },
    persistence_benchmark: {
      n: 696,
      mae_mw: 4183.673,
      rmse_mw: 5190.397,
      bias_mw: 147.614,
      wmape_fraction: 0.36938,
      wmape_percent: 36.938,
      sum_actual_mw: 7883083.5,
      note: null,
      definition: "naive forecast = actual hourly mean two days earlier",
      included: true,
      model_mae_mw_same_sample: 2012.163,
      model_rmse_mw_same_sample: 2513.571,
      skill_mae_percent: 51.9,
      comparison_note: "compared over the same 696 hours",
    },
    coverage: {
      expected_hours: 744,
      matched_hours: 744,
      excluded_missing_forecast: 0,
      excluded_incomplete_actual: 0,
      matched_fraction: 1.0,
    },
    ...overrides,
  };
}

export function horizonFixture(overrides: Partial<HorizonResponse> = {}): HorizonResponse {
  return {
    from: "2026-01-01",
    to: "2026-01-31",
    cutoff_hour: null,
    cutoff_applied: false,
    horizon_convention: "lead time = target − publication time, half-open buckets.",
    excluded_after_cutoff: 0,
    buckets: [
      { bucket: "<0h", lead_hours_from: null, lead_hours_to: 0, n: 3721, mae_mw: 1892.9, rmse_mw: 2408.5, bias_mw: 1761.6 },
      { bucket: "0-6h", lead_hours_from: 0, lead_hours_to: 6, n: 1488, mae_mw: 1772.3, rmse_mw: 2253.4, bias_mw: 1545.7 },
      { bucket: "6-12h", lead_hours_from: 6, lead_hours_to: 12, n: 1488, mae_mw: 1843.4, rmse_mw: 2311.6, bias_mw: 1613.2 },
      { bucket: "48h+", lead_hours_from: 48, lead_hours_to: null, n: 2510, mae_mw: 2380.6, rmse_mw: 2980.0, bias_mw: 1465.9 },
    ],
    total_scored_vintages: 9207,
    ...overrides,
  };
}
