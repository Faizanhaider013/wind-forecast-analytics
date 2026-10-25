"""Decision-support and forecast-accuracy analytics over the ingested data.

Pure, database-driven functions with no FastAPI or network dependencies, so the
whole module is testable offline against an in-memory SQLite database.

Conventions used throughout:

* All timestamps stored in SQLite are canonical UTC strings
  ``YYYY-MM-DDTHH:MM:SSZ`` (fixed width), so lexicographic string comparison is
  identical to chronological comparison -- this is relied on in WHERE clauses.
* A "delivery day" is a **UK calendar day** (``Europe/London``). Its hourly
  targets are the UTC instants of that local day (23, 24, or 25 hours across DST
  transitions). January 2026 is wholly GMT, so for the ingested data a UK day
  equals the UTC day.
* Actuals are half-hourly; WINDFOR forecasts are hourly. The two native
  granularities are never silently merged: an hourly actual is formed only by
  averaging the **two** half-hourly observations in that hour, and an hour with
  fewer than two present observations is reported as incomplete rather than
  imputed.
* Signed error is ``forecast - actual`` (MW); a positive error / bias means the
  forecast **over**predicts.
"""

from __future__ import annotations

import math
import sqlite3
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from .ingestion import timeutils

LONDON = ZoneInfo("Europe/London")
WIND = "WIND"

DEFAULT_CUTOFF_HOUR = 10
DEFAULT_CUTOFF_DAYS_BEFORE = 1
PERSISTENCE_LAG_DAYS = 2  # see persistence_benchmark()

# Half-open lead-time buckets for the horizon endpoint, in hours. "<0h" holds
# vintages published at or after their target time (WINDFOR re-publishes recent
# hours). The final bucket is open-ended.
HORIZON_BUCKETS: list[tuple[str, float, float]] = [
    ("<0h", -math.inf, 0.0),
    ("0-6h", 0.0, 6.0),
    ("6-12h", 6.0, 12.0),
    ("12-18h", 12.0, 18.0),
    ("18-24h", 18.0, 24.0),
    ("24-36h", 24.0, 36.0),
    ("36-48h", 36.0, 48.0),
    ("48h+", 48.0, math.inf),
]


# --- time helpers ------------------------------------------------------------


def parse_date(value: str) -> date:
    """Parse a ``YYYY-MM-DD`` string, raising ValueError on anything else."""
    text = (value or "").strip()
    if len(text) != 10:
        raise ValueError(f"date must be YYYY-MM-DD, got {value!r}")
    return date.fromisoformat(text)


def compute_cutoff_utc(
    delivery_date: date,
    cutoff_hour: int = DEFAULT_CUTOFF_HOUR,
    *,
    days_before: int = DEFAULT_CUTOFF_DAYS_BEFORE,
    tz: ZoneInfo = LONDON,
) -> datetime:
    """Return the UTC cutoff instant for a delivery date.

    The cutoff is ``cutoff_hour`` local (Europe/London) time on the day
    ``days_before`` before delivery. Interpreting the wall-clock time in London
    and converting to UTC makes DST explicit: e.g. 10:00 the day before a summer
    delivery date is 09:00 UTC, but 10:00 UTC in winter.
    """
    if not 0 <= cutoff_hour <= 23:
        raise ValueError(f"cutoff_hour must be 0..23, got {cutoff_hour}")
    local_day = delivery_date - timedelta(days=days_before)
    local = datetime(
        local_day.year, local_day.month, local_day.day, cutoff_hour, tzinfo=tz
    )
    return local.astimezone(timezone.utc)


def delivery_day_utc_window(
    delivery_date: date, *, tz: ZoneInfo = LONDON
) -> tuple[datetime, datetime]:
    """UTC ``[start, end)`` bounds of a UK local calendar day (DST-aware)."""
    nxt = delivery_date + timedelta(days=1)
    start_local = datetime(
        delivery_date.year, delivery_date.month, delivery_date.day, tzinfo=tz
    )
    end_local = datetime(nxt.year, nxt.month, nxt.day, tzinfo=tz)
    return start_local.astimezone(timezone.utc), end_local.astimezone(timezone.utc)


def _hourly_targets(start_utc: datetime, end_utc: datetime) -> list[str]:
    """Canonical hourly target strings in ``[start, end)`` (UTC)."""
    out: list[str] = []
    cur = start_utc
    while cur < end_utc:
        out.append(timeutils.to_canonical_z(cur))
        cur += timedelta(hours=1)
    return out


# --- data access -------------------------------------------------------------


@dataclass
class HourlyActual:
    """Hourly aggregate of the half-hourly actuals in one UTC hour."""

    hour_utc: str
    n_half_hours: int           # present (non-null) half-hourly observations, 0..2
    mean_mw: float | None       # mean MW only when both half-hours are present
    complete: bool              # both half-hourly observations present


def hourly_actual_means(
    conn: sqlite3.Connection, start_utc: datetime, end_utc: datetime, *, fuel: str = WIND
) -> dict[str, HourlyActual]:
    """Aggregate half-hourly actuals into hourly means, keyed by UTC hour.

    An hour is ``complete`` only when both of its half-hourly observations are
    present; otherwise ``mean_mw`` is ``None`` (never imputed). One parameterised
    GROUP BY query -- no per-hour queries.
    """
    start_z = timeutils.to_canonical_z(start_utc)
    end_z = timeutils.to_canonical_z(end_utc)
    rows = conn.execute(
        """
        SELECT substr(target_start_time, 1, 13) AS hour_prefix,
               COUNT(generation_mw)             AS n_present,
               AVG(generation_mw)               AS mean_mw
        FROM actuals
        WHERE target_start_time >= ? AND target_start_time < ? AND fuel_type = ?
        GROUP BY hour_prefix
        """,
        (start_z, end_z, fuel),
    ).fetchall()
    result: dict[str, HourlyActual] = {}
    for r in rows:
        hour = f"{r['hour_prefix']}:00:00Z"
        n = r["n_present"]
        complete = n >= 2
        result[hour] = HourlyActual(
            hour_utc=hour,
            n_half_hours=n,
            mean_mw=float(r["mean_mw"]) if complete and r["mean_mw"] is not None else None,
            complete=complete,
        )
    return result


def select_eligible_forecasts(
    conn: sqlite3.Connection,
    start_utc: datetime,
    end_utc: datetime,
    cutoff_utc: datetime,
) -> dict[str, tuple[str, int]]:
    """Latest forecast vintage per target with ``publish_time <= cutoff``.

    Returns ``{target_utc: (publish_time, generation_mw)}``. A single windowed
    query selects the most recently published eligible vintage for each target,
    so a forecast published after the cutoff is never used.
    """
    start_z = timeutils.to_canonical_z(start_utc)
    end_z = timeutils.to_canonical_z(end_utc)
    cutoff_z = timeutils.to_canonical_z(cutoff_utc)
    rows = conn.execute(
        """
        SELECT target_start_time, publish_time, generation_mw
        FROM (
            SELECT target_start_time, publish_time, generation_mw,
                   ROW_NUMBER() OVER (
                       PARTITION BY target_start_time ORDER BY publish_time DESC
                   ) AS rn
            FROM forecast_vintages
            WHERE target_start_time >= ? AND target_start_time < ?
              AND publish_time <= ?
        )
        WHERE rn = 1
        """,
        (start_z, end_z, cutoff_z),
    ).fetchall()
    return {r["target_start_time"]: (r["publish_time"], r["generation_mw"]) for r in rows}


# --- decision ----------------------------------------------------------------


@dataclass
class DecisionPeriod:
    hour_utc: str
    forecast_mw: int | None
    forecast_publish_time: str | None
    actual_mean_mw: float | None
    actual_n_half_hours: int
    actual_complete: bool
    error_mw: float | None           # forecast - actual (positive => overpredict)
    matched: bool                    # forecast present AND actual complete


def build_decision(
    conn: sqlite3.Connection,
    delivery_date: date,
    cutoff_hour: int = DEFAULT_CUTOFF_HOUR,
) -> dict:
    """Build the day-ahead decision payload for one delivery date."""
    cutoff_utc = compute_cutoff_utc(delivery_date, cutoff_hour)
    start_utc, end_utc = delivery_day_utc_window(delivery_date)
    targets = _hourly_targets(start_utc, end_utc)

    forecasts = select_eligible_forecasts(conn, start_utc, end_utc, cutoff_utc)
    actuals = hourly_actual_means(conn, start_utc, end_utc)

    periods: list[DecisionPeriod] = []
    missing_forecast: list[str] = []
    incomplete_actual: list[str] = []

    for hour in targets:
        fc = forecasts.get(hour)
        fc_mw = fc[1] if fc else None
        fc_pub = fc[0] if fc else None
        act = actuals.get(hour)
        act_mean = act.mean_mw if act else None
        act_n = act.n_half_hours if act else 0
        act_complete = bool(act and act.complete)

        if fc is None:
            missing_forecast.append(hour)
        if not act_complete:
            incomplete_actual.append(hour)

        matched = fc_mw is not None and act_complete and act_mean is not None
        error = (fc_mw - act_mean) if matched else None
        periods.append(
            DecisionPeriod(
                hour_utc=hour,
                forecast_mw=fc_mw,
                forecast_publish_time=fc_pub,
                actual_mean_mw=act_mean,
                actual_n_half_hours=act_n,
                actual_complete=act_complete,
                error_mw=error,
                matched=matched,
            )
        )

    # Summaries. MW averages and MWh totals are computed only over the periods
    # that actually carry a value; coverage counts are reported alongside so
    # incomplete days are transparent.
    fc_values = [p.forecast_mw for p in periods if p.forecast_mw is not None]
    act_values = [p.actual_mean_mw for p in periods if p.actual_mean_mw is not None]

    # Native half-hourly energy (0.5h per observation) for a more accurate total.
    start_z = timeutils.to_canonical_z(start_utc)
    end_z = timeutils.to_canonical_z(end_utc)
    hh = conn.execute(
        """
        SELECT COUNT(generation_mw) AS n, SUM(generation_mw) AS total_mw
        FROM actuals
        WHERE target_start_time >= ? AND target_start_time < ? AND fuel_type = ?
        """,
        (start_z, end_z, WIND),
    ).fetchone()
    actual_mwh_halfhourly = (hh["total_mw"] * 0.5) if hh["total_mw"] is not None else 0.0

    summary = {
        "forecast": {
            "avg_mw": round(sum(fc_values) / len(fc_values), 3) if fc_values else None,
            # Each hourly MW value spans one hour, so MW summed == MWh.
            "total_mwh": round(float(sum(fc_values)), 3) if fc_values else 0.0,
            "hours_with_forecast": len(fc_values),
        },
        "actual": {
            "avg_mw": round(sum(act_values) / len(act_values), 3) if act_values else None,
            "total_mwh_hourly_basis": round(float(sum(act_values)), 3) if act_values else 0.0,
            "total_mwh_halfhourly_basis": round(actual_mwh_halfhourly, 3),
            "hours_complete": len(act_values),
            "half_hours_present": hh["n"] or 0,
        },
    }

    matched_hours = sum(1 for p in periods if p.matched)
    coverage = {
        "expected_hours": len(targets),
        "forecast_hours_present": len(fc_values),
        "actual_hours_complete": len(act_values),
        "matched_hours": matched_hours,
        "missing_forecast_hours": missing_forecast,
        "incomplete_actual_hours": incomplete_actual,
        "fully_covered": matched_hours == len(targets) and len(targets) > 0,
    }

    return {
        "delivery_date": delivery_date.isoformat(),
        "cutoff": {
            "hour_local": cutoff_hour,
            "timezone": "Europe/London",
            "local_time": _local_iso(cutoff_utc),
            "utc_time": timeutils.to_canonical_z(cutoff_utc),
            "rule": f"{cutoff_hour:02d}:00 Europe/London on the day "
            f"{DEFAULT_CUTOFF_DAYS_BEFORE} before delivery; "
            f"forecasts published after this instant are excluded",
        },
        "granularity_note": (
            "Forecasts are hourly (WINDFOR). Actuals are half-hourly (FUELHH) and "
            "are aggregated to an hourly mean MW from the two half-hourly "
            "observations in each hour; hours with fewer than two observations "
            "are reported incomplete and not imputed."
        ),
        "periods": [asdict(p) for p in periods],
        "summary": summary,
        "coverage": coverage,
    }


def _local_iso(dt_utc: datetime) -> str:
    return dt_utc.astimezone(LONDON).strftime("%Y-%m-%dT%H:%M:%S%z")


# --- metrics -----------------------------------------------------------------


def compute_metrics(pairs: list[tuple[float, float]]) -> dict:
    """Error metrics for ``(forecast, actual)`` MW pairs.

    WMAPE = sum(|forecast-actual|) / sum(actual). Actual wind generation is
    non-negative, so the denominator is sum(actual); when it is zero WMAPE is
    undefined and returned as ``None`` with an explanatory note.
    """
    n = len(pairs)
    if n == 0:
        return {
            "n": 0,
            "mae_mw": None,
            "rmse_mw": None,
            "bias_mw": None,
            "wmape_fraction": None,
            "wmape_percent": None,
            "sum_actual_mw": 0.0,
            "note": "no matched observations",
        }
    errors = [f - a for f, a in pairs]
    abs_errors = [abs(e) for e in errors]
    sq_errors = [e * e for e in errors]
    sum_actual = sum(a for _, a in pairs)
    mae = sum(abs_errors) / n
    rmse = math.sqrt(sum(sq_errors) / n)
    bias = sum(errors) / n
    if sum_actual > 0:
        wmape = sum(abs_errors) / sum_actual
        wmape_pct = wmape * 100.0
        note = None
    else:
        wmape = None
        wmape_pct = None
        note = "WMAPE undefined: total actual generation is zero"
    return {
        "n": n,
        "mae_mw": round(mae, 3),
        "rmse_mw": round(rmse, 3),
        "bias_mw": round(bias, 3),  # positive => forecast overpredicts
        "wmape_fraction": round(wmape, 5) if wmape is not None else None,
        "wmape_percent": round(wmape_pct, 3) if wmape_pct is not None else None,
        "sum_actual_mw": round(float(sum_actual), 3),
        "note": note,
    }


def _date_range(from_date: date, to_date: date) -> list[date]:
    if to_date < from_date:
        raise ValueError("'to' date must not be before 'from' date")
    out = []
    cur = from_date
    while cur <= to_date:
        out.append(cur)
        cur += timedelta(days=1)
    return out


def build_accuracy(
    conn: sqlite3.Connection,
    from_date: date,
    to_date: date,
    cutoff_hour: int = DEFAULT_CUTOFF_HOUR,
) -> dict:
    """Accuracy metrics over a date range using the day-ahead cutoff selection.

    For each delivery date the same cutoff rule picks the latest eligible
    vintage per hour; only hours with both an eligible forecast and a complete
    hourly actual are scored. Exclusions and coverage are reported.
    """
    dates = _date_range(from_date, to_date)
    matched: list[tuple[float, float]] = []
    persistence_pairs: list[tuple[float, float]] = []
    # The model's own pairs restricted to the hours where a persistence value
    # also exists, so the forecast-vs-persistence comparison is on one sample.
    model_on_persistence_subset: list[tuple[float, float]] = []

    expected_hours = 0
    missing_forecast = 0
    incomplete_actual = 0

    for d in dates:
        cutoff_utc = compute_cutoff_utc(d, cutoff_hour)
        start_utc, end_utc = delivery_day_utc_window(d)
        targets = _hourly_targets(start_utc, end_utc)
        expected_hours += len(targets)

        forecasts = select_eligible_forecasts(conn, start_utc, end_utc, cutoff_utc)
        actuals = hourly_actual_means(conn, start_utc, end_utc)

        # D-2 actuals supply the persistence benchmark (see persistence note).
        p_start, p_end = delivery_day_utc_window(d - timedelta(days=PERSISTENCE_LAG_DAYS))
        persistence = hourly_actual_means(conn, p_start, p_end)

        for hour in targets:
            fc = forecasts.get(hour)
            act = actuals.get(hour)
            # A vintage row with a null generation value carries no usable
            # forecast, so it is treated as missing (consistent with the
            # decision builder) rather than crashing on float(None).
            if fc is None or fc[1] is None:
                missing_forecast += 1
            if act is None or not act.complete:
                incomplete_actual += 1
            if (
                fc is not None
                and fc[1] is not None
                and act is not None
                and act.complete
                and act.mean_mw is not None
            ):
                matched.append((float(fc[1]), act.mean_mw))
                # Persistence: same hour-of-day, PERSISTENCE_LAG_DAYS earlier.
                shifted = timeutils.to_canonical_z(
                    timeutils.parse_utc(hour) - timedelta(days=PERSISTENCE_LAG_DAYS)
                )
                p_act = persistence.get(shifted)
                if p_act is not None and p_act.complete and p_act.mean_mw is not None:
                    persistence_pairs.append((p_act.mean_mw, act.mean_mw))
                    model_on_persistence_subset.append((float(fc[1]), act.mean_mw))

    metrics = compute_metrics(matched)
    persistence = persistence_benchmark(persistence_pairs, model_on_persistence_subset)

    return {
        "from": from_date.isoformat(),
        "to": to_date.isoformat(),
        "cutoff": {
            "hour_local": cutoff_hour,
            "timezone": "Europe/London",
            "rule": f"{cutoff_hour:02d}:00 Europe/London on the day before each "
            "delivery date; future vintages are never used",
        },
        "metrics": metrics,
        "persistence_benchmark": persistence,
        "coverage": {
            "expected_hours": expected_hours,
            "matched_hours": metrics["n"],
            "excluded_missing_forecast": missing_forecast,
            "excluded_incomplete_actual": incomplete_actual,
            "matched_fraction": round(metrics["n"] / expected_hours, 5)
            if expected_hours
            else None,
        },
    }


def persistence_benchmark(
    pairs: list[tuple[float, float]],
    model_subset_pairs: list[tuple[float, float]] | None = None,
) -> dict:
    """Metrics for the D-2 same-hour persistence benchmark.

    Definition: the naive forecast for delivery hour *h* is the actual hourly
    mean at the same hour-of-day two days earlier. Two days back is the most
    recent calendar day that is *fully observed* at any previous-day cutoff, so
    this is a defensible, strictly-historical day-ahead baseline that never uses
    future information. It is reported only over hours where that prior actual
    exists; hours without it (e.g. the first two days of the ingested month) are
    excluded and reflected in ``n``.

    ``model_subset_pairs`` are the day-ahead forecast's own (forecast, actual)
    pairs for exactly the same hours the benchmark covers. They let the skill be
    computed as a **paired** comparison on one sample, rather than dividing the
    model's whole-range MAE by the benchmark's smaller-sample MAE (which would
    mix two different samples). ``skill_mae_percent`` = 1 - model_MAE / persistence_MAE
    on that common sample; positive means the forecast beats persistence.
    """
    base = compute_metrics(pairs)
    base["definition"] = (
        "naive forecast = actual hourly mean at the same hour-of-day two days "
        "earlier (latest fully-observed day at a previous-day cutoff)"
    )
    base["included"] = base["n"] > 0

    # Paired model metrics on the identical hours (honest head-to-head).
    model_same = compute_metrics(model_subset_pairs or [])
    base["model_mae_mw_same_sample"] = model_same["mae_mw"]
    base["model_rmse_mw_same_sample"] = model_same["rmse_mw"]
    if base["mae_mw"] and base["mae_mw"] > 0 and model_same["mae_mw"] is not None:
        base["skill_mae_percent"] = round((1 - model_same["mae_mw"] / base["mae_mw"]) * 100, 3)
    else:
        base["skill_mae_percent"] = None
    base["comparison_note"] = (
        "MAE/RMSE and skill compare the forecast and persistence over the same "
        f"{base['n']} hours (the hours with a D-2 actual)."
    )

    if base["n"] == 0:
        base["note"] = (
            "omitted: no delivery hour in range had an actual two days earlier "
            "in the database to form the benchmark"
        )
    return base


# --- horizon -----------------------------------------------------------------


def build_horizon(
    conn: sqlite3.Connection,
    from_date: date,
    to_date: date,
    cutoff_hour: int | None = None,
) -> dict:
    """Forecast error by lead-time bucket across vintages in the range.

    Lead time (horizon) = ``target_start_time - publish_time``. This endpoint
    characterises forecast skill as a function of lead time, so it is
    deliberately NOT the day-ahead selection used by ``/api/decision`` and
    ``/api/accuracy`` -- labelling it day-ahead would misrepresent it.

    ``cutoff_hour`` is optional:

    * ``None`` (default) scores **every** stored vintage by its own lead time --
      the true horizon curve, with lead times from negative (re-published recent
      hours) up to the full forecast horizon.
    * An integer restricts to vintages that were available at each target's
      day-ahead cutoff (``publish_time <= cutoff``); this never uses future
      vintages but biases buckets toward longer lead times, so it is opt-in.

    Errors are scored only against complete hourly actuals. One JOIN query.
    """
    _date_range(from_date, to_date)  # validation (ordering)
    if cutoff_hour is not None and not 0 <= cutoff_hour <= 23:
        raise ValueError(f"cutoff_hour must be 0..23, got {cutoff_hour}")
    start_utc, _ = delivery_day_utc_window(from_date)
    _, end_utc = delivery_day_utc_window(to_date)
    start_z = timeutils.to_canonical_z(start_utc)
    end_z = timeutils.to_canonical_z(end_utc)

    rows = conn.execute(
        """
        SELECT fv.target_start_time AS target,
               fv.publish_time      AS publish,
               fv.generation_mw     AS forecast_mw,
               a.mean_mw            AS actual_mw
        FROM forecast_vintages fv
        JOIN (
            SELECT substr(target_start_time, 1, 13) AS hp,
                   AVG(generation_mw)               AS mean_mw,
                   COUNT(generation_mw)             AS n_present
            FROM actuals
            WHERE fuel_type = ?
            GROUP BY hp
            HAVING n_present >= 2
        ) a ON substr(fv.target_start_time, 1, 13) = a.hp
        WHERE fv.target_start_time >= ? AND fv.target_start_time < ?
        """,
        (WIND, start_z, end_z),
    ).fetchall()

    buckets: dict[str, list[tuple[float, float]]] = {name: [] for name, _, _ in HORIZON_BUCKETS}
    excluded_future = 0
    excluded_null_forecast = 0
    for r in rows:
        if r["forecast_mw"] is None:
            # A stored vintage may carry a null generation value (the WINDFOR
            # feed can omit it, and the schema allows it). Without a forecast
            # value there is no error to score, so it is excluded, never imputed.
            excluded_null_forecast += 1
            continue
        target_dt = timeutils.parse_utc(r["target"])
        publish_dt = timeutils.parse_utc(r["publish"])
        if cutoff_hour is not None:
            # Only vintages available at this target's day-ahead cutoff.
            target_local_day = target_dt.astimezone(LONDON).date()
            cutoff_utc = compute_cutoff_utc(target_local_day, cutoff_hour)
            if publish_dt > cutoff_utc:
                excluded_future += 1
                continue
        lead_h = (target_dt - publish_dt).total_seconds() / 3600.0
        name = _bucket_for(lead_h)
        buckets[name].append((float(r["forecast_mw"]), float(r["actual_mw"])))

    out_buckets = []
    for name, lo, hi in HORIZON_BUCKETS:
        m = compute_metrics(buckets[name])
        out_buckets.append(
            {
                "bucket": name,
                "lead_hours_from": None if lo == -math.inf else lo,
                "lead_hours_to": None if hi == math.inf else hi,
                "n": m["n"],
                "mae_mw": m["mae_mw"],
                "rmse_mw": m["rmse_mw"],
                "bias_mw": m["bias_mw"],
            }
        )

    return {
        "from": from_date.isoformat(),
        "to": to_date.isoformat(),
        "cutoff_hour": cutoff_hour,
        "cutoff_applied": cutoff_hour is not None,
        "horizon_convention": (
            "lead time = target delivery time minus forecast publication time, "
            "in hours. Buckets are half-open [from, to). The '<0h' bucket holds "
            "vintages published at or after their target (WINDFOR re-publishes "
            "recent hours). These are stored vintages grouped by their own lead "
            "time -- not the single day-ahead selected forecast. "
            + (
                f"Restricted to vintages available at each target's "
                f"{cutoff_hour:02d}:00 Europe/London day-ahead cutoff."
                if cutoff_hour is not None
                else "All stored vintages are included (no cutoff applied)."
            )
        ),
        "excluded_after_cutoff": excluded_future,
        "excluded_null_forecast": excluded_null_forecast,
        "buckets": out_buckets,
        "total_scored_vintages": sum(b["n"] for b in out_buckets),
    }


def _bucket_for(lead_hours: float) -> str:
    for name, lo, hi in HORIZON_BUCKETS:
        if lo <= lead_hours < hi:
            return name
    return HORIZON_BUCKETS[-1][0]  # pragma: no cover - inf upper guards this


# --- available dates ---------------------------------------------------------


def available_dates(conn: sqlite3.Connection) -> dict:
    """Per-date coverage for actuals and forecasts.

    Dates are keyed by UK settlement date for actuals and by the UTC calendar
    date of the target for forecasts (equal for the ingested GMT month). Each
    date reports whether its actual (48 half-hours) and forecast (24 hourly
    targets) coverage is complete, so the frontend can distinguish complete from
    partial dates.
    """
    actual_rows = conn.execute(
        """
        SELECT settlement_date AS d,
               COUNT(generation_mw) AS n_present
        FROM actuals
        WHERE fuel_type = ?
        GROUP BY settlement_date
        """,
        (WIND,),
    ).fetchall()
    forecast_rows = conn.execute(
        """
        SELECT substr(target_start_time, 1, 10)   AS d,
               COUNT(DISTINCT target_start_time)   AS target_hours,
               COUNT(*)                            AS vintages
        FROM forecast_vintages
        GROUP BY d
        """
    ).fetchall()

    actual_by_date = {r["d"]: r["n_present"] for r in actual_rows}
    forecast_by_date = {r["d"]: (r["target_hours"], r["vintages"]) for r in forecast_rows}

    all_dates = sorted(set(actual_by_date) | set(forecast_by_date))
    expected_half_hours = 48
    expected_hours = 24

    entries = []
    for d in all_dates:
        n_act = actual_by_date.get(d, 0)
        fc_hours, fc_vintages = forecast_by_date.get(d, (0, 0))
        act_complete = n_act >= expected_half_hours
        fc_complete = fc_hours >= expected_hours
        entries.append(
            {
                "date": d,
                "actuals": {
                    "half_hour_periods": n_act,
                    "expected": expected_half_hours,
                    "complete": act_complete,
                },
                "forecasts": {
                    "target_hours": fc_hours,
                    "expected": expected_hours,
                    "vintages": fc_vintages,
                    "complete": fc_complete,
                },
                "complete": act_complete and fc_complete,
            }
        )

    return {
        "dates": entries,
        "summary": {
            "total_dates": len(entries),
            "complete_dates": sum(1 for e in entries if e["complete"]),
            "actuals_complete_dates": sum(1 for e in entries if e["actuals"]["complete"]),
            "forecasts_complete_dates": sum(
                1 for e in entries if e["forecasts"]["complete"]
            ),
        },
    }
