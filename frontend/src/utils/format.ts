// Formatting helpers. Timestamps are rendered in UK local time (Europe/London)
// because the product is for a UK buying team; the backend stores UTC.

const UK_TZ = "Europe/London";

const timeFmt = new Intl.DateTimeFormat("en-GB", {
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
  timeZone: UK_TZ,
});

const dateTimeFmt = new Intl.DateTimeFormat("en-GB", {
  day: "2-digit",
  month: "short",
  hour: "2-digit",
  minute: "2-digit",
  hour12: false,
  timeZone: UK_TZ,
});

/** "HH:mm" in UK local time for an ISO UTC timestamp. */
export function ukTime(iso: string): string {
  return timeFmt.format(new Date(iso));
}

/** "dd Mon HH:mm" in UK local time for an ISO UTC timestamp. */
export function ukDateTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  return dateTimeFmt.format(new Date(iso));
}

/** Format a MW value, or an em dash when the value is missing. */
export function mw(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return `${value.toLocaleString("en-GB", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })} MW`;
}

/** Format a MWh value, or an em dash when the value is missing. */
export function mwh(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return `${value.toLocaleString("en-GB", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })} MWh`;
}

/** Format a percentage (already in percent units), or an em dash. */
export function percent(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return `${value.toLocaleString("en-GB", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })}%`;
}

/** Plain integer with thousands separators, or em dash. */
export function count(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  return value.toLocaleString("en-GB");
}

/** A signed MW value with explicit +/- sign (for bias/error), or em dash. */
export function signedMw(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "—";
  const sign = value > 0 ? "+" : "";
  return `${sign}${value.toLocaleString("en-GB", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  })} MW`;
}
