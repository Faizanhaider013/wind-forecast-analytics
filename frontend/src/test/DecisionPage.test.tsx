import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "../api/client";
import * as endpoints from "../api/endpoints";
import { DecisionPage } from "../pages/DecisionPage";
import { availableDatesFixture, decisionFixture } from "./fixtures";

vi.mock("../api/endpoints", () => ({
  getAvailableDates: vi.fn(),
  getDecision: vi.fn(),
  getAccuracy: vi.fn(),
  getHorizon: vi.fn(),
}));

const getAvailableDates = vi.mocked(endpoints.getAvailableDates);
const getDecision = vi.mocked(endpoints.getDecision);

beforeEach(() => {
  vi.clearAllMocks();
  getAvailableDates.mockResolvedValue(availableDatesFixture);
  getDecision.mockResolvedValue(decisionFixture());
});

describe("DecisionPage", () => {
  it("shows a loading state before data arrives", () => {
    render(<DecisionPage />);
    expect(screen.getAllByRole("status").length).toBeGreaterThan(0);
    expect(screen.getByText(/loading decision data/i)).toBeInTheDocument();
  });

  it("defaults to the first complete January date and fetches its decision", async () => {
    render(<DecisionPage />);
    await waitFor(() => expect(getDecision).toHaveBeenCalledWith("2026-01-15", 10, expect.anything()));
    expect(await screen.findByText(/Avg forecast/i)).toBeInTheDocument();
    // A formatted stat value is rendered (not a hardcoded literal in the component).
    expect(screen.getByText("11,150 MW")).toBeInTheDocument();
    expect(screen.getByText(/Full coverage/i)).toBeInTheDocument();
  });

  it("renders a partial-coverage warning and shows gaps, never interpolated values", async () => {
    getDecision.mockResolvedValue(
      decisionFixture({
        periods: [
          {
            hour_utc: "2026-01-15T00:00:00Z",
            forecast_mw: null,
            forecast_publish_time: null,
            actual_mean_mw: 9500,
            actual_n_half_hours: 2,
            actual_complete: true,
            error_mw: null,
            matched: false,
          },
        ],
        coverage: {
          expected_hours: 24,
          forecast_hours_present: 0,
          actual_hours_complete: 1,
          matched_hours: 0,
          missing_forecast_hours: ["2026-01-15T00:00:00Z"],
          incomplete_actual_hours: [],
          fully_covered: false,
        },
      }),
    );
    render(<DecisionPage />);
    expect(await screen.findByText(/Partial coverage/i)).toBeInTheDocument();
    // The missing-forecast hour renders as "no forecast", not a fabricated number.
    const table = screen.getByRole("table");
    expect(within(table).getByText(/no forecast/i)).toBeInTheDocument();
  });

  it("shows an error state when the decision request fails", async () => {
    getDecision.mockRejectedValue(new ApiError("boom", 503));
    render(<DecisionPage />);
    expect(await screen.findByText(/something went wrong/i)).toBeInTheDocument();
    expect(screen.getByText("boom")).toBeInTheDocument();
  });

  it("refetches when the cutoff hour changes", async () => {
    render(<DecisionPage />);
    await waitFor(() => expect(getDecision).toHaveBeenCalledWith("2026-01-15", 10, expect.anything()));

    await userEvent.selectOptions(screen.getByLabelText(/day-ahead cutoff/i), "8");
    await waitFor(() => expect(getDecision).toHaveBeenCalledWith("2026-01-15", 8, expect.anything()));
  });

  it("refetches when the delivery date changes", async () => {
    render(<DecisionPage />);
    await waitFor(() => expect(getDecision).toHaveBeenCalledWith("2026-01-15", 10, expect.anything()));

    await userEvent.selectOptions(screen.getByLabelText(/delivery date/i), "2026-01-16");
    await waitFor(() => expect(getDecision).toHaveBeenCalledWith("2026-01-16", 10, expect.anything()));
  });
});
