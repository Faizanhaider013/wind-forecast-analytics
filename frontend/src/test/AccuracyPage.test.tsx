import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../api/client";
import * as endpoints from "../api/endpoints";
import { AccuracyPage } from "../pages/AccuracyPage";
import { accuracyFixture, horizonFixture } from "./fixtures";

vi.mock("../api/endpoints", () => ({
  getAvailableDates: vi.fn(),
  getDecision: vi.fn(),
  getAccuracy: vi.fn(),
  getHorizon: vi.fn(),
}));

const getAccuracy = vi.mocked(endpoints.getAccuracy);
const getHorizon = vi.mocked(endpoints.getHorizon);

beforeEach(() => {
  vi.clearAllMocks();
  getAccuracy.mockResolvedValue(accuracyFixture());
  getHorizon.mockResolvedValue(horizonFixture());
});

describe("AccuracyPage", () => {
  it("defaults to January 2026 and renders the metric cards", async () => {
    render(<AccuracyPage />);
    await waitFor(() =>
      expect(getAccuracy).toHaveBeenCalledWith("2026-01-01", "2026-01-31", 10, expect.anything()),
    );
    // MAE appears in the metric card and again in the persistence comparison.
    expect((await screen.findAllByText("2,123 MW")).length).toBeGreaterThan(0); // MAE
    expect(screen.getByText("18.3%")).toBeInTheDocument(); // WMAPE
    expect(screen.getByText(/forecasts over-predict/i)).toBeInTheDocument(); // positive bias
  });

  it("shows the persistence benchmark with a paired, same-sample comparison", async () => {
    render(<AccuracyPage />);
    expect(await screen.findByText(/forecast vs persistence benchmark/i)).toBeInTheDocument();
    expect(screen.getByText("4,184 MW")).toBeInTheDocument(); // persistence MAE (rounded)
    // Skill uses the server's paired value, and the forecast MAE shown is the
    // same-sample one (2,012), not the whole-range MAE (2,123).
    expect(screen.getByText("51.9%")).toBeInTheDocument();
    expect(screen.getByText("2,012 MW")).toBeInTheDocument();
  });

  it("hides the persistence benchmark when not included and safely handles null metrics", async () => {
    getAccuracy.mockResolvedValue(
      accuracyFixture({
        metrics: {
          n: 0,
          mae_mw: null,
          rmse_mw: null,
          bias_mw: null,
          wmape_fraction: null,
          wmape_percent: null,
          sum_actual_mw: 0,
          note: "no matched observations",
        },
        persistence_benchmark: {
          n: 0,
          mae_mw: null,
          rmse_mw: null,
          bias_mw: null,
          wmape_fraction: null,
          wmape_percent: null,
          sum_actual_mw: 0,
          note: "omitted: no prior-day actual",
          definition: "naive forecast = actual hourly mean two days earlier",
          included: false,
          model_mae_mw_same_sample: null,
          model_rmse_mw_same_sample: null,
          skill_mae_percent: null,
        },
      }),
    );
    render(<AccuracyPage />);
    expect(await screen.findByText(/no matched observations in this period/i)).toBeInTheDocument();
    expect(screen.queryByText(/forecast vs persistence benchmark/i)).not.toBeInTheDocument();
  });

  it("documents that a daily trend is not available (no N+1 fan-out)", async () => {
    render(<AccuracyPage />);
    expect(await screen.findByText(/daily breakdown is intentionally not shown/i)).toBeInTheDocument();
  });

  it("renders horizon buckets with sample counts and the all-vintages caveat", async () => {
    render(<AccuracyPage />);
    await waitFor(() => expect(getHorizon).toHaveBeenCalledWith("2026-01-01", "2026-01-31", null, expect.anything()));
    expect(await screen.findByText(/all vintages by lead time/i)).toBeInTheDocument();
    const table = screen.getAllByRole("table").at(-1)!;
    expect(within(table).getByText("<0h")).toBeInTheDocument();
    expect(within(table).getByText("3,721")).toBeInTheDocument(); // sample count
  });

  it("switches the horizon to day-ahead-eligible vintages using the cutoff", async () => {
    getHorizon.mockResolvedValueOnce(horizonFixture());
    getHorizon.mockResolvedValue(
      horizonFixture({ cutoff_hour: 10, cutoff_applied: true, excluded_after_cutoff: 500 }),
    );
    render(<AccuracyPage />);
    await screen.findByText(/all vintages by lead time/i);

    await userEvent.click(screen.getByRole("button", { name: /day-ahead eligible only/i }));
    await waitFor(() =>
      expect(getHorizon).toHaveBeenCalledWith("2026-01-01", "2026-01-31", 10, expect.anything()),
    );
    // Unique to cutoff mode: the excluded-vintages note in the banner.
    expect(await screen.findByText(/later vintage\(s\) excluded/i)).toBeInTheDocument();
  });

  it("shows an error state when accuracy fails to load", async () => {
    getAccuracy.mockRejectedValue(new ApiError("backend down", 503));
    render(<AccuracyPage />);
    expect(await screen.findByText(/something went wrong/i)).toBeInTheDocument();
    expect(screen.getByText("backend down")).toBeInTheDocument();
  });
});
