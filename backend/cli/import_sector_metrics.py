"""Import bank ``sector_metrics`` from a CSV into ``financial_statements``.

Usage::

    python -m cli.import_sector_metrics data/bank_sector_metrics_2021_2025.csv
    python -m cli.import_sector_metrics <csv> --dry-run
    python -m cli.import_sector_metrics <csv> --tickers KCB,EQTY

CSV schema::

    ticker,fiscal_year,npl_ratio,capital_adequacy_ratio,cost_of_risk,
    cost_to_income,loan_growth_pct,deposit_growth_pct

Blanks are preserved as ``null`` (not zero). Existing entries in
``sector_metrics`` are merged with non-blank values; blanks never overwrite.
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm.attributes import flag_modified

from app.database import SessionLocal
from app.models import Company, FinancialStatement


# CSV ticker → DB ticker_symbol (CSV is source of truth; DB uses NSE codes)
TICKER_ALIASES: dict[str, str] = {
    "I&M": "IMH",
    "IM": "IMH",
    "STANBIC": "SBIC",
    "DTB": "DTK",
    "HF": "HFCK",
}

METRIC_COLUMNS: tuple[str, ...] = (
    "npl_ratio",
    "capital_adequacy_ratio",
    "cost_of_risk",
    "cost_to_income",
    "loan_growth_pct",
    "deposit_growth_pct",
)


def _parse_row(raw: dict[str, str]) -> tuple[str, int, dict[str, float]]:
    ticker = (raw.get("ticker") or "").strip()
    fy_raw = (raw.get("fiscal_year") or "").strip()
    if not ticker or not fy_raw:
        raise ValueError(f"missing ticker or fiscal_year: {raw!r}")
    fy = int(fy_raw)
    metrics: dict[str, float] = {}
    for col in METRIC_COLUMNS:
        val = (raw.get(col) or "").strip()
        if val == "":
            continue
        try:
            metrics[col] = float(val)
        except ValueError as exc:
            raise ValueError(
                f"non-numeric value {val!r} for {ticker} FY{fy} {col}"
            ) from exc
    return ticker, fy, metrics


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("csv_path", type=Path)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument(
        "--tickers",
        help="Restrict to comma-separated CSV tickers (uses CSV names, not DB codes)",
    )
    args = ap.parse_args()

    if not args.csv_path.exists():
        print(f"CSV not found: {args.csv_path}")
        return 2

    ticker_filter: set[str] | None = None
    if args.tickers:
        ticker_filter = {t.strip().upper() for t in args.tickers.split(",") if t.strip()}

    seen = 0
    updated = 0
    unchanged = 0
    skipped_blank = 0
    skipped_no_company = 0
    skipped_no_fs_row = 0

    db = SessionLocal()
    try:
        with args.csv_path.open(newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for raw in reader:
                seen += 1
                csv_ticker, fy, new_metrics = _parse_row(raw)
                if ticker_filter and csv_ticker.upper() not in ticker_filter:
                    continue
                if not new_metrics:
                    skipped_blank += 1
                    continue

                db_ticker = TICKER_ALIASES.get(
                    csv_ticker.upper(), csv_ticker.upper()
                )
                company = db.scalar(
                    select(Company).where(Company.ticker_symbol == db_ticker)
                )
                if company is None:
                    print(f"[skip] {csv_ticker} -> {db_ticker} FY{fy}: no company row")
                    skipped_no_company += 1
                    continue

                fs = db.scalar(
                    select(FinancialStatement).where(
                        FinancialStatement.company_id == company.id,
                        FinancialStatement.fiscal_year == fy,
                        FinancialStatement.period_type == "annual",
                    )
                )
                if fs is None:
                    print(
                        f"[skip] {db_ticker} FY{fy}: no annual "
                        f"financial_statement row"
                    )
                    skipped_no_fs_row += 1
                    continue

                merged = dict(fs.sector_metrics or {})
                changed_keys: list[str] = []
                for k, v in new_metrics.items():
                    if merged.get(k) != v:
                        merged[k] = v
                        changed_keys.append(k)

                if changed_keys:
                    fs.sector_metrics = merged
                    # SQLAlchemy JSON: force dirty on in-place update.
                    flag_modified(fs, "sector_metrics")
                    updated += 1
                    print(
                        f"[ok]  {db_ticker} FY{fy}: "
                        + ", ".join(f"{k}={new_metrics[k]}" for k in changed_keys)
                    )
                else:
                    unchanged += 1

        if args.dry_run:
            db.rollback()
            print(
                f"\n[dry-run] rolled back. would update {updated} row(s); "
                f"{unchanged} already current."
            )
        else:
            db.commit()
            print(f"\ncommitted {updated} row update(s); {unchanged} already current.")

        print(
            f"csv rows seen: {seen}, "
            f"blank rows: {skipped_blank}, "
            f"skipped (no company): {skipped_no_company}, "
            f"skipped (no fs row): {skipped_no_fs_row}"
        )
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
