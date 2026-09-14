"""Industrial-company valuation strategy — DCF + EPV + Book Value.

This is the historical StockUp valuation logic, extracted from
``app/services/valuation_engine.py`` and wrapped in the sector strategy
interface. Numeric behaviour is unchanged for any company that classified
as INDUSTRIAL (which is the default).
"""

from __future__ import annotations

import logging
import statistics
from typing import Any

from app.models.company import Company
from app.models.financial_statement import FinancialStatement

from .base import (
    BookValueResult,
    DCFResult,
    EPVResult,
    SectorValuator,
    ValuationResult,
    calculate_expected_return,
    calculate_margin_of_safety,
    get_numeric,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Default assumptions (conservative for Kenyan market)
# ---------------------------------------------------------------------------

DEFAULT_ASSUMPTIONS: dict[str, Any] = {
    "discount_rate": 0.12,          # 12% — higher risk premium for frontier market
    "terminal_growth_rate": 0.03,   # 3% — long-term GDP proxy
    "projection_years": 10,
    "max_growth_rate_cap": 0.20,    # Cap FCF growth at 20%
    "min_growth_rate_floor": -0.05, # Floor at -5%
    "dcf_weight": 1.00,
    "epv_weight": 0.00,
    "bv_weight": 0.00,
    "fallback_epv_weight": 0.70,
    "fallback_bv_weight": 0.30,
    "min_years_for_dcf": 3,
    "min_years_for_epv": 2,
    "outlier_std_multiplier": 2.0,
    # Bear/base/bull scenarios shift the FCF growth rate by this many
    # percentage points either side of ``growth_rate_used`` (still capped
    # by max_growth_rate_cap / min_growth_rate_floor).
    "scenario_growth_delta": 0.04,
    # Horizon used for the Buffett-style expected return computation.
    "expected_return_horizon_years": 5,
}


# ---------------------------------------------------------------------------
# DCF
# ---------------------------------------------------------------------------

def calculate_dcf(
    financials: list[FinancialStatement],
    shares_outstanding: int,
    assumptions: dict[str, Any] | None = None,
) -> DCFResult:
    """Discounted cash flow — historical StockUp implementation."""
    result = DCFResult()
    params = {**DEFAULT_ASSUMPTIONS, **(assumptions or {})}

    if not shares_outstanding or shares_outstanding <= 0:
        result.error = "Invalid or missing shares_outstanding"
        return result

    fcf_data: list[float] = []
    for fs in sorted(financials, key=lambda f: f.fiscal_year):
        fcf = get_numeric(fs.free_cash_flow)
        if fcf is None:
            continue
        # Sanity guard: cap AI-hallucinated FCFs.
        revenue = get_numeric(fs.revenue)
        net_income = get_numeric(fs.net_income)
        if revenue and revenue > 0 and net_income is not None:
            max_reasonable = max(abs(net_income), revenue * 0.30)
            if fcf > max_reasonable * 1.5:
                logger.warning(
                    "FCF sanity cap: company_id=%s year=%s FCF=%.0f "
                    "capped to %.0f (revenue=%.0f, net_income=%.0f)",
                    fs.company_id, fs.fiscal_year, fcf,
                    max_reasonable, revenue, net_income,
                )
                fcf = max_reasonable
        fcf_data.append(fcf)

    result.historical_fcfs = fcf_data
    min_years = params["min_years_for_dcf"]

    if len(fcf_data) < min_years:
        result.error = f"Insufficient FCF data: need {min_years} years, have {len(fcf_data)}"
        return result

    growth_rate = _calculate_cagr(fcf_data)
    if growth_rate < 0 and len(fcf_data) >= 3:
        recent_cagr = _calculate_cagr(fcf_data[-3:])
        if recent_cagr > 0:
            growth_rate = recent_cagr

    growth_rate = max(
        params["min_growth_rate_floor"],
        min(growth_rate, params["max_growth_rate_cap"]),
    )
    result.growth_rate_used = growth_rate

    base_fcf = fcf_data[-1]
    if base_fcf <= 0:
        positive_fcfs = [f for f in fcf_data if f > 0]
        if not positive_fcfs:
            result.error = "All historical FCFs are negative or zero"
            return result
        base_fcf = statistics.mean(positive_fcfs)

    discount_rate = params["discount_rate"]
    terminal_growth = params["terminal_growth_rate"]
    n_years = params["projection_years"]

    # Record assumptions actually applied so the UI can render them without
    # having to reverse-engineer from ``assumptions_used``.
    result.base_fcf = base_fcf
    result.discount_rate = discount_rate
    result.terminal_growth_rate = terminal_growth
    result.projection_years = n_years

    projected_fcfs: list[float] = []
    pv_fcfs = 0.0
    for t in range(1, n_years + 1):
        projected = base_fcf * ((1 + growth_rate) ** t)
        projected_fcfs.append(projected)
        pv_fcfs += projected / ((1 + discount_rate) ** t)

    result.projected_fcfs = projected_fcfs

    if discount_rate <= terminal_growth:
        result.error = "Discount rate must exceed terminal growth rate"
        return result

    final_fcf = projected_fcfs[-1]
    terminal_value = (final_fcf * (1 + terminal_growth)) / (discount_rate - terminal_growth)
    pv_terminal = terminal_value / ((1 + discount_rate) ** n_years)
    result.terminal_value = terminal_value

    total_value = pv_fcfs + pv_terminal
    result.total_intrinsic_value = total_value
    result.intrinsic_value_per_share = total_value / shares_outstanding
    return result


# ---------------------------------------------------------------------------
# EPV
# ---------------------------------------------------------------------------

def calculate_epv(
    financials: list[FinancialStatement],
    shares_outstanding: int,
    assumptions: dict[str, Any] | None = None,
) -> EPVResult:
    """Earnings power value — normalised earnings / cost of capital."""
    result = EPVResult()
    params = {**DEFAULT_ASSUMPTIONS, **(assumptions or {})}

    if not shares_outstanding or shares_outstanding <= 0:
        result.error = "Invalid or missing shares_outstanding"
        return result

    earnings: list[float] = []
    for fs in sorted(financials, key=lambda f: f.fiscal_year):
        ni = get_numeric(fs.net_income)
        if ni is not None:
            earnings.append(ni)

    result.earnings_used = earnings
    min_years = params["min_years_for_epv"]
    if len(earnings) < min_years:
        result.error = f"Insufficient earnings data: need {min_years} years, have {len(earnings)}"
        return result

    filtered = _remove_outliers(earnings, params["outlier_std_multiplier"])
    result.earnings_after_outlier_removal = filtered
    if not filtered:
        result.error = "All earnings removed as outliers"
        return result

    normalized = statistics.mean(filtered)
    result.normalized_earnings = normalized
    if normalized <= 0:
        result.error = "Normalized earnings are negative — EPV not meaningful"
        return result

    cost_of_capital = params["discount_rate"]
    total_epv = normalized / cost_of_capital
    result.intrinsic_value_per_share = total_epv / shares_outstanding
    return result


# ---------------------------------------------------------------------------
# Book value
# ---------------------------------------------------------------------------

def calculate_book_value(
    financials: list[FinancialStatement],
    shares_outstanding: int,
) -> BookValueResult:
    result = BookValueResult()
    if not financials:
        result.error = "No financial statements available"
        return result

    latest = max(financials, key=lambda f: f.fiscal_year)
    total_equity = get_numeric(latest.total_equity)
    if total_equity is None:
        total_equity = get_numeric(latest.shareholders_equity)

    if total_equity is not None and shares_outstanding and shares_outstanding > 0:
        result.total_equity = total_equity
        result.shares_outstanding = shares_outstanding
        result.book_value_per_share = total_equity / shares_outstanding
        result.source = "computed"
        return result

    bvps = get_numeric(latest.book_value_per_share)
    if bvps is not None:
        result.book_value_per_share = bvps
        result.source = "reported"
        return result

    result.error = "No equity data or book value per share available"
    return result


# ---------------------------------------------------------------------------
# Weighted composite
# ---------------------------------------------------------------------------

def calculate_weighted_intrinsic_value(
    dcf_value: float | None,
    epv_value: float | None,
    bv_value: float | None,
    assumptions: dict[str, Any] | None = None,
) -> tuple[float | None, dict[str, float]]:
    """Pure DCF when available, else EPV+BV fallback."""
    params = {**DEFAULT_ASSUMPTIONS, **(assumptions or {})}

    if dcf_value is not None and dcf_value > 0:
        return dcf_value, {"dcf": 1.0}

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

    total_weight = sum(raw_weights.values())
    normalized_weights = {k: v / total_weight for k, v in raw_weights.items()}
    weighted_value = sum(available[k] * normalized_weights[k] for k in available)
    return weighted_value, normalized_weights


# ---------------------------------------------------------------------------
# Strategy adapter
# ---------------------------------------------------------------------------

class IndustrialValuator(SectorValuator):
    """Wraps the DCF+EPV+BV pipeline in the sector-strategy interface."""

    model_name = "industrial_dcf"

    def value(
        self,
        company: Company,
        financials: list[FinancialStatement],
        market_price: float | None,
        assumptions: dict[str, Any] | None = None,
    ) -> ValuationResult:
        params = {**DEFAULT_ASSUMPTIONS, **(assumptions or {})}
        shares = company.shares_outstanding or 0

        dcf = calculate_dcf(financials, shares, params)
        epv = calculate_epv(financials, shares, params)
        bv = calculate_book_value(financials, shares)

        weighted_iv, weights = calculate_weighted_intrinsic_value(
            dcf.intrinsic_value_per_share,
            epv.intrinsic_value_per_share,
            bv.book_value_per_share,
            params,
        )
        mos = calculate_margin_of_safety(weighted_iv, market_price)

        # --- Bear / base / bull scenarios -----------------------------------
        # Only meaningful when the base DCF succeeded; otherwise we surface
        # nothing and let the frontend show a fallback.
        scenario_values: dict[str, float] = {}
        scenario_growth: dict[str, float] = {}
        notes: list[str] = []
        if (
            dcf.intrinsic_value_per_share is not None
            and dcf.growth_rate_used is not None
            and dcf.base_fcf is not None
            and dcf.discount_rate is not None
            and dcf.terminal_growth_rate is not None
            and dcf.projection_years
            and shares > 0
        ):
            delta = float(params["scenario_growth_delta"])
            floor = float(params["min_growth_rate_floor"])
            cap = float(params["max_growth_rate_cap"])
            base_g = float(dcf.growth_rate_used)
            bear_g = max(floor, base_g - delta)
            bull_g = min(cap, base_g + delta)

            bear_iv = _dcf_value_for_growth(
                base_fcf=dcf.base_fcf,
                growth_rate=bear_g,
                discount_rate=dcf.discount_rate,
                terminal_growth=dcf.terminal_growth_rate,
                n_years=dcf.projection_years,
                shares=shares,
            )
            bull_iv = _dcf_value_for_growth(
                base_fcf=dcf.base_fcf,
                growth_rate=bull_g,
                discount_rate=dcf.discount_rate,
                terminal_growth=dcf.terminal_growth_rate,
                n_years=dcf.projection_years,
                shares=shares,
            )
            if bear_iv is not None and bull_iv is not None:
                scenario_values = {
                    "bear": round(bear_iv, 4),
                    "base": round(float(dcf.intrinsic_value_per_share), 4),
                    "bull": round(bull_iv, 4),
                }
                scenario_growth = {"bear": bear_g, "base": base_g, "bull": bull_g}
                notes.append(
                    f"scenarios: bear g={bear_g:.2%}, base g={base_g:.2%}, "
                    f"bull g={bull_g:.2%} (discount={dcf.discount_rate:.2%}, "
                    f"terminal={dcf.terminal_growth_rate:.2%})"
                )

        # --- Expected forward return ---------------------------------------
        # Uses scenarios computed above + trailing dividend yield. Assumes
        # that at horizon N the market re-rates to fair value, with IV
        # compounding at each scenario's growth rate.
        div_yield = _trailing_dividend_yield(financials, market_price)
        horizon = int(params.get("expected_return_horizon_years", 5))
        expected_return = calculate_expected_return(
            scenario_ivs=scenario_values,
            scenario_growth_rates=scenario_growth,
            market_price=market_price,
            dividend_yield=div_yield,
            horizon_years=horizon,
        )
        if expected_return is not None:
            base_er = expected_return["scenarios"].get("base", {}).get("annualized_return")
            if base_er is not None:
                notes.append(
                    f"expected {horizon}y return (base): {base_er:.1%} "
                    f"(div yield {div_yield:.1%})"
                )

        return ValuationResult(
            dcf=dcf,
            epv=epv,
            book_value=bv,
            weighted_intrinsic_value=weighted_iv,
            current_market_price=market_price,
            margin_of_safety_pct=mos,
            assumptions_used=params,
            weights_applied=weights,
            model_used=self.model_name,
            scenario_values=scenario_values,
            notes=notes,
            expected_return=expected_return,
        )


def _dcf_value_for_growth(
    *,
    base_fcf: float,
    growth_rate: float,
    discount_rate: float,
    terminal_growth: float,
    n_years: int,
    shares: int,
) -> float | None:
    """Run a Gordon-growth DCF with a caller-supplied growth rate.

    Returns intrinsic value per share, or ``None`` if the inputs make the
    calculation ill-defined (e.g. discount ≤ terminal growth).
    """
    if shares <= 0 or n_years <= 0:
        return None
    if discount_rate <= terminal_growth:
        return None

    pv_fcfs = 0.0
    final_fcf = base_fcf
    for t in range(1, n_years + 1):
        projected = base_fcf * ((1 + growth_rate) ** t)
        pv_fcfs += projected / ((1 + discount_rate) ** t)
        final_fcf = projected

    terminal_value = (final_fcf * (1 + terminal_growth)) / (discount_rate - terminal_growth)
    pv_terminal = terminal_value / ((1 + discount_rate) ** n_years)
    return (pv_fcfs + pv_terminal) / shares


def _trailing_dividend_yield(
    financials: list[FinancialStatement],
    market_price: float | None,
) -> float:
    """Latest reported DPS / current price. 0.0 when either is missing."""
    if not financials or not market_price or market_price <= 0:
        return 0.0
    latest = max(financials, key=lambda f: f.fiscal_year)
    dps = get_numeric(latest.dividends_per_share)
    if dps is None or dps <= 0:
        return 0.0
    return dps / market_price


# ---------------------------------------------------------------------------
# Internal helpers (also re-exported from valuation_engine shim)
# ---------------------------------------------------------------------------

def _calculate_cagr(values: list[float]) -> float:
    if len(values) < 2:
        return 0.0
    first_val = values[0]
    last_val = values[-1]
    n_periods = len(values) - 1
    if first_val > 0 and last_val > 0 and n_periods > 0:
        return (last_val / first_val) ** (1.0 / n_periods) - 1.0

    growth_rates = []
    for i in range(1, len(values)):
        if values[i - 1] > 0:
            growth_rates.append((values[i] - values[i - 1]) / values[i - 1])
    if growth_rates:
        return statistics.mean(growth_rates)
    return 0.0


def _remove_outliers(values: list[float], std_multiplier: float = 2.0) -> list[float]:
    if len(values) < 3:
        return values

    median = statistics.median(values)
    abs_deviations = [abs(v - median) for v in values]
    mad = statistics.median(abs_deviations)

    if mad == 0:
        mean = statistics.mean(values)
        std = statistics.stdev(values)
        if std == 0:
            return values
        return [v for v in values if abs(v - mean) <= std_multiplier * std]

    threshold = std_multiplier * 1.4826 * mad
    return [v for v in values if abs(v - median) <= threshold]
