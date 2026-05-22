"""Recommendation Engine G�� quantitative stock recommendation logic.

Generates buy/sell/hold recommendations based on:
- Margin of Safety (MOS)
- Quality gate: 5 core factors must ALL pass for a Buy recommendation
- 10 total quality factors scored from financial_statements table

Core quality gate (all 5 must pass for Buy):
    1. FCF increasing for 3+ consecutive years
    2. Consistently increasing earnings (positive trend, majority of years)
    3. Conservative debt (total liabilities < 4x net income)
    4. ROE > 15% (sustained across years)
    5. Capital efficiency (FCF/Revenue > 5%)

Recommendation tiers:
    Strong Buy:  MOS > 30% AND all 5 core factors AND D/E < 0.5 AND dividends
    Buy:         MOS > 30% AND all 5 core factors pass
    Accumulate:  MOS 10-30% AND >= 4 of 5 core factors pass
    Hold:        MOS > 0% OR quality gate not met (potential value trap)
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
    insufficient_data: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "met": self.passed,
            "description": self.detail,
            "passed": self.passed,
            "value": self.value,
            "threshold": self.threshold,
            "detail": self.detail,
            "insufficient_data": self.insufficient_data,
        }


@dataclass
class QualityAssessment:
    """Complete quality assessment for a company."""
    factors: list[QualityScore] = field(default_factory=list)
    score: int = 0  # number of factors passed (0-10)
    max_score: int = 10

    # Derived flags
    has_high_roe: bool = False
    has_low_leverage: bool = False
    has_earnings_growth: bool = False
    has_positive_fcf: bool = False
    has_dividend_consistency: bool = False
    has_adequate_liquidity: bool = False
    has_fcf_increasing: bool = False
    has_revenue_consistency: bool = False
    has_conservative_debt: bool = False
    has_capital_efficiency: bool = False

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
            "has_fcf_increasing": self.has_fcf_increasing,
            "has_revenue_consistency": self.has_revenue_consistency,
            "has_conservative_debt": self.has_conservative_debt,
            "has_capital_efficiency": self.has_capital_efficiency,
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

    # Factor 7: FCF strictly increasing (last 3+ consecutive years)
    fcf_inc_factor = _assess_fcf_increasing(sorted_fs)
    assessment.factors.append(fcf_inc_factor)
    assessment.has_fcf_increasing = fcf_inc_factor.passed

    # Factor 8: Revenue growth consistency (grew in 80%+ of years)
    rev_factor = _assess_revenue_consistency(sorted_fs)
    assessment.factors.append(rev_factor)
    assessment.has_revenue_consistency = rev_factor.passed

    # Factor 9: Conservative debt (total liabilities < 4x net income)
    debt_factor = _assess_conservative_debt(sorted_fs)
    assessment.factors.append(debt_factor)
    assessment.has_conservative_debt = debt_factor.passed

    # Factor 10: Capital efficiency (FCF/Revenue > 5%)
    capeff_factor = _assess_capital_efficiency(sorted_fs)
    assessment.factors.append(capeff_factor)
    assessment.has_capital_efficiency = capeff_factor.passed

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
            insufficient_data=True,
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
    """Dividend consistency G�� paid dividends in most years."""
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


def _assess_fcf_increasing(financials: list[FinancialStatement]) -> QualityScore:
    """FCF strictly increasing for last 3+ consecutive years."""
    fcfs = []
    for fs in financials:
        fcf = _safe_float(fs.free_cash_flow)
        if fcf is not None:
            fcfs.append((fs.fiscal_year, fcf))

    if len(fcfs) < 3:
        return QualityScore(
            name="FCF Increasing (3+ yrs)",
            passed=False,
            value=None,
            threshold="FCF increasing for 3+ consecutive years",
            detail=f"Insufficient FCF data ({len(fcfs)} years)",
            insufficient_data=True,
        )

    # Check last 3 consecutive years
    recent = fcfs[-3:]
    consecutive_increases = all(
        recent[i][1] > recent[i - 1][1] for i in range(1, len(recent))
    )

    return QualityScore(
        name="FCF Increasing (3+ yrs)",
        passed=consecutive_increases,
        value=len([1 for i in range(1, len(fcfs)) if fcfs[i][1] > fcfs[i - 1][1]]),
        threshold="FCF increasing for 3+ consecutive years",
        detail=f"Last 3 years: {'increasing' if consecutive_increases else 'not consistently increasing'}",
    )


def _assess_revenue_consistency(financials: list[FinancialStatement]) -> QualityScore:
    """Revenue grew in 80%+ of years."""
    revenues = []
    for fs in financials:
        rev = _safe_float(fs.revenue)
        if rev is not None:
            revenues.append((fs.fiscal_year, rev))

    if len(revenues) < 2:
        return QualityScore(
            name="Revenue Growth Consistency",
            passed=False,
            value=None,
            threshold="Revenue grew in 80%+ of years",
            detail=f"Insufficient revenue data ({len(revenues)} years)",
        )

    growth_years = sum(
        1 for i in range(1, len(revenues)) if revenues[i][1] > revenues[i - 1][1]
    )
    total_pairs = len(revenues) - 1
    ratio = growth_years / total_pairs

    return QualityScore(
        name="Revenue Growth Consistency",
        passed=ratio >= 0.8,
        value=round(ratio, 2),
        threshold="Revenue grew in 80%+ of years",
        detail=f"Revenue grew in {growth_years}/{total_pairs} years ({ratio:.0%})",
    )


def _assess_conservative_debt(financials: list[FinancialStatement]) -> QualityScore:
    """Conservative debt: total liabilities < 4x net income (latest year)."""
    for fs in reversed(financials):
        ni = _safe_float(fs.net_income)
        liabilities = _safe_float(fs.total_liabilities)

        # Compute liabilities from assets - equity if not directly available
        if liabilities is None:
            assets = _safe_float(fs.total_assets)
            equity = _safe_float(fs.total_equity)
            if assets is not None and equity is not None:
                liabilities = assets - equity

        if ni is not None and ni > 0 and liabilities is not None:
            ratio = liabilities / ni
            passed = ratio < 4.0
            return QualityScore(
                name="Conservative Debt (LT Debt < 4x NI)",
                passed=passed,
                value=round(ratio, 2),
                threshold="Total liabilities < 4x net income",
                detail=f"Liabilities/NI ratio: {ratio:.1f}x (FY{fs.fiscal_year})",
            )

    return QualityScore(
        name="Conservative Debt (LT Debt < 4x NI)",
        passed=False,
        value=None,
        threshold="Total liabilities < 4x net income",
        detail="Insufficient data (need net income > 0 and liabilities)",
    )


def _assess_capital_efficiency(financials: list[FinancialStatement]) -> QualityScore:
    """Capital efficiency: FCF/Revenue > 5% (latest year)."""
    for fs in reversed(financials):
        fcf = _safe_float(fs.free_cash_flow)
        rev = _safe_float(fs.revenue)
        if fcf is not None and rev is not None and rev > 0:
            ratio = fcf / rev
            passed = ratio > 0.05
            return QualityScore(
                name="Capital Efficiency (FCF/Rev > 5%)",
                passed=passed,
                value=round(ratio, 4),
                threshold="FCF / Revenue > 5%",
                detail=f"FCF/Revenue: {ratio:.1%} (FY{fs.fiscal_year})",
            )

    return QualityScore(
        name="Capital Efficiency (FCF/Rev > 5%)",
        passed=False,
        value=None,
        threshold="FCF / Revenue > 5%",
        detail="No FCF or revenue data available",
        insufficient_data=True,
    )


# ---------------------------------------------------------------------------
# Recommendation Logic
# ---------------------------------------------------------------------------

def generate_recommendation(
    margin_of_safety: float | None,
    financials: list[FinancialStatement],
) -> Recommendation:
    """Generate a buy/sell/hold recommendation with quality-gated buy logic.

    Core quality gate (all 5 must pass for Buy):
        1. FCF increasing for 3+ consecutive years
        2. Consistently increasing sales & earnings
        3. Conservative debt (liabilities < 4x net income)
        4. ROE > 15%
        5. Capital efficiency (FCF/Revenue > 5%)

    Decision matrix:
        Strong Buy:  MOS > 30% AND all 5 quality factors pass AND D/E < 0.5 AND dividends
        Buy:         MOS > 30% AND all 5 quality factors pass
        Accumulate:  MOS > 10% AND >= 4 of 5 quality factors pass
        Hold:        MOS > 0% OR quality factors insufficient
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

    mos_pct = margin_of_safety * 100

    # Core factors: FCF increasing, earnings growth, conservative debt, ROE, capital efficiency.
    # Indexes reference quality.factors order from assess_quality().
    core_factor_indices = [6, 2, 8, 0, 9]
    core_factors = [quality.factors[i] for i in core_factor_indices]
    available_core = [f for f in core_factors if not f.insufficient_data]
    core_passed = sum(1 for f in available_core if f.passed)
    core_total = len(available_core)
    all_core_pass = core_total == 5 and core_passed == 5
    missing_core = 5 - core_total

    has_low_de = quality.has_low_leverage
    has_dividends = quality.has_dividend_consistency

    failing = []
    if not quality.has_high_roe:
        failing.append("ROE < 15%")
    if not quality.has_earnings_growth:
        failing.append("earnings not growing")
    if not quality.has_conservative_debt:
        failing.append("high debt/earnings ratio")
    if not quality.factors[6].insufficient_data and not quality.has_fcf_increasing:
        failing.append("FCF not consistently increasing")
    if not quality.factors[9].insufficient_data and not quality.has_capital_efficiency:
        failing.append("low capital efficiency")

    if margin_of_safety > 0.30:
        if all_core_pass and has_low_de and has_dividends:
            action = "Strong Buy"
            reason = (
                f"Deep value: {mos_pct:.1f}% margin of safety — all quality "
                f"factors pass with low leverage and consistent dividends "
                f"(score: {quality.score}/{quality.max_score})"
            )
        elif all_core_pass:
            action = "Buy"
            reason = (
                f"Undervalued: {mos_pct:.1f}% margin of safety — all 5 core "
                f"quality factors pass (score: {quality.score}/{quality.max_score})"
            )
        else:
            action = "Hold"
            if missing_core > 0:
                reason = (
                    f"Undervalued ({mos_pct:.1f}% MOS) but quality gate is incomplete "
                    f"({core_total}/5 core factors available). Additional cash flow data is needed."
                )
            else:
                reason = (
                    f"Undervalued ({mos_pct:.1f}% MOS) but quality gate not met "
                    f"({core_passed}/5 core factors). Fails: {', '.join(failing)}. "
                    f"Potential value trap — hold until quality improves"
                )
    elif margin_of_safety > 0.10:
        if core_total >= 4 and core_passed >= 4:
            action = "Accumulate"
            reason = (
                f"Moderately undervalued: {mos_pct:.1f}% margin of safety "
                f"with {core_passed}/{core_total} available core quality factors passing"
            )
        else:
            action = "Hold"
            if missing_core > 0:
                reason = (
                    f"Marginally undervalued: {mos_pct:.1f}% margin of safety, "
                    f"but only {core_total}/5 core quality factors are available."
                )
            else:
                reason = (
                    f"Marginally undervalued: {mos_pct:.1f}% margin of safety "
                    f"but quality insufficient ({core_passed}/5 core factors). "
                    f"Fails: {', '.join(failing)}"
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
