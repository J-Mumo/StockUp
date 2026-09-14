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
from app.services.valuation.sector_norms import QualityNorms, norms_for_sector
from app.services.valuation.sectors import SectorKind, classify_sector

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


# ---------------------------------------------------------------------------
# Quality subscore decomposition
#
# The 10 individual factors roll up into 6 investor-facing dimensions so the
# UI can show *why* a company got its aggregate score rather than just the
# raw 6/10. Slot semantics differ per sector (see ``_assess_bank_quality``);
# the mapping below reflects that. A dimension is skipped ("n/a") when every
# feeding factor is ``insufficient_data`` — that's a signal, not a failure.
# ---------------------------------------------------------------------------

# Slot indexes into ``QualityAssessment.factors`` (order matches the append
# sequence in ``_assess_industrial_quality`` / ``_assess_bank_quality``).
_INDUSTRIAL_SUBSCORE_MAP: dict[str, list[int]] = {
    "Profitability": [0],                # ROE
    "Capital": [1, 8],                   # D/E, conservative debt
    "Asset quality": [5],                # current ratio (proxy)
    "Efficiency": [9],                   # capital efficiency (FCF/Rev)
    "Growth": [2, 7],                    # earnings, revenue consistency
    "Shareholder returns": [3, 4, 6],    # FCF, dividends, FCF increasing
}
_BANK_SUBSCORE_MAP: dict[str, list[int]] = {
    "Profitability": [0],                # ROE
    "Capital": [1],                      # capital adequacy
    "Asset quality": [3],                # NPL / CoR composite
    "Efficiency": [9],                   # cost/income
    "Growth": [2, 6, 7],                 # earnings, earning-assets, NII
    "Shareholder returns": [4],          # dividend consistency
}


@dataclass
class QualityAssessment:
    """Complete quality assessment for a company."""
    factors: list[QualityScore] = field(default_factory=list)
    score: int = 0  # number of factors passed (0-10)
    max_score: int = 10
    sector_kind: str = "industrial"  # "industrial" | "bank"; used for subscore map

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

    def _subscore_map(self) -> dict[str, list[int]]:
        return (
            _BANK_SUBSCORE_MAP
            if self.sector_kind == "bank"
            else _INDUSTRIAL_SUBSCORE_MAP
        )

    def subscores(self) -> list[dict[str, Any]]:
        """Return the 6-dimension breakdown as a list of ``{name, score,
        max_score, passed, applicable, detail}`` dicts.

        ``score`` is out of ``max_score`` (= number of applicable factors in
        that dimension). ``applicable`` is False when every factor feeding
        the dimension is marked ``insufficient_data`` (dimension is "n/a").
        """
        out: list[dict[str, Any]] = []
        for name, slots in self._subscore_map().items():
            applicable_factors: list[QualityScore] = []
            for slot in slots:
                if slot >= len(self.factors):
                    continue
                f = self.factors[slot]
                if f.insufficient_data:
                    continue
                applicable_factors.append(f)
            applicable = bool(applicable_factors)
            passed_count = sum(1 for f in applicable_factors if f.passed)
            total = len(applicable_factors)
            out.append(
                {
                    "name": name,
                    "score": passed_count,
                    "max_score": total,
                    "passed": applicable and passed_count == total,
                    "applicable": applicable,
                    "detail": (
                        ", ".join(f.name for f in applicable_factors)
                        if applicable
                        else "n/a for this sector or insufficient data"
                    ),
                }
            )
        return out

    def to_dict(self) -> dict[str, Any]:
        return {
            "factors": [f.to_dict() for f in self.factors],
            "score": self.score,
            "max_score": self.max_score,
            "sector_kind": self.sector_kind,
            "subscores": self.subscores(),
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
    # Optional 4-dimensional scorecard. Populated by callers that pass price
    # history / portfolio context to compute_recommendation_with_dimensions().
    # Kept as a dict (not a dataclass) to keep this module dependency-free.
    dimensions: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "action": self.action,
            "reason": self.reason,
            "margin_of_safety_pct": self.margin_of_safety_pct,
            "quality": self.quality.to_dict(),
            "dimensions": self.dimensions,
        }


# ---------------------------------------------------------------------------
# Quality Factor Assessment
# ---------------------------------------------------------------------------

def assess_quality(
    financials: list[FinancialStatement],
    sector: str | None = None,
) -> QualityAssessment:
    """Assess quality factors from financial statements.

    Dispatches to a sector-specific implementation. Unknown or missing
    sectors default to the industrial factor set for backward compatibility.

    Args:
        financials: List of FinancialStatement objects (any order).
        sector: Free-form sector string from ``Company.sector``. When
            ``None`` (or unknown), the industrial factor set is used —
            matching pre-sector-dispatcher behaviour.

    Returns:
        QualityAssessment with individual factor results.
    """
    kind = classify_sector(sector)
    if kind == SectorKind.BANK:
        return _assess_bank_quality(financials)
    return _assess_industrial_quality(financials, sector=sector)


def _assess_industrial_quality(
    financials: list[FinancialStatement],
    sector: str | None = None,
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
    norms = norms_for_sector(sector)
    # Keep the assessment tagged "industrial" so downstream slot mapping and
    # UI rendering are unchanged; the sector-conditioned thresholds are an
    # internal adjustment, not a new sector strategy.
    assessment = QualityAssessment(sector_kind="industrial")
    sorted_fs = sorted(financials, key=lambda f: f.fiscal_year)

    # Factor 1: ROE consistency vs sector-appropriate hurdle.
    roe_factor = _assess_roe(sorted_fs, norms=norms)
    assessment.factors.append(roe_factor)
    assessment.has_high_roe = roe_factor.passed

    # Factor 2: Leverage vs sector-appropriate ceiling.
    de_factor = _assess_debt_to_equity(sorted_fs, norms=norms)
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

    # Factor 9: Conservative debt — sector-appropriate metric & threshold.
    debt_factor = _assess_conservative_debt(sorted_fs, norms=norms)
    assessment.factors.append(debt_factor)
    assessment.has_conservative_debt = debt_factor.passed

    # Factor 10: Capital efficiency (FCF/Revenue > 5%)
    capeff_factor = _assess_capital_efficiency(sorted_fs)
    assessment.factors.append(capeff_factor)
    assessment.has_capital_efficiency = capeff_factor.passed

    # Score
    assessment.score = sum(1 for f in assessment.factors if f.passed)
    return assessment


def _assess_roe(
    financials: list[FinancialStatement],
    norms: QualityNorms | None = None,
) -> QualityScore:
    """Average ROE vs sector-appropriate hurdle.

    Historical default is 15% (industrial). Utilities/energy/real-estate use
    lower hurdles via :mod:`app.services.valuation.sector_norms`.
    """
    norms = norms or QualityNorms()
    hurdle = norms.roe_min
    name = f"Consistent ROE > {hurdle:.0%}"
    threshold = f"> {hurdle:.2f} average, 50%+ years above threshold"

    roes = []
    for fs in financials:
        roe = _safe_float(fs.return_on_equity)
        if roe is not None:
            roes.append(roe)

    if not roes:
        return QualityScore(
            name=name,
            passed=False,
            value=None,
            threshold=threshold,
            detail="No ROE data available",
        )

    avg_roe = statistics.mean(roes)
    years_above = sum(1 for r in roes if r > hurdle)
    consistency = years_above / len(roes)

    passed = avg_roe > hurdle and consistency >= 0.5
    detail = (
        f"Avg ROE: {avg_roe:.1%}, {years_above}/{len(roes)} years above "
        f"{hurdle:.0%} [{norms.label} hurdle]"
    )
    return QualityScore(
        name=name,
        passed=passed,
        value=round(avg_roe, 4),
        threshold=threshold,
        detail=detail,
    )


def _assess_debt_to_equity(
    financials: list[FinancialStatement],
    norms: QualityNorms | None = None,
) -> QualityScore:
    """D/E vs sector-appropriate ceiling (latest available year)."""
    norms = norms or QualityNorms()
    ceiling = norms.de_max
    name = f"Low Debt-to-Equity (< {ceiling:.1f})"
    threshold = f"< {ceiling:.2f}"

    for fs in reversed(financials):
        de = _safe_float(fs.debt_to_equity)
        if de is not None:
            passed = de < ceiling
            return QualityScore(
                name=name,
                passed=passed,
                value=round(de, 4),
                threshold=threshold,
                detail=f"D/E ratio: {de:.2f} (FY{fs.fiscal_year}) [{norms.label} ceiling]",
            )

    return QualityScore(
        name=name,
        passed=False,
        value=None,
        threshold=threshold,
        detail="No D/E data available",
    )


# Extreme scale jumps between two consecutive annual observations almost
# always indicate a data-entry / unit / restated-base problem rather than a
# real business event — a 200× or 50,000× YoY isn't achievable organically.
# We trim such base years before computing growth so a single bad row doesn't
# poison the CAGR headline.
_ANOMALOUS_BASE_RATIO = 50.0


def _trim_anomalous_base_years(
    series: list[tuple[int, float]],
) -> tuple[list[tuple[int, float]], list[int]]:
    """Drop leading years whose value is negligibly small vs the next year.

    Returns ``(trimmed_series, excluded_years)``. Only trims from the front
    of the series — a large positive year followed by an outlier isn't a
    base-year error, it's a business shock and should stay.
    """
    excluded: list[int] = []
    trimmed = list(series)
    while len(trimmed) >= 2:
        (y0, v0), (_, v1) = trimmed[0], trimmed[1]
        if v0 > 0 and v1 > 0 and v1 / v0 > _ANOMALOUS_BASE_RATIO:
            excluded.append(y0)
            trimmed = trimmed[1:]
            continue
        # Also drop a non-positive leading year — it can't seed a CAGR anyway.
        if v0 <= 0 and v1 > 0 and len(trimmed) >= 3:
            excluded.append(y0)
            trimmed = trimmed[1:]
            continue
        break
    return trimmed, excluded


def _assess_earnings_growth(financials: list[FinancialStatement]) -> QualityScore:
    """Normalized earnings-growth trend as a CAGR.

    * Filters out anomalous base years (e.g. a nominal 2020 figure that would
      turn a real ~15% CAGR into a 43,000% "average") before computing.
    * Reports the CAGR across the normalized period and the count of years
      that grew YoY. ``passed`` = positive CAGR AND majority of years grew.
    """
    earnings: list[tuple[int, float]] = []
    for fs in financials:
        ni = _safe_float(fs.net_income)
        if ni is not None:
            earnings.append((fs.fiscal_year, ni))

    if len(earnings) < 2:
        return QualityScore(
            name="Earnings Growth Trend",
            passed=False,
            value=None,
            threshold="Positive normalized CAGR (5+ years)",
            detail="Insufficient earnings data (need 2+ years)",
        )

    trimmed, excluded = _trim_anomalous_base_years(earnings)
    if len(trimmed) < 2:
        return QualityScore(
            name="Earnings Growth Trend",
            passed=False,
            value=None,
            threshold="Positive normalized CAGR (5+ years)",
            detail=(
                "Cannot compute growth after excluding anomalous base "
                f"year(s): {', '.join(f'FY{y}' for y in excluded)}"
            ),
        )

    y_start, v_start = trimmed[0]
    y_end, v_end = trimmed[-1]
    n_years = y_end - y_start
    cagr: float | None = None
    if n_years > 0 and v_start > 0 and v_end > 0:
        cagr = (v_end / v_start) ** (1.0 / n_years) - 1.0

    positive_years = 0
    total_pairs = 0
    for i in range(1, len(trimmed)):
        prev_val = trimmed[i - 1][1]
        curr_val = trimmed[i][1]
        if prev_val > 0:
            total_pairs += 1
            if curr_val > prev_val:
                positive_years += 1

    passed = (
        cagr is not None
        and cagr > 0
        and total_pairs > 0
        and positive_years > total_pairs / 2
    )

    if cagr is None:
        detail = "Cannot compute CAGR (need positive start and end earnings)"
    else:
        detail = (
            f"Normalized CAGR: {cagr:.1%} (FY{y_start}-FY{y_end}), "
            f"{positive_years}/{total_pairs} years growing"
        )
    if excluded:
        detail += (
            f"; excluded {', '.join(f'FY{y}' for y in excluded)} "
            f"(anomalous base — YoY jump > {_ANOMALOUS_BASE_RATIO:.0f}x)"
        )

    return QualityScore(
        name="Earnings Growth Trend",
        passed=bool(passed),
        value=round(cagr, 4) if cagr is not None else None,
        threshold="Positive CAGR + majority of years growing",
        detail=detail,
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


def _assess_conservative_debt(
    financials: list[FinancialStatement],
    norms: QualityNorms | None = None,
) -> QualityScore:
    """Conservative debt vs sector-appropriate metric & threshold.

    Historically this used ``liabilities / net income`` with a 4× ceiling —
    fine for asset-light industrials, poor for utilities where NI is
    distorted by non-cash FX losses on concessional foreign debt. Asset-heavy
    sectors (energy, real estate, telecom) prefer ``liabilities / OCF`` when
    OCF is available, falling back to a widened NI-based metric otherwise.
    """
    norms = norms or QualityNorms()

    for fs in reversed(financials):
        liabilities = _safe_float(fs.total_liabilities)
        if liabilities is None:
            assets = _safe_float(fs.total_assets)
            equity = _safe_float(fs.total_equity)
            if assets is not None and equity is not None:
                liabilities = assets - equity
        if liabilities is None:
            continue

        # Preferred metric for asset-heavy sectors: liabilities / OCF.
        if norms.prefer_ocf_debt_metric:
            ocf = _safe_float(fs.operating_cash_flow)
            if ocf is not None and ocf > 0:
                ratio = liabilities / ocf
                ceiling = norms.liab_to_ocf_max
                passed = ratio < ceiling
                return QualityScore(
                    name=f"Conservative Debt (Liab/OCF < {ceiling:.0f}x)",
                    passed=passed,
                    value=round(ratio, 2),
                    threshold=f"Total liabilities < {ceiling:.0f}\u00d7 OCF",
                    detail=(
                        f"Liabilities/OCF: {ratio:.1f}x (FY{fs.fiscal_year}) "
                        f"[{norms.label} metric]"
                    ),
                )

        # Fallback: liabilities / net income (widened per sector).
        ni = _safe_float(fs.net_income)
        if ni is not None and ni > 0:
            ratio = liabilities / ni
            ceiling = norms.liab_to_ni_max
            passed = ratio < ceiling
            return QualityScore(
                name=f"Conservative Debt (Liab/NI < {ceiling:.0f}x)",
                passed=passed,
                value=round(ratio, 2),
                threshold=f"Total liabilities < {ceiling:.0f}\u00d7 net income",
                detail=(
                    f"Liabilities/NI ratio: {ratio:.1f}x (FY{fs.fiscal_year}) "
                    f"[{norms.label} ceiling]"
                ),
            )

    return QualityScore(
        name="Conservative Debt",
        passed=False,
        value=None,
        threshold="Liabilities vs OCF/NI within sector norms",
        detail="Insufficient data (need liabilities and positive OCF or NI)",
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
# Bank Quality Assessment (Phase 1 of sector-specific models)
#
# For banks, the industrial quality gate is inappropriate:
#   - Customer deposits are inputs, not "debt". Liabilities/NI is meaningless.
#   - Free cash flow is not a proxy for owner earnings.
#   - Capital adequacy, asset quality and cost-of-risk are the right lenses.
#
# We reuse the 10-slot QualityAssessment shape so downstream code (frontend
# rendering, recommendation gate) doesn't need to change. Slot semantics are
# repurposed for banks — see the mapping below. Slots that have no bank
# analogue are marked ``insufficient_data=True`` so the gate correctly skips
# them (the gate already handles missing factors gracefully).
#
# Slot → industrial → bank meaning
#   0  → ROE > 15%                → ROE > 18%
#   1  → D/E < 0.5                → Capital adequacy > 14.5%
#   2  → earnings growth          → earnings growth (unchanged)
#   3  → FCF positive/growing     → healthy asset quality (NPL < 15%, CoR < 2%)
#   4  → dividend consistency     → dividend consistency (unchanged)
#   5  → current ratio > 1        → *n/a for banks* (marked insufficient)
#   6  → FCF increasing 3yrs      → earning-asset growth (loans/deposits)
#   7  → revenue consistency      → net-interest-income growth
#   8  → conservative debt        → *n/a for banks* (marked insufficient)
#   9  → capital efficiency       → operating efficiency (cost/income < 55%)
# ---------------------------------------------------------------------------


def _assess_bank_quality(
    financials: list[FinancialStatement],
) -> QualityAssessment:
    """Bank-specific quality assessment. See slot mapping above."""
    assessment = QualityAssessment(sector_kind="bank")
    sorted_fs = sorted(financials, key=lambda f: f.fiscal_year)

    # Slot 0: ROE > 18% (higher bar for banks)
    roe_factor = _assess_bank_roe(sorted_fs)
    assessment.factors.append(roe_factor)
    assessment.has_high_roe = roe_factor.passed

    # Slot 1: Capital adequacy > 14.5%
    car_factor = _assess_bank_capital_adequacy(sorted_fs)
    assessment.factors.append(car_factor)
    assessment.has_low_leverage = car_factor.passed  # semantics: "safe balance sheet"

    # Slot 2: Earnings growth (unchanged)
    eg_factor = _assess_earnings_growth(sorted_fs)
    assessment.factors.append(eg_factor)
    assessment.has_earnings_growth = eg_factor.passed

    # Slot 3: Healthy asset quality (NPL < 15% and CoR < 2%)
    aq_factor = _assess_bank_asset_quality(sorted_fs)
    assessment.factors.append(aq_factor)
    assessment.has_positive_fcf = aq_factor.passed  # semantics: "not bleeding"

    # Slot 4: Dividend consistency (unchanged)
    div_factor = _assess_dividends(sorted_fs)
    assessment.factors.append(div_factor)
    assessment.has_dividend_consistency = div_factor.passed

    # Slot 5: n/a for banks — skip.
    na_liquidity = QualityScore(
        name="Current Ratio (n/a for banks)",
        passed=True,
        value=None,
        threshold="not applicable to banks",
        detail="Liquidity is regulated separately (LCR/NSFR)",
        insufficient_data=True,
    )
    assessment.factors.append(na_liquidity)
    assessment.has_adequate_liquidity = True

    # Slot 6: Earning-asset growth (loans or deposits growing)
    ea_factor = _assess_bank_earning_asset_growth(sorted_fs)
    assessment.factors.append(ea_factor)
    assessment.has_fcf_increasing = ea_factor.passed  # semantics: "growing engine"

    # Slot 7: Net-interest-income growth (proxy for top-line consistency)
    nii_factor = _assess_bank_nii_growth(sorted_fs)
    assessment.factors.append(nii_factor)
    assessment.has_revenue_consistency = nii_factor.passed

    # Slot 8: n/a for banks — skip.
    na_debt = QualityScore(
        name="Liabilities/NI (n/a for banks)",
        passed=True,
        value=None,
        threshold="not applicable to banks",
        detail="Customer deposits are raw material, not debt",
        insufficient_data=True,
    )
    assessment.factors.append(na_debt)
    assessment.has_conservative_debt = True

    # Slot 9: Operating efficiency (cost-to-income < 55%)
    eff_factor = _assess_bank_operating_efficiency(sorted_fs)
    assessment.factors.append(eff_factor)
    assessment.has_capital_efficiency = eff_factor.passed

    assessment.score = sum(1 for f in assessment.factors if f.passed)
    return assessment


def _assess_bank_roe(financials: list[FinancialStatement]) -> QualityScore:
    """Banks should earn a premium ROE (> 18%)."""
    roes = [_safe_float(fs.return_on_equity) for fs in financials]
    roes = [r for r in roes if r is not None]
    if not roes:
        return QualityScore(
            name="Bank ROE > 18%",
            passed=False,
            value=None,
            threshold="> 0.18 average",
            detail="No ROE data available",
            insufficient_data=True,
        )
    avg = statistics.mean(roes)
    years_above = sum(1 for r in roes if r > 0.18)
    passed = avg > 0.18 and years_above / len(roes) >= 0.5
    return QualityScore(
        name="Bank ROE > 18%",
        passed=passed,
        value=round(avg, 4),
        threshold="> 0.18 average, 50%+ years above",
        detail=f"Avg ROE: {avg:.1%}, {years_above}/{len(roes)} years above 18%",
    )


def _assess_bank_capital_adequacy(
    financials: list[FinancialStatement],
) -> QualityScore:
    """Capital adequacy ratio > 14.5% (well above CBK 14.5% minimum)."""
    for fs in reversed(financials):
        sm = fs.sector_metrics or {}
        car = _safe_float(sm.get("capital_adequacy_ratio"))
        if car is not None:
            passed = car > 0.145
            return QualityScore(
                name="Capital Adequacy > 14.5%",
                passed=passed,
                value=round(car, 4),
                threshold="> 0.145 (CBK minimum + buffer)",
                detail=f"CAR: {car:.1%} (FY{fs.fiscal_year})",
            )
    return QualityScore(
        name="Capital Adequacy > 14.5%",
        passed=False,
        value=None,
        threshold="> 0.145",
        detail="No capital adequacy ratio in sector_metrics",
        insufficient_data=True,
    )


def _assess_bank_asset_quality(
    financials: list[FinancialStatement],
) -> QualityScore:
    """NPL ratio < 15% AND cost of risk < 2% (latest year)."""
    for fs in reversed(financials):
        sm = fs.sector_metrics or {}
        npl = _safe_float(sm.get("npl_ratio"))
        cor = _safe_float(sm.get("cost_of_risk"))
        if npl is None and cor is None:
            continue
        npl_ok = npl is None or npl < 0.15
        cor_ok = cor is None or cor < 0.02
        passed = npl_ok and cor_ok
        parts = []
        if npl is not None:
            parts.append(f"NPL={npl:.1%}")
        if cor is not None:
            parts.append(f"CoR={cor:.2%}")
        return QualityScore(
            name="Healthy Asset Quality",
            passed=passed,
            value=round(npl, 4) if npl is not None else None,
            threshold="NPL < 15%, CoR < 2%",
            detail=f"{', '.join(parts)} (FY{fs.fiscal_year})",
        )
    return QualityScore(
        name="Healthy Asset Quality",
        passed=False,
        value=None,
        threshold="NPL < 15%, CoR < 2%",
        detail="No NPL or cost-of-risk data in sector_metrics",
        insufficient_data=True,
    )


def _assess_bank_earning_asset_growth(
    financials: list[FinancialStatement],
) -> QualityScore:
    """Loans or deposits growing (positive trend over 3+ years)."""
    for fs in reversed(financials):
        sm = fs.sector_metrics or {}
        loan_g = _safe_float(sm.get("loan_growth_pct"))
        dep_g = _safe_float(sm.get("deposit_growth_pct"))
        if loan_g is not None or dep_g is not None:
            grow = max(g for g in [loan_g, dep_g] if g is not None)
            passed = grow > 0.05
            parts = []
            if loan_g is not None:
                parts.append(f"loans +{loan_g:.1%}")
            if dep_g is not None:
                parts.append(f"deposits +{dep_g:.1%}")
            return QualityScore(
                name="Earning-Asset Growth",
                passed=passed,
                value=round(grow, 4),
                threshold="loans or deposits growing > 5%",
                detail=", ".join(parts) + f" (FY{fs.fiscal_year})",
            )
    # Fallback: net-income growth as a rough proxy
    return QualityScore(
        name="Earning-Asset Growth",
        passed=False,
        value=None,
        threshold="loans or deposits growing > 5%",
        detail="No loan/deposit growth data in sector_metrics",
        insufficient_data=True,
    )


def _assess_bank_nii_growth(
    financials: list[FinancialStatement],
) -> QualityScore:
    """Net interest income growing in 60%+ of years (proxy for top-line)."""
    series: list[tuple[int, float]] = []
    for fs in financials:
        sm = fs.sector_metrics or {}
        nii = _safe_float(sm.get("net_interest_income"))
        if nii is not None:
            series.append((fs.fiscal_year, nii))
    if len(series) < 2:
        # Fall back to revenue if NII missing.
        return _assess_revenue_consistency(financials)
    growth_years = sum(
        1 for i in range(1, len(series)) if series[i][1] > series[i - 1][1]
    )
    ratio = growth_years / (len(series) - 1)
    return QualityScore(
        name="Net Interest Income Growth",
        passed=ratio >= 0.6,
        value=round(ratio, 2),
        threshold="NII grew in 60%+ of years",
        detail=f"NII grew in {growth_years}/{len(series) - 1} years ({ratio:.0%})",
    )


def _assess_bank_operating_efficiency(
    financials: list[FinancialStatement],
) -> QualityScore:
    """Cost-to-income ratio < 55% (well-run bank)."""
    for fs in reversed(financials):
        sm = fs.sector_metrics or {}
        cti = _safe_float(sm.get("cost_to_income"))
        if cti is not None:
            passed = cti < 0.55
            return QualityScore(
                name="Cost-to-Income < 55%",
                passed=passed,
                value=round(cti, 4),
                threshold="< 0.55",
                detail=f"C/I: {cti:.1%} (FY{fs.fiscal_year})",
            )
    return QualityScore(
        name="Cost-to-Income < 55%",
        passed=False,
        value=None,
        threshold="< 0.55",
        detail="No cost-to-income ratio in sector_metrics",
        insufficient_data=True,
    )


# ---------------------------------------------------------------------------
# Recommendation Logic
# ---------------------------------------------------------------------------

def generate_recommendation(
    margin_of_safety: float | None,
    financials: list[FinancialStatement],
    sector: str | None = None,
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
        sector: Optional company sector; when provided, sector-specific quality
            factors are used (e.g. banks get NPL/CAR instead of D/E).

    Returns:
        Recommendation with action, reason, and quality breakdown.
    """
    quality = assess_quality(financials, sector=sector)

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

    # Build a human-readable list of failing core factors from the actual
    # factor objects so bank-specific factor names propagate correctly.
    failing = [
        f.name for f in core_factors
        if not f.insufficient_data and not f.passed
    ]

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

    return generate_recommendation(margin_of_safety, financials, sector=company.sector)


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
