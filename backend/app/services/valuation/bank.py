"""Bank valuation strategy — two-stage residual income + justified P/B + P/E.

Rationale (see plans/sector-specific-valuation.md):

Discounted cash flow does not work for banks. Free cash flow is not a
meaningful proxy for owner earnings, and customer deposits (which look like
"debt" on the balance sheet) are the raw material of the business rather
than a leverage constraint. Instead we value banks by the spread between
their return on equity and their cost of equity:

    V_RI     = BVPS_0 + Σ discounted residual income + terminal RI
    V_P/B    = BVPS_0 × (ROE_sustainable - g) / (r - g)
    V_P/E    = EPS_0 × payout × (1 + g) / (r - g)

Composite = 0.5·V_RI + 0.3·V_P/B + 0.2·V_P/E, minus a quality discount for
asset-quality problems (NPL ratio, cost of risk, capital adequacy).

Also computes conservative / base / strong scenarios for the frontend
decision-range table.
"""

from __future__ import annotations

import logging
from typing import Any

from app.models.company import Company
from app.models.financial_statement import FinancialStatement

from .base import (
    BookValueResult,
    DCFResult,
    EPVResult,
    SectorValuator,
    ValuationResult,
    calculate_margin_of_safety,
    get_numeric,
)

logger = logging.getLogger(__name__)


BANK_DEFAULT_ASSUMPTIONS: dict[str, Any] = {
    "cost_of_equity": 0.145,        # Risk-free ~13% + 1.5% bank equity premium
    "terminal_growth": 0.05,        # Long-term nominal GDP proxy for Kenya
    "high_growth_years": 5,         # Explicit ROE-holds-current window
    "fade_years": 5,                # Fade window from current ROE → sustainable
    "sustainable_roe_floor": 0.15,  # Min ROE assumed for terminal period
    "sustainable_roe_spread": 0.03, # sustainable_roe = r + spread (if higher than floor)
    "current_roe_cap": 0.25,        # Cap current ROE input at 25% (avoid over-extrapolation)
    "min_payout": 0.25,             # Minimum assumed payout ratio
    "max_payout": 0.60,             # Cap payout for growth calculation
    "max_growth_cap": 0.20,         # Cap year-on-year book value growth
    "weight_residual_income": 0.50,
    "weight_justified_pb": 0.30,
    "weight_justified_pe": 0.20,
    "npl_moderate_threshold": 0.10,
    "npl_severe_threshold": 0.15,
    "cor_elevated_threshold": 0.02,
    "car_tight_threshold": 0.145,
    "npl_moderate_penalty": 0.05,
    "npl_severe_penalty": 0.10,
    "cor_penalty": 0.05,
    "car_penalty": 0.10,
    "max_quality_discount": 0.25,
    # Scenario overrides
    "conservative_cost_of_equity": 0.155,
    "conservative_payout": 0.40,
    "conservative_terminal_roe_spread": 0.01,
    "strong_cost_of_equity": 0.135,
    "strong_payout": 0.25,
    # Scenario computed by using current ROE as sustainable ROE
}


class BankValuator(SectorValuator):
    """Residual-income-driven valuation for banks."""

    model_name = "bank_residual_income"

    def value(
        self,
        company: Company,
        financials: list[FinancialStatement],
        market_price: float | None,
        assumptions: dict[str, Any] | None = None,
    ) -> ValuationResult:
        params = {**BANK_DEFAULT_ASSUMPTIONS, **(assumptions or {})}
        shares = company.shares_outstanding or 0

        inputs, input_error = _extract_bank_inputs(financials, shares)
        if input_error:
            # Bail out with an empty result rather than crashing.  The
            # dispatcher will still persist the row so the frontend can
            # display "insufficient data".
            logger.warning(
                "Bank valuation for company_id=%s aborted: %s",
                company.id, input_error,
            )
            bv = BookValueResult(error=input_error)
            return ValuationResult(
                book_value=bv,
                current_market_price=market_price,
                assumptions_used=params,
                model_used=self.model_name,
                notes=[input_error],
            )

        # --- Base case ------------------------------------------------------
        base_value, base_components = _compute_bank_value(inputs, params)

        # Quality discount
        quality_adjustments = _quality_adjustments(inputs, params)
        total_penalty = min(
            sum(quality_adjustments.values()),
            params["max_quality_discount"],
        )
        base_value_adjusted = base_value * (1 - total_penalty)

        # --- Scenarios ------------------------------------------------------
        conservative = _compute_scenario(
            inputs, params, scenario="conservative",
        )
        strong = _compute_scenario(inputs, params, scenario="strong")

        scenario_values = {
            "conservative": round(conservative, 4),
            "base": round(base_value_adjusted, 4),
            "strong": round(strong, 4),
        }
        # Also record the pre-discount base value so users can inspect the
        # raw model output vs the quality-adjusted number.
        component_values = {
            k: round(v, 4) for k, v in base_components.items()
        }
        component_values["base_pre_quality_discount"] = round(base_value, 4)
        component_values["quality_discount_pct"] = round(total_penalty, 4)

        # --- Package result -------------------------------------------------
        # We reuse the DCF/EPV/BV result slots for backward compatibility with
        # the existing IntrinsicValue schema and frontend:
        #   dcf_value             ← residual income value (primary)
        #   epv_value             ← justified P/B value (secondary)
        #   book_value_estimate   ← book value per share (tertiary)
        dcf = DCFResult(
            intrinsic_value_per_share=round(base_components["residual_income"], 4),
            growth_rate_used=inputs["current_roe"],
        )
        epv = EPVResult(
            intrinsic_value_per_share=round(base_components["justified_pb"], 4),
            normalized_earnings=inputs["eps"],
        )
        bv = BookValueResult(
            book_value_per_share=round(inputs["bvps"], 4),
            total_equity=inputs["total_equity"],
            shares_outstanding=shares,
            source="computed",
        )

        mos = calculate_margin_of_safety(base_value_adjusted, market_price)

        weights = {
            "residual_income": params["weight_residual_income"],
            "justified_pb": params["weight_justified_pb"],
            "justified_pe": params["weight_justified_pe"],
        }

        notes = [
            f"cost_of_equity={params['cost_of_equity']:.3f}",
            f"terminal_growth={params['terminal_growth']:.3f}",
            f"current_roe={inputs['current_roe']:.3f}",
            f"sustainable_roe={inputs['sustainable_roe']:.3f}",
            f"payout={inputs['payout']:.3f}",
        ]
        if total_penalty > 0:
            notes.append(
                f"quality_discount={total_penalty:.1%} applied "
                f"(NPL={inputs.get('npl_ratio')}, "
                f"CoR={inputs.get('cost_of_risk')}, "
                f"CAR={inputs.get('capital_adequacy_ratio')})"
            )

        return ValuationResult(
            dcf=dcf,
            epv=epv,
            book_value=bv,
            weighted_intrinsic_value=round(base_value_adjusted, 4),
            current_market_price=market_price,
            margin_of_safety_pct=mos,
            assumptions_used=params,
            weights_applied=weights,
            model_used=self.model_name,
            scenario_values=scenario_values,
            component_values=component_values,
            quality_adjustments=quality_adjustments,
            notes=notes,
        )


# ---------------------------------------------------------------------------
# Input extraction
# ---------------------------------------------------------------------------

def _extract_bank_inputs(
    financials: list[FinancialStatement],
    shares_outstanding: int,
) -> tuple[dict[str, Any], str | None]:
    """Pull the latest year's bank-relevant inputs.

    Returns (inputs, error) where ``error`` is a human-readable reason the
    valuation cannot proceed (e.g. no equity data). ``inputs`` is populated
    on a best-effort basis so quality adjustments still work when partial
    sector_metrics are available.
    """
    if not financials:
        return {}, "no_financial_data"
    if not shares_outstanding or shares_outstanding <= 0:
        return {}, "no_shares_outstanding"

    latest = max(financials, key=lambda f: f.fiscal_year)

    # Equity priority: shareholders_equity (attributable to parent, the correct
    # base for per-share BVPS and ROE) → total_equity (may include minorities)
    # → last resort. In practice audited filings report both; StockUp's ingest
    # occasionally maps them inconsistently so we prefer the attributable
    # figure explicitly.
    total_equity = get_numeric(latest.shareholders_equity)
    if total_equity is None:
        total_equity = get_numeric(latest.total_equity)
    if total_equity is None or total_equity <= 0:
        return {}, "no_equity_data"

    # BVPS priority: reported book_value_per_share (already reconciled to
    # attributable equity in the filing) → derived from equity/shares.
    bvps = get_numeric(latest.book_value_per_share)
    if bvps is None or bvps <= 0:
        bvps = total_equity / shares_outstanding

    net_income = get_numeric(latest.net_income)

    # ROE priority: reported → computed from net_income/equity (using the
    # same equity source as BVPS so justified P/B stays internally
    # consistent).
    current_roe = get_numeric(latest.return_on_equity)
    if current_roe is None and net_income is not None and total_equity > 0:
        current_roe = net_income / total_equity
    if current_roe is None:
        return {}, "no_roe_data"

    # EPS priority: reported → computed.
    eps = get_numeric(latest.earnings_per_share)
    if eps is None and net_income is not None:
        eps = net_income / shares_outstanding

    # Payout ratio inferred from DPS/EPS if both available; else default.
    dps = get_numeric(latest.dividends_per_share)
    payout: float | None = None
    if dps is not None and eps is not None and eps > 0:
        payout = max(0.0, min(1.0, dps / eps))

    # Sector metrics
    sm = latest.sector_metrics or {}
    npl_ratio = _read_metric(sm, "npl_ratio")
    cost_of_risk = _read_metric(sm, "cost_of_risk")
    capital_adequacy_ratio = _read_metric(sm, "capital_adequacy_ratio")
    tier1_ratio = _read_metric(sm, "tier1_ratio")
    net_interest_margin = _read_metric(sm, "net_interest_margin")
    cost_to_income = _read_metric(sm, "cost_to_income")
    loan_growth_pct = _read_metric(sm, "loan_growth_pct")
    deposit_growth_pct = _read_metric(sm, "deposit_growth_pct")

    return (
        {
            "bvps": bvps,
            "total_equity": total_equity,
            "eps": eps,
            "current_roe": current_roe,
            "payout": payout if payout is not None else 0.30,
            "payout_from_data": payout is not None,
            "dps": dps,
            "npl_ratio": npl_ratio,
            "cost_of_risk": cost_of_risk,
            "capital_adequacy_ratio": capital_adequacy_ratio,
            "tier1_ratio": tier1_ratio,
            "net_interest_margin": net_interest_margin,
            "cost_to_income": cost_to_income,
            "loan_growth_pct": loan_growth_pct,
            "deposit_growth_pct": deposit_growth_pct,
            # sustainable_roe filled by the value engine so scenario overrides
            # can adjust it.
            "sustainable_roe": None,
        },
        None,
    )


def _read_metric(metrics: dict[str, Any], key: str) -> float | None:
    return get_numeric(metrics.get(key))


# ---------------------------------------------------------------------------
# Core math
# ---------------------------------------------------------------------------

def _sustainable_roe(params: dict[str, Any]) -> float:
    return max(
        params["sustainable_roe_floor"],
        params["cost_of_equity"] + params["sustainable_roe_spread"],
    )


def _compute_bank_value(
    inputs: dict[str, Any],
    params: dict[str, Any],
) -> tuple[float, dict[str, float]]:
    """Return (composite_value, component_values) for the given params."""
    r = params["cost_of_equity"]
    g_t = params["terminal_growth"]
    high_years = int(params["high_growth_years"])
    fade_years = int(params["fade_years"])
    max_growth = params["max_growth_cap"]

    current_roe = min(inputs["current_roe"], params["current_roe_cap"])
    sustainable_roe = _sustainable_roe(params)
    inputs["sustainable_roe"] = sustainable_roe  # for notes

    payout = max(params["min_payout"], min(inputs["payout"], params["max_payout"]))
    retention = 1.0 - payout

    # ---- Residual income (two-stage) --------------------------------------
    bvps = inputs["bvps"]
    total_years = high_years + fade_years
    pv_ri_sum = 0.0
    bvps_t = bvps
    for t in range(1, total_years + 1):
        # ROE fades linearly across the fade window; stays flat during the
        # high-growth window.
        if t <= high_years:
            roe_t = current_roe
        else:
            fade_progress = (t - high_years) / fade_years
            roe_t = current_roe - fade_progress * (current_roe - sustainable_roe)

        ri_t = (roe_t - r) * bvps_t
        pv_ri_sum += ri_t / ((1 + r) ** t)

        # Cap book value growth per year so retention × very-high-ROE doesn't
        # explode.
        growth = min(roe_t * retention, max_growth)
        bvps_t = bvps_t * (1 + growth)

    # Terminal residual income (fades to sustainable_roe forever)
    if r > g_t:
        terminal_ri = (sustainable_roe - r) * bvps_t
        pv_terminal = (terminal_ri / (r - g_t)) / ((1 + r) ** total_years)
    else:
        pv_terminal = 0.0

    v_ri = bvps + pv_ri_sum + pv_terminal

    # ---- Justified P/B ----------------------------------------------------
    if r > g_t:
        v_pb = bvps * (sustainable_roe - g_t) / (r - g_t)
    else:
        v_pb = bvps

    # ---- Justified P/E ----------------------------------------------------
    eps = inputs["eps"] if inputs["eps"] is not None else current_roe * bvps
    if r > g_t:
        v_pe = eps * payout * (1 + g_t) / (r - g_t)
    else:
        v_pe = eps * 10  # crude fallback

    # ---- Weighted composite ----------------------------------------------
    w_ri = params["weight_residual_income"]
    w_pb = params["weight_justified_pb"]
    w_pe = params["weight_justified_pe"]
    weight_total = w_ri + w_pb + w_pe
    composite = (w_ri * v_ri + w_pb * v_pb + w_pe * v_pe) / weight_total

    return composite, {
        "residual_income": v_ri,
        "justified_pb": v_pb,
        "justified_pe": v_pe,
        "composite": composite,
    }


def _compute_scenario(
    inputs: dict[str, Any],
    base_params: dict[str, Any],
    scenario: str,
) -> float:
    """Recompute the composite value under scenario-specific overrides."""
    p = dict(base_params)
    scenario_inputs = dict(inputs)

    if scenario == "conservative":
        p["cost_of_equity"] = base_params["conservative_cost_of_equity"]
        p["sustainable_roe_spread"] = base_params["conservative_terminal_roe_spread"]
        scenario_inputs["payout"] = base_params["conservative_payout"]
    elif scenario == "strong":
        p["cost_of_equity"] = base_params["strong_cost_of_equity"]
        # Strong case assumes the current ROE persists indefinitely — but if
        # the current ROE is already at or below the base-case sustainable
        # ROE, use the base sustainable ROE as the floor so "strong" is
        # never numerically lower than "base".
        base_sustainable = max(
            base_params["sustainable_roe_floor"],
            base_params["cost_of_equity"] + base_params["sustainable_roe_spread"],
        )
        capped_current = min(inputs["current_roe"], base_params["current_roe_cap"])
        target = max(capped_current, base_sustainable)
        p["sustainable_roe_spread"] = target - p["cost_of_equity"]
        p["sustainable_roe_floor"] = target
        scenario_inputs["payout"] = base_params["strong_payout"]

    value, _ = _compute_bank_value(scenario_inputs, p)
    # Apply the same quality discount to keep scenarios directly comparable.
    penalty = min(
        sum(_quality_adjustments(inputs, base_params).values()),
        base_params["max_quality_discount"],
    )
    return value * (1 - penalty)


# ---------------------------------------------------------------------------
# Quality adjustments
# ---------------------------------------------------------------------------

def _quality_adjustments(
    inputs: dict[str, Any],
    params: dict[str, Any],
) -> dict[str, float]:
    """Return a dict of penalty_name → penalty_fraction.

    Penalties are additive; the caller is responsible for capping the sum at
    ``max_quality_discount``.
    """
    adjustments: dict[str, float] = {}

    npl = inputs.get("npl_ratio")
    if npl is not None:
        if npl > params["npl_severe_threshold"]:
            adjustments["npl_severe"] = params["npl_severe_penalty"]
        elif npl > params["npl_moderate_threshold"]:
            adjustments["npl_moderate"] = params["npl_moderate_penalty"]

    cor = inputs.get("cost_of_risk")
    if cor is not None and cor > params["cor_elevated_threshold"]:
        adjustments["cost_of_risk_elevated"] = params["cor_penalty"]

    car = inputs.get("capital_adequacy_ratio")
    if car is not None and car < params["car_tight_threshold"]:
        adjustments["capital_tight"] = params["car_penalty"]

    return adjustments
