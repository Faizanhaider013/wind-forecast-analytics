import { useEffect, useMemo, useState } from "react";
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { getAvailableDates, getDecision } from "../api/endpoints";
import type { DecisionResponse } from "../api/types";
import { Banner, Panel } from "../components/Panel";
import { ErrorState, LoadingState } from "../components/States";
import { StatCard } from "../components/StatCard";
import { useAsync, type AsyncState } from "../hooks/useAsync";
import { count, mw, mwh, signedMw, ukDateTime, ukTime } from "../utils/format";

const FORECAST_COLOR = "#2563eb";
const ACTUAL_COLOR = "#0e9f6e";

const HOURS = Array.from({ length: 24 }, (_, h) => h);

export function DecisionPage() {
  const datesState = useAsync((signal) => getAvailableDates(signal), []);
  const [deliveryDate, setDeliveryDate] = useState<string>("");
  const [cutoffHour, setCutoffHour] = useState<number>(10);

  // Default to the first complete January date once available-dates loads.
  useEffect(() => {
    if (datesState.status !== "success" || deliveryDate) return;
    const dates = datesState.data.dates;
    const firstComplete = dates.find((d) => d.complete) ?? dates[0];
    if (firstComplete) setDeliveryDate(firstComplete.date);
  }, [datesState, deliveryDate]);

  const decisionState = useAsync(
    (signal) =>
      deliveryDate
        ? getDecision(deliveryDate, cutoffHour, signal)
        : new Promise<DecisionResponse>(() => {}), // idle until a date is chosen
    [deliveryDate, cutoffHour],
  );

  return (
    <main className="page">
      <div className="page__head">
        <h1>Day-ahead decision dashboard</h1>
        <p className="page__subtitle">
          The wind forecast available at the day-ahead buying cutoff, compared with
          the generation that actually occurred. Forecasts are the latest WINDFOR
          vintage published on or before the cutoff — later vintages are never used.
        </p>
      </div>

      <div className="stack">
        <Panel title="Delivery day & cutoff">
          <div className="toolbar">
            <div className="field">
              <label htmlFor="delivery-date">Delivery date</label>
              <select
                id="delivery-date"
                value={deliveryDate}
                onChange={(e) => setDeliveryDate(e.target.value)}
                disabled={datesState.status !== "success"}
              >
                {datesState.status === "success" ? (
                  datesState.data.dates.map((d) => (
                    <option key={d.date} value={d.date}>
                      {d.date}
                      {d.complete ? "" : " (partial coverage)"}
                    </option>
                  ))
                ) : (
                  <option>Loading…</option>
                )}
              </select>
            </div>
            <div className="field">
              <label htmlFor="cutoff-hour">Day-ahead cutoff (UK time, day before)</label>
              <select
                id="cutoff-hour"
                value={cutoffHour}
                onChange={(e) => setCutoffHour(Number(e.target.value))}
              >
                {HOURS.map((h) => (
                  <option key={h} value={h}>
                    {String(h).padStart(2, "0")}:00
                  </option>
                ))}
              </select>
            </div>
          </div>
          {datesState.status === "error" ? (
            <div style={{ marginTop: "0.75rem" }}>
              <Banner variant="warn" role="alert">
                Could not load available dates: {datesState.message}
              </Banner>
            </div>
          ) : null}
        </Panel>

        {renderDecision(decisionState, cutoffHour, Boolean(deliveryDate))}
      </div>
    </main>
  );
}

function renderDecision(
  state: AsyncState<DecisionResponse>,
  cutoffHour: number,
  hasDate: boolean,
) {
  if (!hasDate || state.status === "loading") {
    return (
      <Panel title="Forecast vs actual">
        <LoadingState label="Loading decision data…" />
      </Panel>
    );
  }
  if (state.status === "error") {
    return (
      <Panel title="Forecast vs actual">
        <ErrorState message={state.message} httpStatus={state.httpStatus} />
      </Panel>
    );
  }
  return <DecisionResult data={state.data} cutoffHour={cutoffHour} />;
}

function DecisionResult({ data, cutoffHour }: { data: DecisionResponse; cutoffHour: number }) {
  const { summary, coverage, cutoff, periods } = data;

  const chartData = useMemo(
    () =>
      periods.map((p) => ({
        time: ukTime(p.hour_utc),
        forecast: p.forecast_mw,
        actual: p.actual_mean_mw,
      })),
    [periods],
  );

  const publishTimes = useMemo(() => {
    const set = new Set<string>();
    for (const p of periods) if (p.forecast_publish_time) set.add(p.forecast_publish_time);
    return Array.from(set).sort();
  }, [periods]);

  const cutoffLocal = cutoff.local_time
    ? ukDateTime(cutoff.utc_time ?? cutoff.local_time)
    : `${String(cutoffHour).padStart(2, "0")}:00`;

  return (
    <>
      <Banner variant="info">
        Selected forecast vintages were published on or before{" "}
        <strong>{cutoffLocal} UK</strong> ({cutoff.utc_time ?? "day-ahead cutoff"}).{" "}
        {cutoff.rule}
      </Banner>

      {!coverage.fully_covered ? (
        <Banner variant="warn" role="alert">
          <strong>Partial coverage.</strong> {coverage.matched_hours} of{" "}
          {coverage.expected_hours} hours have both a forecast and a complete actual.{" "}
          {coverage.missing_forecast_hours.length > 0 ? (
            <>
              Missing forecast: {coverage.missing_forecast_hours.length} hour(s).{" "}
            </>
          ) : null}
          {coverage.incomplete_actual_hours.length > 0 ? (
            <>Incomplete actual: {coverage.incomplete_actual_hours.length} hour(s). </>
          ) : null}
          Missing periods are shown as gaps — no values are interpolated.
        </Banner>
      ) : (
        <Banner variant="info">
          <strong>Full coverage.</strong> All {coverage.expected_hours} hours have a
          forecast and a complete half-hourly actual.
        </Banner>
      )}

      <div className="stat-grid">
        <StatCard
          label="Avg forecast"
          value={mw(summary.forecast.avg_mw)}
          sub={`over ${count(summary.forecast.hours_with_forecast)} h with a forecast`}
          tooltip="Mean of the selected hourly forecast values across the delivery day."
        />
        <StatCard
          label="Avg actual"
          value={mw(summary.actual.avg_mw)}
          sub={`over ${count(summary.actual.hours_complete)} complete h`}
          tooltip="Mean of the hourly actual generation (each the mean of two half-hourly observations)."
        />
        <StatCard
          label="Forecast energy"
          value={mwh(summary.forecast.total_mwh)}
          sub="sum of hourly forecast MW × 1 h"
          tooltip="Total forecast energy over the day, from hours that have a forecast."
        />
        <StatCard
          label="Actual energy"
          value={mwh(summary.actual.total_mwh_halfhourly_basis)}
          sub={`${count(summary.actual.half_hours_present)} half-hours present`}
          tooltip="Total actual energy from the native half-hourly data (MW × 0.5 h), the most precise basis."
        />
      </div>

      <Panel
        title="Forecast vs actual generation"
        hint="Hourly, UK local time · MW"
      >
        <div className="legend" style={{ marginBottom: "0.5rem" }}>
          <span className="legend__item">
            <span className="legend__swatch" style={{ background: FORECAST_COLOR }} />
            Selected forecast (WINDFOR, hourly)
          </span>
          <span className="legend__item">
            <span className="legend__swatch" style={{ background: ACTUAL_COLOR }} />
            Actual hourly mean (FUELHH, from 2 half-hours)
          </span>
        </div>
        <ResponsiveContainer width="100%" height={330}>
          <LineChart data={chartData} margin={{ top: 8, right: 16, bottom: 20, left: 8 }}>
            <CartesianGrid stroke="#eef2f7" vertical={false} />
            <XAxis
              dataKey="time"
              interval="preserveStartEnd"
              minTickGap={24}
              tickMargin={8}
              label={{ value: "Time (UK, Europe/London)", position: "insideBottom", offset: -12, fontSize: 12, fill: "#64748b" }}
            />
            <YAxis
              width={64}
              tickFormatter={(v: number) => v.toLocaleString("en-GB")}
              label={{ value: "MW", angle: -90, position: "insideLeft", fontSize: 12, fill: "#64748b" }}
            />
            <Tooltip content={<SeriesTooltip />} />
            <Legend wrapperStyle={{ display: "none" }} />
            <Line
              type="monotone"
              dataKey="forecast"
              name="Forecast"
              stroke={FORECAST_COLOR}
              strokeWidth={2}
              dot={false}
              connectNulls={false}
              isAnimationActive={false}
            />
            <Line
              type="monotone"
              dataKey="actual"
              name="Actual"
              stroke={ACTUAL_COLOR}
              strokeWidth={2}
              dot={false}
              connectNulls={false}
              isAnimationActive={false}
            />
          </LineChart>
        </ResponsiveContainer>
        <p className="chart-note">{data.granularity_note}</p>
      </Panel>

      <Panel
        title="Selected forecast vintages"
        hint={
          publishTimes.length > 0
            ? `${publishTimes.length} distinct publication time(s), all ≤ cutoff`
            : "no eligible forecast vintages"
        }
      >
        {publishTimes.length > 0 ? (
          <p className="panel__hint" style={{ padding: 0 }}>
            Published between <strong>{ukDateTime(publishTimes[0])}</strong> and{" "}
            <strong>{ukDateTime(publishTimes[publishTimes.length - 1])}</strong> (UK). Each
            hour below uses the latest vintage published by the cutoff.
          </p>
        ) : (
          <p className="panel__hint" style={{ padding: 0 }}>
            No forecast was published on or before the cutoff for this day.
          </p>
        )}
        <div className="table-wrap" style={{ marginTop: "0.75rem" }}>
          <table className="data">
            <thead>
              <tr>
                <th>Hour (UK)</th>
                <th>Forecast</th>
                <th>Actual (mean)</th>
                <th>Error (F−A)</th>
                <th>Vintage published (UK)</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {periods.map((p) => {
                const unmatched = !p.matched;
                return (
                  <tr key={p.hour_utc} className={unmatched ? "is-unmatched" : undefined}>
                    <td>{ukTime(p.hour_utc)}</td>
                    <td>{mw(p.forecast_mw)}</td>
                    <td>
                      {mw(p.actual_mean_mw)}
                      {!p.actual_complete ? (
                        <span className="cell-muted"> ({p.actual_n_half_hours}/2)</span>
                      ) : null}
                    </td>
                    <td>{signedMw(p.error_mw)}</td>
                    <td className={p.forecast_publish_time ? undefined : "cell-muted"}>
                      {ukDateTime(p.forecast_publish_time)}
                    </td>
                    <td>
                      {p.matched ? (
                        <span className="cell-muted">matched</span>
                      ) : p.forecast_mw === null ? (
                        <span style={{ color: "var(--warn)" }}>no forecast</span>
                      ) : (
                        <span style={{ color: "var(--warn)" }}>actual incomplete</span>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      </Panel>
    </>
  );
}

interface TooltipPayloadItem {
  dataKey: string;
  value: number | null;
  color: string;
}

function SeriesTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: TooltipPayloadItem[];
  label?: string;
}) {
  if (!active || !payload || payload.length === 0) return null;
  const find = (key: string) => payload.find((p) => p.dataKey === key)?.value ?? null;
  return (
    <div className="recharts-default-tooltip" style={{ background: "#fff", padding: "0.5rem 0.65rem" }}>
      <div style={{ fontWeight: 600, marginBottom: 4 }}>{label} UK</div>
      <div style={{ color: FORECAST_COLOR }}>Forecast: {mw(find("forecast"))}</div>
      <div style={{ color: ACTUAL_COLOR }}>Actual: {mw(find("actual"))}</div>
    </div>
  );
}
