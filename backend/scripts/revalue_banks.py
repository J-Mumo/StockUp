"""Re-value companies using the sector-dispatch valuation engine and print an
old-vs-new comparison.

Run this against a database to verify the new sector-aware valuator produces
sane numbers before promoting scheduled valuations to a broader set.

Usage (from ``backend/`` with venv active):

    python -m scripts.revalue_banks                            # dry-run over KCB,EQTY,COOP,NCBA
    python -m scripts.revalue_banks --commit                   # persist snapshots for the banks
    python -m scripts.revalue_banks --tickers KCB,EQTY         # subset
    python -m scripts.revalue_banks --all                      # every active company (dry-run)
    python -m scripts.revalue_banks --all --commit             # every active company, persist

Default behaviour is DRY-RUN so operators cannot accidentally overwrite prod
``intrinsic_values`` rows. Persistence requires the explicit ``--commit`` flag.

For each ticker the script logs the sector-classified strategy and, for
banks, the component values and scenario decision ranges so we can eyeball
whether the composite falls in the plans/sector-specific-valuation.md target
windows.
"""

from __future__ import annotations

import argparse
import logging
import sys
from typing import Any

from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.models.company import Company
from app.models.intrinsic_value import IntrinsicValue
from app.services.valuation import compute_valuation, get_strategy
from app.services.valuation.sectors import classify_sector

logger = logging.getLogger("revalue_banks")


DEFAULT_TICKERS = ["KCB", "EQTY", "COOP", "NCBA"]


def _format_money(value: Any) -> str:
    if value is None:
        return "     n/a"
    return f"{float(value):>8.2f}"


def _format_pct(value: Any) -> str:
    if value is None:
        return "   n/a"
    return f"{float(value) * 100:>5.1f}%"


def _fetch_previous_iv(db: Session, company_id: int) -> IntrinsicValue | None:
    return (
        db.query(IntrinsicValue)
        .filter(IntrinsicValue.company_id == company_id)
        .order_by(desc(IntrinsicValue.valuation_date), desc(IntrinsicValue.id))
        .first()
    )


def revalue(tickers: list[str], commit: bool) -> int:
    session: Session = SessionLocal()
    try:
        mode = "COMMIT" if commit else "DRY-RUN"
        print("=" * 100)
        print(f"mode: {mode}  db: {session.get_bind().url}")
        print(
            f"{'Ticker':<8}{'Sector':<14}{'Model':<26}"
            f"{'Prev IV':>10}{'New IV':>10}{'Price':>10}{'MOS':>8}"
        )
        print("-" * 100)

        exit_code = 0
        for ticker in tickers:
            company = (
                session.query(Company)
                .filter(Company.ticker_symbol == ticker.upper())
                .first()
            )
            if company is None:
                print(f"{ticker:<8}NOT FOUND — skipping")
                exit_code = 1
                continue

            strategy = get_strategy(company.sector)
            kind = classify_sector(company.sector).value

            prev_iv = _fetch_previous_iv(session, company.id)
            prev_value = prev_iv.weighted_intrinsic_value if prev_iv else None

            result = compute_valuation(session, company.id)
            if isinstance(result, str):
                print(f"{ticker:<8}{kind:<14}{strategy.model_name:<26}error: {result}")
                exit_code = 1
                continue

            print(
                f"{company.ticker_symbol:<8}{kind:<14}"
                f"{result.model_used:<26}"
                f"{_format_money(prev_value)}"
                f"{_format_money(result.weighted_intrinsic_value)}"
                f"{_format_money(result.current_market_price)}"
                f"{_format_pct(result.margin_of_safety_pct)}"
            )

            # Bank-specific breakdown
            if result.model_used == "bank_residual_income":
                comps = result.component_values or {}
                scenarios = result.scenario_values or {}
                print(
                    "        components:  "
                    f"RI={_format_money(comps.get('residual_income'))}  "
                    f"JustP/B={_format_money(comps.get('justified_pb'))}  "
                    f"JustP/E={_format_money(comps.get('justified_pe'))}  "
                    f"pre-discount={_format_money(comps.get('base_pre_quality_discount'))}  "
                    f"discount={_format_pct(comps.get('quality_discount_pct'))}"
                )
                print(
                    "        scenarios:   "
                    f"conservative={_format_money(scenarios.get('conservative'))}  "
                    f"base={_format_money(scenarios.get('base'))}  "
                    f"strong={_format_money(scenarios.get('strong'))}"
                )
                if result.notes:
                    print("        notes:       " + "; ".join(result.notes))
                if result.quality_adjustments:
                    penalties = ", ".join(
                        f"{k}={v * 100:.1f}%" for k, v in result.quality_adjustments.items()
                    )
                    print(f"        penalties:   {penalties}")
            print()

        if commit:
            session.commit()
            print("Committed new valuation snapshots.")
        else:
            session.rollback()
            print("[dry-run] rolled back; no valuation snapshots written. "
                  "Re-run with --commit to persist.")

        return exit_code
    finally:
        session.close()


def _resolve_tickers(session: Session, args: argparse.Namespace) -> list[str]:
    """Resolve the ticker list based on CLI flags."""
    if args.all:
        rows = (
            session.query(Company)
            .filter(Company.is_active.is_(True))
            .order_by(Company.ticker_symbol)
            .all()
        )
        return [c.ticker_symbol for c in rows]
    return [t.strip() for t in args.tickers.split(",") if t.strip()]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tickers",
        default=",".join(DEFAULT_TICKERS),
        help="Comma-separated tickers to re-value (default: KCB,EQTY,COOP,NCBA)",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Re-value every active company (ignores --tickers)",
    )
    parser.add_argument(
        "--commit",
        action="store_true",
        help="Persist new valuation snapshots (default is dry-run)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Explicit dry-run flag (default behaviour). Retained for backward compatibility.",
    )
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    if args.commit and args.dry_run:
        parser.error("--commit and --dry-run are mutually exclusive")

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    # Resolve ticker list against a short-lived session
    resolver_session: Session = SessionLocal()
    try:
        tickers = _resolve_tickers(resolver_session, args)
    finally:
        resolver_session.close()

    if not tickers:
        print("No tickers to re-value.")
        return 1

    return revalue(tickers, commit=args.commit)


if __name__ == "__main__":
    sys.exit(main())
