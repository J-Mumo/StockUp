"""Bulk-run goal extraction (Pass A) and progress assessment (Pass B) for a
sequence of tickers, pacing LLM calls to respect the OpenAI 30k TPM budget.

Usage:
    python run_bulk_goals.py CARB ABSA COOP DTK EQTY KCB NCBA SBIC SCBK
        [--pace 60] [--no-llm] [--skip-extract] [--skip-assess]
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
import time
from pathlib import Path

from app.database import SessionLocal
from app.data.company_goals_extractor import (
    assess_all_goals_for_company,
    extract_goals_from_report,
)
from app.models.company import Company

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
# Silence the very noisy SQLAlchemy echo for bulk runs.
logging.getLogger("sqlalchemy.engine.Engine").setLevel(logging.WARNING)
logger = logging.getLogger("bulk_goals")

YEAR_RE = re.compile(r"^\d{4}$")
REPORTS_DIR = Path(__file__).resolve().parent / "data" / "annual_reports"


def cached_annual_years(ticker: str) -> list[int]:
    folder = REPORTS_DIR / ticker
    if not folder.exists():
        return []
    years: list[int] = []
    for pdf in folder.glob("*.pdf"):
        if YEAR_RE.match(pdf.stem):
            years.append(int(pdf.stem))
    return sorted(years)


def run_for_ticker(
    ticker: str,
    *,
    pace_seconds: float,
    allow_llm_fallback: bool,
    skip_extract: bool,
    skip_assess: bool,
) -> None:
    db = SessionLocal()
    try:
        company = (
            db.query(Company).filter(Company.ticker_symbol == ticker).first()
        )
        if company is None:
            logger.error("No company row for ticker %s — skipping", ticker)
            return

        years = cached_annual_years(ticker)
        logger.info("=== %s: %d cached annual PDFs (%s) ===", ticker, len(years), years)

        # ---- Pass A: extract goals ----
        if not skip_extract:
            for i, year in enumerate(years):
                logger.info("[%s] extract goals FY%d", ticker, year)
                try:
                    result = extract_goals_from_report(
                        db, company, year, skip_if_exists=True
                    )
                except Exception as e:
                    logger.exception("[%s] FY%d extract crashed: %s", ticker, year, e)
                    time.sleep(pace_seconds)
                    continue
                logger.info(
                    "[%s] FY%d -> %s (inserted=%s skipped_existing=%s)",
                    ticker,
                    year,
                    result.get("status"),
                    result.get("goals_inserted"),
                    result.get("goals_existing"),
                )
                # Pace only when we actually called the LLM.
                if result.get("status") == "success" and i < len(years) - 1:
                    time.sleep(pace_seconds)

        # ---- Pass B: assess progress for every goal ----
        if not skip_assess:
            logger.info("[%s] assessing all goals (LLM fallback=%s)", ticker, allow_llm_fallback)
            summary = assess_all_goals_for_company(
                db,
                company,
                allow_llm_fallback=allow_llm_fallback,
                pace_seconds=pace_seconds,
            )
            logger.info("[%s] assess summary: %s", ticker, summary)

    finally:
        db.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("tickers", nargs="+")
    parser.add_argument("--pace", type=float, default=60.0)
    parser.add_argument("--no-llm", action="store_true")
    parser.add_argument("--skip-extract", action="store_true")
    parser.add_argument("--skip-assess", action="store_true")
    args = parser.parse_args()

    for ticker in args.tickers:
        run_for_ticker(
            ticker.upper(),
            pace_seconds=args.pace,
            allow_llm_fallback=not args.no_llm,
            skip_extract=args.skip_extract,
            skip_assess=args.skip_assess,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
