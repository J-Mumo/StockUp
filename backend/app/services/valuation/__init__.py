"""Valuation strategy package — sector-aware dispatcher.

Public API (backward compatible):
    compute_valuation(db, company_id, assumptions=None, valuation_date=None)
    compute_all_valuations(db, assumptions=None)

The dispatcher classifies each company by sector and delegates to the
appropriate strategy (industrial DCF, bank residual income, ...). Falls
back to the industrial strategy for unknown sectors or when sector-specific
data is missing.

See plans/sector-specific-valuation.md for design rationale.
"""

from __future__ import annotations

import logging
from datetime import date, datetime
from typing import Any

from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.models.company import Company
from app.models.financial_statement import FinancialStatement
from app.models.intrinsic_value import IntrinsicValue
from app.models.price_history import PriceHistory

from .base import SectorValuator, ValuationResult
from .sectors import classify_sector, SectorKind
from .industrial import IndustrialValuator
from .bank import BankValuator

logger = logging.getLogger(__name__)


_STRATEGY_REGISTRY: dict[SectorKind, SectorValuator] = {
    SectorKind.BANK: BankValuator(),
    SectorKind.INDUSTRIAL: IndustrialValuator(),
    # SectorKind.INSURANCE and SectorKind.REIT fall back to INDUSTRIAL until
    # their dedicated strategies land.
}


def get_strategy(sector: str | None) -> SectorValuator:
    """Return the valuation strategy that should be used for the given sector."""
    kind = classify_sector(sector)
    return _STRATEGY_REGISTRY.get(kind, _STRATEGY_REGISTRY[SectorKind.INDUSTRIAL])


def compute_valuation(
    db: Session,
    company_id: int,
    assumptions: dict[str, Any] | None = None,
    valuation_date: date | None = None,
) -> ValuationResult | str:
    """Compute a valuation for a company and persist a snapshot.

    Returns a ValuationResult on success or an error string sentinel
    ("company_not_found", "no_shares_outstanding", "no_financial_data")
    matching the historical contract.
    """
    if valuation_date is None:
        valuation_date = date.today()

    company = db.query(Company).filter(Company.id == company_id).first()
    if company is None:
        return "company_not_found"

    shares = company.shares_outstanding
    if not shares or shares <= 0:
        return "no_shares_outstanding"

    financials = (
        db.query(FinancialStatement)
        .filter(FinancialStatement.company_id == company_id)
        .order_by(FinancialStatement.fiscal_year)
        .all()
    )
    if not financials:
        return "no_financial_data"

    latest_price_record = (
        db.query(PriceHistory)
        .filter(PriceHistory.company_id == company_id)
        .order_by(desc(PriceHistory.price_date))
        .first()
    )
    market_price = (
        float(latest_price_record.close_price) if latest_price_record else None
    )

    strategy = get_strategy(company.sector)
    logger.debug(
        "Valuing company_id=%s sector=%r via strategy=%s",
        company_id, company.sector, strategy.model_name,
    )
    result = strategy.value(company, financials, market_price, assumptions)

    # Persist snapshot
    iv_record = IntrinsicValue(
        company_id=company_id,
        valuation_date=valuation_date,
        dcf_value=result.dcf.intrinsic_value_per_share,
        epv_value=result.epv.intrinsic_value_per_share,
        book_value_estimate=result.book_value.book_value_per_share,
        weighted_intrinsic_value=result.weighted_intrinsic_value,
        current_market_price=result.current_market_price,
        margin_of_safety_pct=result.margin_of_safety_pct,
        model_used=result.model_used,
        scenario_values=result.scenario_values or None,
        assumptions=result.assumptions_used,
        calculation_details=result.to_calculation_details(),
        calculated_at=datetime.utcnow(),
    )
    db.add(iv_record)
    db.flush()

    logger.info(
        "Valuation computed for company_id=%s model=%s IV=%s MOS=%s price=%s",
        company_id, result.model_used, result.weighted_intrinsic_value,
        result.margin_of_safety_pct, market_price,
    )
    return result


def compute_all_valuations(
    db: Session,
    assumptions: dict[str, Any] | None = None,
) -> dict[int, str | ValuationResult]:
    """Compute valuations for all active companies."""
    companies = db.query(Company).filter(Company.is_active == True).all()  # noqa: E712
    results: dict[int, str | ValuationResult] = {}

    for company in companies:
        try:
            results[company.id] = compute_valuation(db, company.id, assumptions)
        except Exception as e:  # pragma: no cover — defensive
            logger.error(
                "Error computing valuation for company_id=%s: %s", company.id, e,
            )
            results[company.id] = f"error: {str(e)}"

    db.commit()
    return results


__all__ = [
    "compute_valuation",
    "compute_all_valuations",
    "get_strategy",
    "ValuationResult",
    "SectorValuator",
]
