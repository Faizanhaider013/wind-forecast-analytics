import { useMemo, useState } from "react";
import {
  Bar,
  CartesianGrid,
  ComposedChart,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { getAccuracy, getHorizon } from "../api/endpoints";
import type { AccuracyResponse, HorizonResponse } from "../api/types";
import { Banner, Panel } from "../components/Panel";
import { ErrorState, LoadingState } from "../components/States";
import { StatCard } from "../components/StatCard";
import { useAsync, type AsyncState } from "../hooks/useAsync";
import { count, mw, percent, signedMw } from "../utils/format";

const DEFAULT_FROM = "2026-01-01";
const DEFAULT_TO = "2026-01-31";
const MAE_COLOR = "#2563eb";
const RMSE_COLOR = "#7c3aed";
const COUNT_COLOR = "#94a3b8";
const HOURS = Array.from({ length: 24 }, (_, h) => h);

type HorizonMode = "all" | "cutoff";

export function AccuracyPage() {
  const [from, setFrom] = useState(DEFAULT_FROM);
  const [to, setTo] = useState(DEFAULT_TO);
  const [cutoffHour, setCutoffHour] = useState(10);
  const [horizonMode, setHorizonMode] = useState<HorizonMode>("all");

  const accuracy = useAsync(
    (signal) => getAccuracy(from, to, cutoffHour, signal),
    [from, to, cutoffHour],
  );
  const horizon = useAsync(
    (signal) =>
      getHorizon(from, to, horizonMode === "cutoff" ? cutoffHour : null, signal),
    [from, to, cutoffHour, horizonMode],
  );

  return (
    <main className="page">
      <div className="page__head">
        <h1>Forecast accuracy dashboard</h1>
        <p className="page__subtitle">
          How accurate the day-ahead wind forecasts were over a chosen period, plus
          how error grows with forecast lead time. Metrics are computed only from
          hours that have both an eligible forecast and a complete actual.
        </p>
      </div>

      <div className="stack">
        <Panel title="Period & cutoff">
          <div className="toolbar">
            <div className="field">
              <label htmlFor="from">From (delivery date)</label>
              <input id="from" type="date" value={from} onChange={(e) => setFrom(e.target.value)} />
            </div>
            <div className="field">
              <label htmlFor="to">To (delivery date)</label>
              <input id="to" type="date" value={to} onChange={(e) => setTo(e.target.value)} />
            </div>
            <div className="field">
              <label htmlFor="acc-cutoff">Day-ahead cutoff (UK time)</label>
              <select
                id="acc-cutoff"
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
        </Panel>

        {renderAccuracy(accuracy)}

        <HorizonPanel
          state={horizon}
          mode={horizonMode}
          onModeChange={setHorizonMode}
          cutoffHour={cutoffHour}
        />
      </div>
    </main>
  );
}

function renderAccuracy(state: AsyncState<AccuracyResponse>) {
  if (state.status === "loading") {
    return (
      <Panel title="Day-ahead accuracy">
        <LoadingState label="Loading accuracy metrics…" />
      </Panel>
    );
  }
  if (state.status === "error") {
    return (
      <Panel title="Day-ahead accuracy">
        <ErrorState message={state.message} httpStatus={state.httpStatus} />
      </Panel>
    );
  }
  return <AccuracyResult data={state.data} />;
}

function AccuracyResult({ data }: { data: AccuracyResponse }) {
  const { metrics, coverage, persistence_benchmark: pb } = data;

  if (metrics.n === 0) {
    return (
      <Panel title="Day-ahead accuracy" hint={`${data.from} → ${data.to}`}>
        <Banner variant="warn" role="status">
          No matched observations in this period, so accuracy metrics cannot be
          computed. {metrics.note ? metrics.note : null}
        </Banner>
      </Panel>
    );
  }

  // Skill is the server's paired value (model vs persistence over the same
  // hours), not model-whole-range ÷ persistence-subset.
  const skill = pb.included ? pb.skill_mae_percent : null;

  return (
    <Panel
      title="Day-ahead accuracy"
      hint={`${data.from} → ${data.to} · cutoff ${String(data.cutoff.hour_local).padStart(2, "0")}:00 ${data.cutoff.timezone}`}
    >
      <div className="stat-grid">
        <StatCard
          label="MAE"
          value={mw(metrics.mae_mw)}
          tooltip="Mean Absolute Error: the average size of the forecast error, in MW."
        />
        <StatCard
          label="RMSE"
          value={mw(metrics.rmse_mw)}
          tooltip="Root Mean Square Error, in MW. Penalises large misses more than MAE."
        />
        <StatCard
          label="Bias"
          value={signedMw(metrics.bias_mw)}
          sub={metrics.bias_mw !== null && metrics.bias_mw > 0 ? "forecasts over-predict" : metrics.bias_mw !== null && metrics.bias_mw < 0 ? "forecasts under-predict" : undefined}
          tooltip="Mean signed error (forecast − actual). Positive means the forecast over-predicts generation."
        />
        <StatCard
          label="WMAPE"
          value={percent(metrics.wmape_percent)}
          sub={metrics.wmape_percent === null ? metrics.note ?? "undefined" : undefined}
          tooltip="Weighted Mean Absolute Percentage Error = Σ|forecast−actual| ÷ Σ(actual). Undefined when total actual generation is zero."
        />
      </div>

      <div className="stat-grid" style={{ marginTop: "1rem" }}>
        <StatCard
          label="Matched observations"
          value={count(metrics.n)}
          sub={`of ${count(coverage.expected_hours)} expected hours`}
          muted
        />
        <StatCard
          label="Coverage"
          value={coverage.matched_fraction === null ? "—" : percent(coverage.matched_fraction * 100)}
          sub="hours matched ÷ expected"
          muted
        />
        <StatCard
          label="Excluded: no forecast"
          value={count(coverage.excluded_missing_forecast)}
          muted
        />
        <StatCard
          label="Excluded: incomplete actual"
          value={count(coverage.excluded_incomplete_actual)}
          muted
        />
      </div>

      {pb.included ? (
        <div style={{ marginTop: "1.25rem" }}>
          <h3 style={{ fontSize: "0.95rem", marginBottom: "0.5rem" }}>
            Forecast vs persistence benchmark
          </h3>
          <p className="panel__hint" style={{ padding: 0, marginBottom: "0.75rem" }}>
            {pb.definition}. Compared over the same {count(pb.n)} hours (those with a
            D-2 actual).
          </p>
          <div className="stat-grid">
            <StatCard
              label="Forecast MAE"
              value={mw(pb.model_mae_mw_same_sample)}
              sub="same hours"
              tooltip="The day-ahead forecast's MAE over exactly the hours the benchmark covers, for a fair head-to-head."
            />
            <StatCard label="Persistence MAE" value={mw(pb.mae_mw)} sub="same hours" muted />
            <StatCard label="Forecast RMSE" value={mw(pb.model_rmse_mw_same_sample)} sub="same hours" />
            <StatCard
              label="Skill vs persistence"
              value={skill === null ? "—" : percent(skill)}
              sub={skill !== null && skill > 0 ? "forecast beats persistence" : undefined}
              tooltip="1 − (forecast MAE ÷ persistence MAE) over the same hours. Positive means the day-ahead forecast is more accurate than naive persistence."
            />
          </div>
        </div>
      ) : (
        <div style={{ marginTop: "1rem" }}>
          <Banner variant="info">
            Persistence benchmark not available for this period
            {pb.note ? `: ${pb.note}` : "."}
          </Banner>
        </div>
      )}

      <Banner variant="info">
        <strong>Daily trend:</strong> the accuracy endpoint returns aggregate metrics
        for the whole period, not a per-day series. A daily breakdown is intentionally
        not shown here, as it would require one request per day; narrow the date range
        above to inspect shorter periods.
      </Banner>
    </Panel>
  );
}

function HorizonPanel({
  state,
  mode,
  onModeChange,
  cutoffHour,
}: {
  state: AsyncState<HorizonResponse>;
  mode: HorizonMode;
  onModeChange: (m: HorizonMode) => void;
  cutoffHour: number;
}) {
  const toggle = (
    <div className="toggle" role="group" aria-label="Horizon vintage selection">
      <button
        type="button"
        className="toggle__btn"
        aria-pressed={mode === "all"}
        onClick={() => onModeChange("all")}
      >
        All vintages (lead-time curve)
      </button>
      <button
        type="button"
        className="toggle__btn"
        aria-pressed={mode === "cutoff"}
        onClick={() => onModeChange("cutoff")}
      >
        Day-ahead eligible only
      </button>
    </div>
  );

  return (
    <Panel
      title="Accuracy by forecast horizon"
      hint="Error grouped by lead time = target − publication time"
      actions={toggle}
    >
      {state.status === "loading" ? (
        <LoadingState label="Loading horizon data…" />
      ) : state.status === "error" ? (
        <ErrorState message={state.message} httpStatus={state.httpStatus} />
      ) : (
        <HorizonResult data={state.data} mode={mode} cutoffHour={cutoffHour} />
      )}
    </Panel>
  );
}

function HorizonResult({
  data,
  mode,
  cutoffHour,
}: {
  data: HorizonResponse;
  mode: HorizonMode;
  cutoffHour: number;
}) {
  const chartData = useMemo(
    () =>
      data.buckets.map((b) => ({
        bucket: b.bucket,
        mae: b.mae_mw,
        rmse: b.rmse_mw,
        n: b.n,
      })),
    [data.buckets],
  );

  const scored = data.buckets.filter((b) => b.n > 0).length;

  return (
    <>
      <Banner variant={mode === "cutoff" ? "info" : "warn"} role="status">
        {mode === "cutoff" ? (
          <>
            <strong>Day-ahead eligible only.</strong> Showing vintages available at each
            target's {String(cutoffHour).padStart(2, "0")}:00 UK cutoff (never future
            vintages). {data.excluded_after_cutoff > 0 ? `${count(data.excluded_after_cutoff)} later vintage(s) excluded. ` : ""}
          </>
        ) : (
          <>
            <strong>All vintages by lead time.</strong> This is <em>not</em> the single
            day-ahead selection — it groups every stored vintage by its own lead time to
            show how error changes with horizon.
          </>
        )}
      </Banner>

      {scored === 0 ? (
        <Banner variant="warn" role="status">
          No scored vintages in this period (no complete actuals to match against).
        </Banner>
      ) : (
        <>
          <div className="legend" style={{ margin: "0.75rem 0 0.25rem" }}>
            <span className="legend__item">
              <span className="legend__swatch" style={{ background: MAE_COLOR }} />
              MAE (MW)
            </span>
            <span className="legend__item">
              <span className="legend__swatch" style={{ background: RMSE_COLOR }} />
              RMSE (MW)
            </span>
            <span className="legend__item">
              <span className="legend__swatch" style={{ background: COUNT_COLOR }} />
              Sample count
            </span>
          </div>
          <ResponsiveContainer width="100%" height={330}>
            <ComposedChart data={chartData} margin={{ top: 8, right: 16, bottom: 20, left: 8 }}>
              <CartesianGrid stroke="#eef2f7" vertical={false} />
              <XAxis
                dataKey="bucket"
                tickMargin={8}
                label={{ value: "Lead time (hours)", position: "insideBottom", offset: -12, fontSize: 12, fill: "#64748b" }}
              />
              <YAxis
                yAxisId="mw"
                width={64}
                tickFormatter={(v: number) => v.toLocaleString("en-GB")}
                label={{ value: "Error (MW)", angle: -90, position: "insideLeft", fontSize: 12, fill: "#64748b" }}
              />
              <YAxis
                yAxisId="n"
                orientation="right"
                width={56}
                tickFormatter={(v: number) => v.toLocaleString("en-GB")}
                label={{ value: "Samples", angle: 90, position: "insideRight", fontSize: 12, fill: "#64748b" }}
              />
              <Tooltip content={<HorizonTooltip />} />
              <Bar yAxisId="n" dataKey="n" name="Samples" fill={COUNT_COLOR} opacity={0.35} barSize={26} />
              <Line yAxisId="mw" type="monotone" dataKey="mae" name="MAE" stroke={MAE_COLOR} strokeWidth={2} connectNulls={false} dot isAnimationActive={false} />
              <Line yAxisId="mw" type="monotone" dataKey="rmse" name="RMSE" stroke={RMSE_COLOR} strokeWidth={2} strokeDasharray="5 4" connectNulls={false} dot isAnimationActive={false} />
            </ComposedChart>
          </ResponsiveContainer>
        </>
      )}

      <p className="chart-note">{data.horizon_convention}</p>

      <div className="table-wrap" style={{ marginTop: "0.75rem" }}>
        <table className="data">
          <thead>
            <tr>
              <th>Lead-time bucket</th>
              <th>Samples</th>
              <th>MAE</th>
              <th>RMSE</th>
              <th>Bias</th>
            </tr>
          </thead>
          <tbody>
            {data.buckets.map((b) => (
              <tr key={b.bucket}>
                <td>{b.bucket}</td>
                <td>{count(b.n)}</td>
                <td>{mw(b.mae_mw)}</td>
                <td>{mw(b.rmse_mw)}</td>
                <td>{signedMw(b.bias_mw)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="chart-note">
        Total scored vintages: {count(data.total_scored_vintages)}.
      </p>
    </>
  );
}

interface HorizonPayloadItem {
  dataKey: string;
  value: number | null;
}

function HorizonTooltip({
  active,
  payload,
  label,
}: {
  active?: boolean;
  payload?: HorizonPayloadItem[];
  label?: string;
}) {
  if (!active || !payload || payload.length === 0) return null;
  const find = (key: string) => payload.find((p) => p.dataKey === key)?.value ?? null;
  return (
    <div className="recharts-default-tooltip" style={{ background: "#fff", padding: "0.5rem 0.65rem" }}>
      <div style={{ fontWeight: 600, marginBottom: 4 }}>{label} lead time</div>
      <div style={{ color: MAE_COLOR }}>MAE: {mw(find("mae"))}</div>
      <div style={{ color: RMSE_COLOR }}>RMSE: {mw(find("rmse"))}</div>
      <div style={{ color: "#475569" }}>Samples: {count(find("n"))}</div>
    </div>
  );
}
