import { InfoTip } from "./InfoTip";

/**
 * A single KPI card. `value` is pre-formatted (callers use the format helpers
 * so a missing value renders as an em dash rather than a fabricated number).
 */
export function StatCard({
  label,
  value,
  sub,
  tooltip,
  muted,
}: {
  label: string;
  value: string;
  sub?: string;
  tooltip?: string;
  muted?: boolean;
}) {
  return (
    <div className="stat">
      <div className="stat__label">
        <span>{label}</span>
        {tooltip ? <InfoTip text={tooltip} label={label} /> : null}
      </div>
      <div className={muted ? "stat__value stat__value--muted" : "stat__value"}>{value}</div>
      {sub ? <div className="stat__sub">{sub}</div> : null}
    </div>
  );
}
