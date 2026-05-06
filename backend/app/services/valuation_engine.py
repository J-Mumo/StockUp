"""Valuation Engine — DCF, EPV, Book Value, and composite intrinsic value calculations.

Implements Buffett-style value investing math with conservative defaults for the
Kenyan market. Handles missing data gracefully by skipping methods with insufficient
data rather than failing entirely.

Key formulas:
    DCF:  V = Σ FCF_t/(1+r)^t + FCF_n(1+g)/((r-g)(1+r)^n)
    EPV:  EPV = Normalized Earnings / Cost of Capital
    BV:   BV/share = Total Equity / Shares Outstanding
    IV:   0.5×DCF + 0.3×EPV + 0.2×BV  (configurable weights)
    MOS:  1 - (Market Price / Intrinsic Value)
"""

from __future__ import annotations

import logging
import statistics
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.models.company import Company
from app.models.financial_statement import FinancialStatement
from app.models.intrinsic_value import IntrinsicValue
from app.models.price_history import PriceHistory

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Default assumptions (conservative for Kenyan market)
# ---------------------------------------------------------------------------

DEFAULT_ASSUMPTIONS = {
    "discount_rate": 0.12,          # 12% — higher risk premium for frontier market
    "terminal_growth_rate": 0.03,   # 3% — long-term GDP proxy
    "projection_years": 10,
    "max_growth_rate_cap": 0.20,    # Cap FCF growth at 20%
    "min_growth_rate_floor": -0.05, # Floor at -5%
    "dcf_weight": 1.00,            # Pure DCF when available
    "epv_weight": 0.00,            # EPV used only as fallback when DCF unavailable
    "bv_weight": 0.00,             # BV used only as fallback when DCF unavailable
    "fallback_epv_weight": 0.70,   # When DCF unavailable: EPV weight
    "fallback_bv_weight": 0.30,    # When DCF unavailable: BV weight
    "min_years_for_dcf": 3,         # Need at least 3 years of FCF data
    "min_years_for_epv": 2,         # Need at least 2 years of net income
    "outlier_std_multiplier": 2.0,  # Remove values > 2 std devs for EPV
}


# ---------------------------------------------------------------------------
# Data classes for intermediate results
# ---------------------------------------------------------------------------

@dataclass
class DCFResult:
    """Result of DCF valuation calculation."""
    intrinsic_value_per_share: float | None = None
    total_intrinsic_value: float | None = None
    projected_fcfs: list[float] = field(default_factory=list)
    terminal_value: float | None = None
    growth_rate_used: float | None = None
    historical_fcfs: list[float] = field(default_factory=list)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "method": "dcf",
            "intrinsic_value_per_share": self.intrinsic_value_per_share,
            "total_intrinsic_value": self.total_intrinsic_value,
            "projected_fcfs": self.projected_fcfs,
            "terminal_value": self.terminal_value,
            "growth_rate_used": self.growth_rate_used,
            "historical_fcfs": self.historical_fcfs,
            "error": self.error,
        }


@dataclass
class EPVResult:
    """Result of EPV valuation calculation."""
    intrinsic_value_per_share: float | None = None
    normalized_earnings: float | None = None
    earnings_used: list[float] = field(default_factory=list)
    earnings_after_outlier_removal: list[float] = field(default_factory=list)
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "method": "epv",
            "intrinsic_value_per_share": self.intrinsic_value_per_share,
            "normalized_earnings": self.normalized_earnings,
            "earnings_used": self.earnings_used,
            "earnings_after_outlier_removal": self.earnings_after_outlier_removal,
            "error": self.error,
        }


@dataclass
class BookValueResult:
    """Result of Book Value per share estimation."""
    book_value_per_share: float | None = None
    total_equity: float | None = None
    shares_outstanding: int | None = None
    source: str | None = None  # "computed" or "reported"
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "method": "book_value",
            "book_value_per_share": self.book_value_per_share,
            "total_equity": self.total_equity,
            "shares_outstanding": self.shares_outstanding,
            "source": self.source,
            "error": self.error,
        }


@dataclass
class ValuationResult:
    """Complete composite valuation result."""
    dcf: DCFResult = field(default_factory=DCFResult)
    epv: EPVResult = field(default_factory=EPVResult)
    book_value: BookValueResult = field(default_factory=BookValueResult)
    weighted_intrinsic_value: float | None = None
    current_market_price: float | None = None
    margin_of_safety_pct: float | None = None
    assumptions_used: dict[str, Any] = field(default_factory=dict)
    weights_applied: dict[str, float] = field(default_factory=dict)

    def to_calculation_details(self) -> dict[str, Any]:
        return {
            "dcf": self.dcf.to_dict(),
            "epv": self.epv.to_dict(),
            "book_value": self.book_value.to_dict(),
            "weights_applied": self.weights_applied,
        }


# ---------------------------------------------------------------------------
# Step 24: DCF Valuation Calculator
# ---------------------------------------------------------------------------

def calculate_dcf(
    financials: list[FinancialStatement],
    shares_outstanding: int,
    assumptions: dict[str, Any] | None = None,
) -> DCFResult:
    """Calculate intrinsic value per share using Discounted Cash Flow method.

    Projects FCF from historical trend using average growth rate (capped),
    then adds terminal value using Gordon Growth Model.

    Formula:
        V = Σ(t=1..n) FCF_t/(1+r)^t + FCF_n(1+g)/((r-g)(1+r)^n)

    Args:
        financials: List of FinancialStatement sorted by fiscal_year ascending.
        shares_outstanding: Total shares outstanding for per-share calculation.
        assumptions: Override default assumptions dict.

    Returns:
        DCFResult with value or error message.
    """
    result = DCFResult()
    params = {**DEFAULT_ASSUMPTIONS, **(assumptions or {})}

    if not shares_outstanding or shares_outstanding <= 0:
        result.error = "Invalid or missing shares_outstanding"
        return result

    # Extract FCF data (sorted by year ascending)
    fcf_data = []
    for fs in sorted(financials, key=lambda f: f.fiscal_year):
        fcf = _get_numeric(fs.free_cash_flow)
        if fcf is not None:
            fcf_data.append(fcf)

    result.historical_fcfs = fcf_data
    min_years = params["min_years_for_dcf"]

    if len(fcf_data) < min_years:
        result.error = f"Insufficient FCF data: need {min_years} years, have {len(fcf_data)}"
        return result

    # Calculate growth rate from historical FCF
    # Use full-period CAGR first; if negative, try recent 3 years for recovery detection
    growth_rate = _calculate_cagr(fcf_data)

    if growth_rate < 0 and len(fcf_data) >= 3:
        # Full-period growth is negative, check if recent years show recovery
        recent_cagr = _calculate_cagr(fcf_data[-3:])
        if recent_cagr > 0:
            # Use the recent recovery growth rate (more relevant for projections)
            growth_rate = recent_cagr

    # Cap growth rate conservatively
    growth_rate = max(
        params["min_growth_rate_floor"],
        min(growth_rate, params["max_growth_rate_cap"]),
    )
    result.growth_rate_used = growth_rate

    # Use the most recent FCF as the base
    base_fcf = fcf_data[-1]
    if base_fcf <= 0:
        # If latest FCF is negative, try using average of positive FCFs
        positive_fcfs = [f for f in fcf_data if f > 0]
        if not positive_fcfs:
            result.error = "All historical FCFs are negative or zero"
            return result
        base_fcf = statistics.mean(positive_fcfs)

    # Project FCFs for n years
    discount_rate = params["discount_rate"]
    terminal_growth = params["terminal_growth_rate"]
    n_years = params["projection_years"]

    projected_fcfs = []
    pv_fcfs = 0.0

    for t in range(1, n_years + 1):
        projected_fcf = base_fcf * ((1 + growth_rate) ** t)
        projected_fcfs.append(projected_fcf)
        pv_fcfs += projected_fcf / ((1 + discount_rate) ** t)

    result.projected_fcfs = projected_fcfs

    # Terminal value using Gordon Growth Model
    final_fcf = projected_fcfs[-1]
    if discount_rate <= terminal_growth:
        result.error = "Discount rate must exceed terminal growth rate"
        return result

    terminal_value = (final_fcf * (1 + terminal_growth)) / (discount_rate - terminal_growth)
    pv_terminal = terminal_value / ((1 + discount_rate) ** n_years)
    result.terminal_value = terminal_value

    # Total intrinsic value
    total_value = pv_fcfs + pv_terminal
    result.total_intrinsic_value = total_value
    result.intrinsic_value_per_share = total_value / shares_outstanding

    return result


# ---------------------------------------------------------------------------
# Step 25: EPV Valuation Calculator
# ---------------------------------------------------------------------------

def calculate_epv(
    financials: list[FinancialStatement],
    shares_outstanding: int,
    assumptions: dict[str, Any] | None = None,
) -> EPVResult:
    """Calculate intrinsic value per share using Earnings Power Value.

    Formula:
        EPV = Normalized Earnings / Cost of Capital

    Normalized earnings = average net income over available years,
    with outliers removed (values > 2 std deviations from mean).

    Args:
        financials: List of FinancialStatement objects.
        shares_outstanding: Total shares outstanding.
        assumptions: Override default assumptions dict.

    Returns:
        EPVResult with value or error message.
    """
    result = EPVResult()
    params = {**DEFAULT_ASSUMPTIONS, **(assumptions or {})}

    if not shares_outstanding or shares_outstanding <= 0:
        result.error = "Invalid or missing shares_outstanding"
        return result

    # Extract net income data
    earnings = []
    for fs in sorted(financials, key=lambda f: f.fiscal_year):
        ni = _get_numeric(fs.net_income)
        if ni is not None:
            earnings.append(ni)

    result.earnings_used = earnings
    min_years = params["min_years_for_epv"]

    if len(earnings) < min_years:
        result.error = f"Insufficient earnings data: need {min_years} years, have {len(earnings)}"
        return result

    # Remove outliers using std deviation method
    filtered_earnings = _remove_outliers(earnings, params["outlier_std_multiplier"])
    result.earnings_after_outlier_removal = filtered_earnings

    if not filtered_earnings:
        result.error = "All earnings removed as outliers"
        return result

    # Normalized earnings = mean of filtered earnings
    normalized = statistics.mean(filtered_earnings)
    result.normalized_earnings = normalized

    if normalized <= 0:
        result.error = "Normalized earnings are negative — EPV not meaningful"
        return result

    # EPV = Normalized Earnings / Cost of Capital
    cost_of_capital = params["discount_rate"]
    total_epv = normalized / cost_of_capital
    result.intrinsic_value_per_share = total_epv / shares_outstanding

    return result


# ---------------------------------------------------------------------------
# Step 26: Book Value Estimation
# ---------------------------------------------------------------------------

def calculate_book_value(
    financials: list[FinancialStatement],
    shares_outstanding: int,
) -> BookValueResult:
    """Calculate book value per share.

    Formula:
        BV/share = Total Equity / Shares Outstanding

    Uses the most recent financial statement. Falls back to reported
    book_value_per_share if total_equity is not available.

    Args:
        financials: List of FinancialStatement objects.
        shares_outstanding: Total shares outstanding.

    Returns:
        BookValueResult with value or error message.
    """
    result = BookValueResult()

    if not financials:
        result.error = "No financial statements available"
        return result

    # Use most recent financial data
    latest = max(financials, key=lambda f: f.fiscal_year)

    # Try computing from total_equity / shares_outstanding
    total_equity = _get_numeric(latest.total_equity)
    if total_equity is None:
        # Fallback: try shareholders_equity
        total_equity = _get_numeric(latest.shareholders_equity)

    if total_equity is not None and shares_outstanding and shares_outstanding > 0:
        result.total_equity = total_equity
        result.shares_outstanding = shares_outstanding
        result.book_value_per_share = total_equity / shares_outstanding
        result.source = "computed"
        return result

    # Fallback: use reported book_value_per_share
    bvps = _get_numeric(latest.book_value_per_share)
    if bvps is not None:
        result.book_value_per_share = bvps
        result.source = "reported"
        return result

    result.error = "No equity data or book value per share available"
    return result


# ---------------------------------------------------------------------------
# Step 27: Weighted Intrinsic Value Composite
# ---------------------------------------------------------------------------

def calculate_weighted_intrinsic_value(
    dcf_value: float | None,
    epv_value: float | None,
    bv_value: float | None,
    assumptions: dict[str, Any] | None = None,
) -> tuple[float | None, dict[str, float]]:
    """Calculate intrinsic value — pure DCF when available, fallback to EPV+BV.

    Strategy:
        - If DCF is available: use 100% DCF (pure DCF valuation)
        - If DCF unavailable: use EPV (70%) + BV (30%) as fallback
        - If only one fallback available: use it at 100%

    Args:
        dcf_value: DCF intrinsic value per share (or None).
        epv_value: EPV intrinsic value per share (or None).
        bv_value: Book value per share (or None).
        assumptions: Override default assumptions dict.

    Returns:
        Tuple of (weighted_value, weights_actually_applied).
    """
    params = {**DEFAULT_ASSUMPTIONS, **(assumptions or {})}

    # Primary: Pure DCF when available
    if dcf_value is not None and dcf_value > 0:
        return dcf_value, {"dcf": 1.0}

    # Fallback: EPV + BV blend when no DCF
    available: dict[str, float] = {}
    raw_weights: dict[str, float] = {}

    if epv_value is not None and epv_value > 0:
        available["epv"] = epv_value
        raw_weights["epv"] = params["fallback_epv_weight"]
    if bv_value is not None and bv_value > 0:
        available["bv"] = bv_value
        raw_weights["bv"] = params["fallback_bv_weight"]

    if not available:
        return None, {}

    # Normalize weights so they sum to 1.0
    total_weight = sum(raw_weights.values())
    normalized_weights = {k: v / total_weight for k, v in raw_weights.items()}

    # Calculate weighted value
    weighted_value = sum(
        available[k] * normalized_weights[k] for k in available
    )

    return weighted_value, normalized_weights


# ---------------------------------------------------------------------------
# Step 28: Margin of Safety Calculation
# ---------------------------------------------------------------------------

def calculate_margin_of_safety(
    intrinsic_value: float | None,
    market_price: float | None,
) -> float | None:
    """Calculate margin of safety percentage.

    Formula:
        MOS = 1 - (Market Price / Intrinsic Value)

    A positive MOS means the stock is trading below intrinsic value (undervalued).
    A negative MOS means overvalued.

    Args:
        intrinsic_value: Computed intrinsic value per share.
        market_price: Current market price per share.

    Returns:
        Margin of safety as a decimal (e.g., 0.30 = 30%), or None.
    """
    if intrinsic_value is None or market_price is None:
        return None
    if intrinsic_value <= 0:
        return None

    return 1.0 - (market_price / intrinsic_value)


# ---------------------------------------------------------------------------
# Step 29: Compute full valuation and persist to DB
# ---------------------------------------------------------------------------

def compute_valuation(
    db: Session,
    company_id: int,
    assumptions: dict[str, Any] | None = None,
    valuation_date: date | None = None,
) -> ValuationResult | str:
    """Compute full valuation for a company and store as a snapshot.

    Orchestrates DCF, EPV, Book Value, composite IV, and MOS calculations.
    Persists the result to the intrinsic_values table.

    Args:
        db: Database session.
        company_id: ID of the company to value.
        assumptions: Override default assumptions (or None for defaults).
        valuation_date: Date for the valuation (defaults to today).

    Returns:
        ValuationResult on success, or error string.
    """
    if valuation_date is None:
        valuation_date = date.today()

    params = {**DEFAULT_ASSUMPTIONS, **(assumptions or {})}

    # Load company
    company = db.query(Company).filter(Company.id == company_id).first()
    if company is None:
        return "company_not_found"

    shares = company.shares_outstanding
    if not shares or shares <= 0:
        return "no_shares_outstanding"

    # Load financial statements
    financials = (
        db.query(FinancialStatement)
        .filter(FinancialStatement.company_id == company_id)
        .order_by(FinancialStatement.fiscal_year)
        .all()
    )

    if not financials:
        return "no_financial_data"

    # Get current market price (latest close)
    latest_price_record = (
        db.query(PriceHistory)
        .filter(PriceHistory.company_id == company_id)
        .order_by(desc(PriceHistory.price_date))
        .first()
    )
    market_price = float(latest_price_record.close_price) if latest_price_record else None

    # Run calculations
    dcf_result = calculate_dcf(financials, shares, params)
    epv_result = calculate_epv(financials, shares, params)
    bv_result = calculate_book_value(financials, shares)

    # Composite value
    weighted_iv, weights_applied = calculate_weighted_intrinsic_value(
        dcf_result.intrinsic_value_per_share,
        epv_result.intrinsic_value_per_share,
        bv_result.book_value_per_share,
        params,
    )

    # Margin of safety
    mos = calculate_margin_of_safety(weighted_iv, market_price)

    # Build result
    valuation = ValuationResult(
        dcf=dcf_result,
        epv=epv_result,
        book_value=bv_result,
        weighted_intrinsic_value=weighted_iv,
        current_market_price=market_price,
        margin_of_safety_pct=mos,
        assumptions_used=params,
        weights_applied=weights_applied,
    )

    # Persist to DB
    iv_record = IntrinsicValue(
        company_id=company_id,
        valuation_date=valuation_date,
        dcf_value=dcf_result.intrinsic_value_per_share,
        epv_value=epv_result.intrinsic_value_per_share,
        book_value_estimate=bv_result.book_value_per_share,
        weighted_intrinsic_value=weighted_iv,
        current_market_price=market_price,
        margin_of_safety_pct=mos,
        assumptions=params,
        calculation_details=valuation.to_calculation_details(),
        calculated_at=datetime.utcnow(),
    )
    db.add(iv_record)
    db.flush()

    logger.info(
        f"Valuation computed for company_id={company_id}: "
        f"IV={weighted_iv}, MOS={mos}, price={market_price}"
    )

    return valuation


def compute_all_valuations(
    db: Session,
    assumptions: dict[str, Any] | None = None,
) -> dict[int, str | ValuationResult]:
    """Compute valuations for all active companies.

    Returns a dict mapping company_id → ValuationResult or error string.
    """
    companies = db.query(Company).filter(Company.is_active == True).all()
    results: dict[int, str | ValuationResult] = {}

    for company in companies:
        try:
            result = compute_valuation(db, company.id, assumptions)
            results[company.id] = result
        except Exception as e:
            logger.error(f"Error computing valuation for company_id={company.id}: {e}")
            results[company.id] = f"error: {str(e)}"

    db.commit()
    return results


# ---------------------------------------------------------------------------
# Utility functions
# ---------------------------------------------------------------------------

def _get_numeric(value: Any) -> float | None:
    """Safely convert a potentially Decimal/None value to float."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _calculate_cagr(values: list[float]) -> float:
    """Calculate Compound Annual Growth Rate from a list of values.

    Uses the first and last positive values. Falls back to simple average
    growth rate if CAGR calculation would fail (e.g., negative values).
    """
    if len(values) < 2:
        return 0.0

    # Filter to use first and last values
    first_val = values[0]
    last_val = values[-1]
    n_periods = len(values) - 1

    # If both positive, use standard CAGR formula
    if first_val > 0 and last_val > 0 and n_periods > 0:
        return (last_val / first_val) ** (1.0 / n_periods) - 1.0

    # Fallback: average year-over-year growth rates for positive pairs
    growth_rates = []
    for i in range(1, len(values)):
        if values[i - 1] > 0:
            growth_rates.append((values[i] - values[i - 1]) / values[i - 1])

    if growth_rates:
        return statistics.mean(growth_rates)

    return 0.0


def _remove_outliers(values: list[float], std_multiplier: float = 2.0) -> list[float]:
    """Remove statistical outliers from a list of values.

    Uses median-based detection (MAD) which is robust against the outlier
    inflating the standard deviation. Falls back to mean/std if MAD is zero.
    """
    if len(values) < 3:
        return values  # Too few values to meaningfully detect outliers

    # Use median-based detection (robust against the outlier itself)
    median = statistics.median(values)
    abs_deviations = [abs(v - median) for v in values]
    mad = statistics.median(abs_deviations)

    if mad == 0:
        # All values are close to median; use mean/std fallback
        mean = statistics.mean(values)
        std = statistics.stdev(values)
        if std == 0:
            return values
        return [v for v in values if abs(v - mean) <= std_multiplier * std]

    # MAD-based threshold: values > std_multiplier * 1.4826 * MAD from median
    # 1.4826 is the consistency constant for normal distribution
    threshold = std_multiplier * 1.4826 * mad
    return [v for v in values if abs(v - median) <= threshold]
