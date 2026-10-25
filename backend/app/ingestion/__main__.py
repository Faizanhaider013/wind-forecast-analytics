"""CLI for Phase 1 Elexon ingestion.

Run from the repository root, ideally via Docker Compose:

    docker compose run --rm backend python -m app.ingestion

or locally (from ``backend/`` with the venv active):

    python -m app.ingestion --target-month 2026-01

This is deliberately separate from the FastAPI app: starting the API never
triggers a download.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import config, pipeline
from .elexon_client import ElexonAPIError
from .pipeline import RunResult


def _parse_month(text: str) -> tuple[int, int]:
    try:
        year_str, month_str = text.split("-")
        year, month = int(year_str), int(month_str)
        if not 1 <= month <= 12:
            raise ValueError
        return year, month
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"--target-month must be YYYY-MM (got {text!r})"
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m app.ingestion",
        description="Ingest Elexon wind actuals (FUELHH) and forecasts (WINDFOR) "
        "for a target delivery month into local SQLite.",
    )
    parser.add_argument(
        "--target-month",
        type=_parse_month,
        default=(config.DEFAULT_TARGET_YEAR, config.DEFAULT_TARGET_MONTH),
        metavar="YYYY-MM",
        help="Target delivery month (default: 2026-01).",
    )
    parser.add_argument(
        "--db-path", type=Path, default=None, help="SQLite file (default: data/wind.db)."
    )
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=None,
        help="Data directory for the DB and raw cache (default: project data/).",
    )
    parser.add_argument(
        "--forecast-lookback-days",
        type=int,
        default=config.DEFAULT_FORECAST_LOOKBACK_DAYS,
        help="Days before the month to start the WINDFOR publish window "
        f"(default: {config.DEFAULT_FORECAST_LOOKBACK_DAYS}).",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--actuals-only", action="store_true", help="Ingest only FUELHH actuals."
    )
    group.add_argument(
        "--forecasts-only", action="store_true", help="Ingest only WINDFOR forecasts."
    )
    return parser


def print_summary(result: RunResult) -> None:
    cov = result.coverage
    exp_periods = pipeline.expected_actual_periods(
        result.window_start, result.window_end
    )
    exp_hours = pipeline.expected_forecast_target_hours(
        result.window_start, result.window_end
    )
    exp_days = (result.window_end - result.window_start).days

    print("\n" + "=" * 68)
    print("INGESTION SUMMARY")
    print("=" * 68)

    a = result.actuals
    print("\nActuals (FUELHH, fuelType=WIND):")
    print(f"  API rows fetched          : {a.fetched}")
    print(f"  Kept (target in month)    : {a.kept}")
    print(f"  Inserted                  : {a.counts.inserted}")
    print(f"  Updated                   : {a.counts.updated}")
    print(f"  Duplicates (no change)    : {a.counts.duplicates}")
    print(f"  Malformed rows skipped    : {a.malformed}")
    print(
        f"  Coverage                  : {cov.actual_periods}/{exp_periods} "
        f"half-hourly periods across {cov.actual_distinct_dates}/{exp_days} dates"
    )
    print(
        f"  Target range              : {cov.actual_min_target} .. "
        f"{cov.actual_max_target}"
    )

    f = result.forecasts
    print("\nForecast vintages (WINDFOR):")
    print(f"  API rows fetched          : {f.fetched}")
    print(f"  Kept (target in month)    : {f.kept}")
    print(f"  Inserted                  : {f.counts.inserted}")
    print(f"  Updated                   : {f.counts.updated}")
    print(f"  Duplicates (no change)    : {f.counts.duplicates}")
    print(f"  Malformed rows skipped    : {f.malformed}")
    print(
        f"  Coverage                  : {cov.forecast_distinct_targets}/{exp_hours} "
        f"hourly target times; {cov.forecast_distinct_vintages} distinct vintages; "
        f"{cov.forecast_rows} rows"
    )
    print(
        f"  Target range              : {cov.forecast_min_target} .. "
        f"{cov.forecast_max_target}"
    )

    # Honest coverage verdict -- never claim complete coverage unless verified.
    actuals_complete = (
        result.actuals.fetched > 0 and cov.actual_periods >= exp_periods
    )
    forecasts_complete = (
        result.forecasts.fetched > 0 and cov.forecast_distinct_targets >= exp_hours
    )
    print("\nCoverage verdict:")
    print(
        "  Actuals   : "
        + (
            "COMPLETE" if actuals_complete
            else f"INCOMPLETE ({cov.actual_periods}/{exp_periods} periods)"
        )
    )
    print(
        "  Forecasts : "
        + (
            "COMPLETE" if forecasts_complete
            else f"INCOMPLETE ({cov.forecast_distinct_targets}/{exp_hours} target hours)"
        )
    )
    print("=" * 68)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    year, month = args.target_month
    try:
        result = pipeline.run(
            year=year,
            month=month,
            db_path=args.db_path,
            data_dir=args.data_dir,
            lookback_days=args.forecast_lookback_days,
            do_actuals=not args.forecasts_only,
            do_forecasts=not args.actuals_only,
        )
    except ElexonAPIError as exc:
        print(f"\nERROR: Elexon ingestion failed: {exc}", file=sys.stderr)
        return 1
    print_summary(result)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
