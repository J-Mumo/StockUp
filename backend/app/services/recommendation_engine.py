"""Recommendation Engine — quantitative stock recommendation logic.

Generates buy/sell/hold recommendations based on:
- Margin of Safety (MOS)
- Quality factors (ROE, D/E, earnings growth, FCF, dividends, current ratio)

All factors are purely quantitative — computed from the financial_statements table.
No subjective moat assessment; sustained ROE > 15% is the moat proxy.

Recommendation tiers:
    Strong Buy:  MOS > 30% AND ROE > 15% AND D/E < 0.5
    Buy:         MOS > 30% AND ROE > 15%
    Buy:         MOS > 30%
    Accumulate:  MOS 10-30% AND ROE > 15%
    Hold:        MOS 0-10%
    Hold/Trim:   MOS -10% to 0%
    Sell:        MOS < -10%
    Strong Sell: MOS < -20%
"""

from __future__ import annotations

import logging
import statistics
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from app.models.company import Company
from app.models.financial_statement import FinancialStatement

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class QualityScore:
    """Individual quality factor assessment."""
    name: str
    passed: bool
    value: float | None = None
    threshold: str = ""
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "met": self.passed,
            "description": self.detail,
            "passed": self.passed,
            "value": self.value,
            "threshold": self.threshold,
            "detail": self.detail,
        }


@dataclass
class QualityAssessment:
    """Complete quality assessment for a company."""
    factors: list[QualityScore] = field(default_factory=list)
    score: int = 0  # number of factors passed (0-6)
    max_score: int = 6

    # Derived flags
    has_high_roe: bool = False
    has_low_leverage: bool = False
    has_earnings_growth: bool = False
    has_positive_fcf: bool = False
    has_dividend_consistency: bool = False
    has_adequate_liquidity: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "factors": [f.to_dict() for f in self.factors],
            "score": self.score,
            "max_score": self.max_score,
            "has_high_roe": self.has_high_roe,
            "has_low_leverage": self.has_low_leverage,
            "has_earnings_growth": self.has_earnings_growth,
            "has_positive_fcf": self.has_positive_fcf,
            "has_dividend_consistency": self.has_dividend_consistency,
            "has_adequate_liquidity": self.has_adequate_liquidity,
        }


@dataclass
class Recommendation:
    """Final recommendation output."""
    action: str  # Strong Buy, Buy, Accumulate, Hold, Hold/Trim, Sell, Strong Sell
    reason: str
    margin_of_safety_pct: float | None = None
    quality: QualityAssessment = field(default_factory=QualityAssessment)

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "reason": self.reason,
            "margin_of_safety_pct": self.margin_of_safety_pct,
            "quality": self.quality.to_dict(),
        }


# ---------------------------------------------------------------------------
# Quality Factor Assessment
# ---------------------------------------------------------------------------

def assess_quality(
    financials: list[FinancialStatement],
) -> QualityAssessment:
    """Assess quality factors from financial statements.

    Quality factors (all quantitative):
        1. ROE > 15% consistent (moat proxy)
        2. D/E < 0.5 (low leverage)
        3. Earnings growth trend (5+ years)
        4. FCF positive and growing
        5. Dividend consistency
        6. Current ratio > 1.0

    Args:
        financials: List of FinancialStatement objects (any order).

    Returns:
        QualityAssessment with individual factor results.
    """
    assessment = QualityAssessment()
    sorted_fs = sorted(financials, key=lambda f: f.fiscal_year)

    # Factor 1: ROE > 15% consistent (average ROE over available years)
    roe_factor = _assess_roe(sorted_fs)
    assessment.factors.append(roe_factor)
    assessment.has_high_roe = roe_factor.passed

    # Factor 2: D/E < 0.5 (latest year)
    de_factor = _assess_debt_to_equity(sorted_fs)
    assessment.factors.append(de_factor)
    assessment.has_low_leverage = de_factor.passed

    # Factor 3: Earnings growth trend
    eg_factor = _assess_earnings_growth(sorted_fs)
    assessment.factors.append(eg_factor)
    assessment.has_earnings_growth = eg_factor.passed

    # Factor 4: FCF positive and growing
    fcf_factor = _assess_fcf(sorted_fs)
    assessment.factors.append(fcf_factor)
    assessment.has_positive_fcf = fcf_factor.passed

    # Factor 5: Dividend consistency
    div_factor = _assess_dividends(sorted_fs)
    assessment.factors.append(div_factor)
    assessment.has_dividend_consistency = div_factor.passed

    # Factor 6: Current ratio > 1.0
    cr_factor = _assess_current_ratio(sorted_fs)
    assessment.factors.append(cr_factor)
    assessment.has_adequate_liquidity = cr_factor.passed

    # Score
    assessment.score = sum(1 for f in assessment.factors if f.passed)
    return assessment


def _assess_roe(financials: list[FinancialStatement]) -> QualityScore:
    """ROE > 15% consistently (average across available years)."""
    roes = []
    for fs in financials:
        roe = _safe_float(fs.return_on_equity)
        if roe is not None:
            roes.append(roe)

    if not roes:
        return QualityScore(
            name="Consistent ROE > 15%",
            passed=False,
            value=None,
            threshold="> 0.15 average",
            detail="No ROE data available",
        )

    avg_roe = statistics.mean(roes)
    # Check if at least 50% of years have ROE > 15%
    years_above = sum(1 for r in roes if r > 0.15)
    consistency = years_above / len(roes)

    passed = avg_roe > 0.15 and consistency >= 0.5
    return QualityScore(
        name="Consistent ROE > 15%",
        passed=passed,
        value=round(avg_roe, 4),
        threshold="> 0.15 average, 50%+ years above threshold",
        detail=f"Avg ROE: {avg_roe:.1%}, {years_above}/{len(roes)} years above 15%",
    )


def _assess_debt_to_equity(financials: list[FinancialStatement]) -> QualityScore:
    """D/E < 0.5 (latest available year)."""
    # Use latest financial with D/E data
    for fs in reversed(financials):
        de = _safe_float(fs.debt_to_equity)
        if de is not None:
            passed = de < 0.5
            return QualityScore(
                name="Low Debt-to-Equity (< 0.5)",
                passed=passed,
                value=round(de, 4),
                threshold="< 0.5",
                detail=f"D/E ratio: {de:.2f} (FY{fs.fiscal_year})",
            )

    return QualityScore(
        name="Low Debt-to-Equity (< 0.5)",
        passed=False,
        value=None,
        threshold="< 0.5",
        detail="No D/E data available",
    )


def _assess_earnings_growth(financials: list[FinancialStatement]) -> QualityScore:
    """Earnings growth trend over 5+ years (or all available if < 5)."""
    earnings = []
    for fs in financials:
        ni = _safe_float(fs.net_income)
        if ni is not None:
            earnings.append((fs.fiscal_year, ni))

    if len(earnings) < 2:
        return QualityScore(
            name="Earnings Growth Trend",
            passed=False,
            value=None,
            threshold="Positive trend over 5+ years",
            detail="Insufficient earnings data (need 2+ years)",
        )

    # Calculate average YoY growth
    growth_rates = []
    for i in range(1, len(earnings)):
        prev_val = earnings[i - 1][1]
        if prev_val > 0:
            growth = (earnings[i][1] - prev_val) / prev_val
            growth_rates.append(growth)

    if not growth_rates:
        return QualityScore(
            name="Earnings Growth Trend",
            passed=False,
            value=None,
            threshold="Positive trend over 5+ years",
            detail="Cannot compute growth (prior year earnings <= 0)",
        )

    avg_growth = statistics.mean(growth_rates)
    # Consider trend positive if avg growth > 0 and majority of years positive
    positive_years = sum(1 for g in growth_rates if g > 0)
    passed = avg_growth > 0 and positive_years > len(growth_rates) / 2

    return QualityScore(
        name="Earnings Growth Trend",
        passed=passed,
        value=round(avg_growth, 4),
        threshold="Positive avg growth, majority of years positive",
        detail=f"Avg growth: {avg_growth:.1%}, {positive_years}/{len(growth_rates)} years positive",
    )


def _assess_fcf(financials: list[FinancialStatement]) -> QualityScore:
    """Free Cash Flow positive and growing."""
    fcfs = []
    for fs in financials:
        fcf = _safe_float(fs.free_cash_flow)
        if fcf is not None:
            fcfs.append((fs.fiscal_year, fcf))

    if not fcfs:
        return QualityScore(
            name="Positive & Growing FCF",
            passed=False,
            value=None,
            threshold="Positive FCF in majority of years",
            detail="No FCF data available",
        )

    positive_years = sum(1 for _, f in fcfs if f > 0)
    passed = positive_years > len(fcfs) / 2

    # Check growth if enough data
    growth_detail = ""
    if len(fcfs) >= 2:
        first_fcf = fcfs[0][1]
        last_fcf = fcfs[-1][1]
        if first_fcf > 0 and last_fcf > first_fcf:
            growth_detail = ", growing"
        elif last_fcf < first_fcf:
            growth_detail = ", declining"

    latest_fcf = fcfs[-1][1] if fcfs else None

    return QualityScore(
        name="Positive & Growing FCF",
        passed=passed,
        value=latest_fcf,
        threshold="Positive FCF in majority of years",
        detail=f"{positive_years}/{len(fcfs)} years positive{growth_detail}",
    )


def _assess_dividends(financials: list[FinancialStatement]) -> QualityScore:
    """Dividend consistency — paid dividends in most years."""
    divs = []
    for fs in financials:
        dps = _safe_float(fs.dividends_per_share)
        if dps is not None:
            divs.append((fs.fiscal_year, dps))

    if not divs:
        return QualityScore(
            name="Dividend Consistency",
            passed=False,
            value=None,
            threshold="Dividends paid in 60%+ of years",
            detail="No dividend data available",
        )

    paying_years = sum(1 for _, d in divs if d > 0)
    ratio = paying_years / len(divs)
    passed = ratio >= 0.6

    return QualityScore(
        name="Dividend Consistency",
        passed=passed,
        value=round(ratio, 2),
        threshold="Dividends paid in 60%+ of years",
        detail=f"Paid dividends in {paying_years}/{len(divs)} years ({ratio:.0%})",
    )


def _assess_current_ratio(financials: list[FinancialStatement]) -> QualityScore:
    """Current ratio > 1.0 (latest year)."""
    for fs in reversed(financials):
        cr = _safe_float(fs.current_ratio)
        if cr is not None:
            passed = cr > 1.0
            return QualityScore(
                name="Current Ratio > 1.0",
                passed=passed,
                value=round(cr, 4),
                threshold="> 1.0",
                detail=f"Current ratio: {cr:.2f} (FY{fs.fiscal_year})",
            )

    return QualityScore(
        name="Current Ratio > 1.0",
        passed=False,
        value=None,
        threshold="> 1.0",
        detail="No current ratio data available",
    )


# ---------------------------------------------------------------------------
# Recommendation Logic
# ---------------------------------------------------------------------------

def generate_recommendation(
    margin_of_safety: float | None,
    financials: list[FinancialStatement],
) -> Recommendation:
    """Generate a buy/sell/hold recommendation.

    Decision matrix:
        Strong Buy:  MOS > 30% AND ROE > 15% AND D/E < 0.5
        Buy:         MOS > 30% AND ROE > 15%
        Buy:         MOS > 30%
        Accumulate:  MOS 10-30% AND ROE > 15%
        Hold:        MOS 0-10%
        Hold/Trim:   MOS -10% to 0%
        Sell:        MOS < -10%
        Strong Sell: MOS < -20%

    Args:
        margin_of_safety: MOS as decimal (0.30 = 30%). None if not computable.
        financials: Financial statements for quality assessment.

    Returns:
        Recommendation with action, reason, and quality breakdown.
    """
    quality = assess_quality(financials)

    if margin_of_safety is None:
        return Recommendation(
            action="Hold",
            reason="Insufficient data to compute margin of safety",
            margin_of_safety_pct=None,
            quality=quality,
        )

    mos_pct = margin_of_safety * 100  # Convert to percentage for display
    has_roe = quality.has_high_roe
    has_low_de = quality.has_low_leverage

    # Decision logic (ordered from most bullish to most bearish)
    if margin_of_safety > 0.30:
        if has_roe and has_low_de:
            action = "Strong Buy"
            reason = (
                f"Deep value: {mos_pct:.1f}% margin of safety with "
                f"consistent high ROE and low leverage"
            )
        elif has_roe:
            action = "Buy"
            reason = (
                f"Undervalued: {mos_pct:.1f}% margin of safety with "
                f"strong earnings quality (ROE > 15%)"
            )
        else:
            action = "Buy"
            reason = (
                f"Undervalued: {mos_pct:.1f}% margin of safety "
                f"(quality score: {quality.score}/{quality.max_score})"
            )
    elif margin_of_safety > 0.10:
        if has_roe:
            action = "Accumulate"
            reason = (
                f"Moderately undervalued: {mos_pct:.1f}% margin of safety "
                f"with strong ROE — suitable for accumulation"
            )
        else:
            action = "Hold"
            reason = (
                f"Marginally undervalued: {mos_pct:.1f}% margin of safety "
                f"but quality factors insufficient for accumulation"
            )
    elif margin_of_safety >= 0:
        action = "Hold"
        reason = (
            f"Fairly valued: {mos_pct:.1f}% margin of safety — "
            f"no action needed at current price"
        )
    elif margin_of_safety >= -0.10:
        action = "Hold/Trim"
        reason = (
            f"Slightly overvalued: {mos_pct:.1f}% margin of safety — "
            f"consider trimming on strength"
        )
    elif margin_of_safety >= -0.20:
        action = "Sell"
        reason = (
            f"Overvalued: {mos_pct:.1f}% margin of safety — "
            f"price exceeds intrinsic value significantly"
        )
    else:
        action = "Strong Sell"
        reason = (
            f"Significantly overvalued: {mos_pct:.1f}% margin of safety — "
            f"sell to avoid capital loss"
        )

    return Recommendation(
        action=action,
        reason=reason,
        margin_of_safety_pct=margin_of_safety,
        quality=quality,
    )


def compute_recommendation(
    db: Session,
    company_id: int,
    margin_of_safety: float | None,
) -> Recommendation | str:
    """Compute recommendation for a company using DB data.

    Args:
        db: Database session.
        company_id: Company to evaluate.
        margin_of_safety: Pre-computed MOS (from valuation engine).

    Returns:
        Recommendation or error string.
    """
    company = db.query(Company).filter(Company.id == company_id).first()
    if company is None:
        return "company_not_found"

    financials = (
        db.query(FinancialStatement)
        .filter(FinancialStatement.company_id == company_id)
        .order_by(FinancialStatement.fiscal_year)
        .all()
    )

    return generate_recommendation(margin_of_safety, financials)


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _safe_float(value: Any) -> float | None:
    """Convert a potentially Decimal/None value to float safely."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
