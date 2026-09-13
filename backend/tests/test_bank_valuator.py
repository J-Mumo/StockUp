"""Tests for the bank valuation strategy.

Validates the residual-income + justified P/B + P/E composite against
KCB-like inputs and asserts the model does not crash on missing sector
metrics.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from app.models.company import Company
from app.models.financial_statement import FinancialStatement
from app.services.valuation import get_strategy
from app.services.valuation.bank import (
    BANK_DEFAULT_ASSUMPTIONS,
    BankValuator,
    _compute_bank_value,
    _quality_adjustments,
)
from app.services.valuation.sectors import SectorKind, classify_sector


def _make_bank_fs(
    fiscal_year: int,
    total_equity: float,
    net_income: float,
    shares_outstanding: int,
    dividends_per_share: float | None = None,
    return_on_equity: float | None = None,
    sector_metrics: dict | None = None,
) -> FinancialStatement:
    fs = MagicMock(spec=FinancialStatement)
    fs.fiscal_year = fiscal_year
    fs.total_equity = total_equity
    fs.shareholders_equity = total_equity
    fs.net_income = net_income
    fs.earnings_per_share = net_income / shares_outstanding
    fs.return_on_equity = return_on_equity if return_on_equity is not None else net_income / total_equity
    fs.dividends_per_share = dividends_per_share
    fs.book_value_per_share = total_equity / shares_outstanding
    fs.revenue = None
    fs.free_cash_flow = None
    fs.operating_cash_flow = None
    fs.capital_expenditures = None
    fs.total_assets = None
    fs.total_liabilities = None
    fs.debt_to_equity = None
    fs.current_ratio = None
    fs.sector_metrics = sector_metrics
    fs.company_id = 1
    return fs


def _make_bank_company(sector: str = "Banking") -> Company:
    company = MagicMock(spec=Company)
    company.id = 1
    company.ticker_symbol = "KCB"
    company.sector = sector
    company.shares_outstanding = 3_213_462_815
    return company


# ---------------------------------------------------------------------------
# Sector classification
# ---------------------------------------------------------------------------

class TestSectorClassification:
    def test_banking_classifies_bank(self):
        assert classify_sector("Banking") == SectorKind.BANK

    def test_lowercase_banking(self):
        assert classify_sector("banking") == SectorKind.BANK

    def test_manufacturing_classifies_industrial(self):
        assert classify_sector("Manufacturing") == SectorKind.INDUSTRIAL

    def test_none_defaults_industrial(self):
        assert classify_sector(None) == SectorKind.INDUSTRIAL

    def test_unknown_defaults_industrial(self):
        assert classify_sector("Widgets") == SectorKind.INDUSTRIAL


# ---------------------------------------------------------------------------
# Dispatcher wiring
# ---------------------------------------------------------------------------

class TestDispatcher:
    def test_banking_sector_gets_bank_strategy(self):
        strategy = get_strategy("Banking")
        assert isinstance(strategy, BankValuator)

    def test_industrial_sector_gets_industrial_strategy(self):
        from app.services.valuation.industrial import IndustrialValuator
        strategy = get_strategy("Manufacturing")
        assert isinstance(strategy, IndustrialValuator)

    def test_none_sector_falls_back_industrial(self):
        from app.services.valuation.industrial import IndustrialValuator
        strategy = get_strategy(None)
        assert isinstance(strategy, IndustrialValuator)


# ---------------------------------------------------------------------------
# Bank valuator — KCB-like scenario
#
# Inputs (from ChatGPT analysis of KCB FY2025):
#   BVPS   ≈ 103.15
#   ROE    ≈ 0.225
#   EPS    ≈ 22 (payout ≈ 32%)
#   NPL    ≈ 0.169
#   CoR    ≈ 0.028
#   CAR    ≈ 0.185
# Expected base-case IV in the 90–160 range (post quality discount).
# ---------------------------------------------------------------------------

class TestBankValuatorKCB:
    def _make_kcb_financials(self):
        shares = 3_213_462_815  # KCB approx
        equity = 103.15 * shares  # ≈ 331.5B
        net_income = 0.225 * equity  # ≈ 74.6B (close to reported 68.4B)
        return _make_bank_fs(
            fiscal_year=2025,
            total_equity=equity,
            net_income=net_income,
            shares_outstanding=shares,
            dividends_per_share=7.0,
            return_on_equity=0.225,
            sector_metrics={
                "npl_ratio": 0.169,
                "cost_of_risk": 0.028,
                "capital_adequacy_ratio": 0.185,
                "net_interest_margin": 0.076,
                "cost_to_income": 0.48,
                "loan_growth_pct": 0.10,
                "deposit_growth_pct": 0.08,
            },
        ), shares

    def test_kcb_base_case_lands_in_defensible_range(self):
        fs, shares = self._make_kcb_financials()
        company = _make_bank_company()
        company.shares_outstanding = shares

        result = BankValuator().value(
            company, [fs], market_price=94.0,
        )

        iv = result.weighted_intrinsic_value
        assert iv is not None
        # Base case (post quality discount) should be well below the broken
        # 1,083 industrial-DCF number, and well above the market price of 94.
        assert 90.0 < iv < 200.0, (
            f"KCB base-case IV {iv:.2f} outside defensible 90–200 window; "
            f"components={result.component_values}"
        )

    def test_kcb_scenarios_ordered(self):
        fs, shares = self._make_kcb_financials()
        company = _make_bank_company()
        company.shares_outstanding = shares

        result = BankValuator().value(company, [fs], market_price=94.0)
        s = result.scenario_values
        assert s["conservative"] < s["base"] < s["strong"], (
            f"Scenarios not ordered: {s}"
        )

    def test_kcb_records_bank_model_name(self):
        fs, shares = self._make_kcb_financials()
        company = _make_bank_company()
        company.shares_outstanding = shares

        result = BankValuator().value(company, [fs], market_price=94.0)
        assert result.model_used == "bank_residual_income"

    def test_quality_discount_applied_for_high_npl(self):
        fs, shares = self._make_kcb_financials()
        company = _make_bank_company()
        company.shares_outstanding = shares

        result = BankValuator().value(company, [fs], market_price=94.0)
        adjustments = result.quality_adjustments
        # KCB NPL 16.9% is above the severe threshold (15%).
        assert "npl_severe" in adjustments
        # Cost of risk 2.8% is above the elevated threshold.
        assert "cost_of_risk_elevated" in adjustments

    def test_kcb_produces_positive_margin_of_safety(self):
        fs, shares = self._make_kcb_financials()
        company = _make_bank_company()
        company.shares_outstanding = shares

        result = BankValuator().value(company, [fs], market_price=94.0)
        mos = result.margin_of_safety_pct
        assert mos is not None and mos > 0, (
            f"KCB should be undervalued at 94; MOS={mos}"
        )


# ---------------------------------------------------------------------------
# Graceful degradation
# ---------------------------------------------------------------------------

class TestBankValuatorMissingData:
    def test_missing_sector_metrics_still_produces_value(self):
        """No NPL/CAR — model should run, just without quality discounts."""
        shares = 1_000_000_000
        equity = 100.0 * shares
        fs = _make_bank_fs(
            fiscal_year=2025,
            total_equity=equity,
            net_income=0.20 * equity,
            shares_outstanding=shares,
            dividends_per_share=5.0,
            return_on_equity=0.20,
            sector_metrics=None,
        )
        company = _make_bank_company()
        company.shares_outstanding = shares

        result = BankValuator().value(company, [fs], market_price=80.0)
        assert result.weighted_intrinsic_value is not None
        assert result.quality_adjustments == {}

    def test_no_equity_returns_error_result(self):
        shares = 1_000_000_000
        fs = _make_bank_fs(
            fiscal_year=2025,
            total_equity=0.0,
            net_income=1_000_000,
            shares_outstanding=shares,
            return_on_equity=0.20,
        )
        company = _make_bank_company()
        company.shares_outstanding = shares

        result = BankValuator().value(company, [fs], market_price=50.0)
        assert result.weighted_intrinsic_value is None
        assert "no_equity_data" in "".join(result.notes)


# ---------------------------------------------------------------------------
# Formula sanity — pure math, no I/O
# ---------------------------------------------------------------------------

class TestBankValueFormulas:
    def test_zero_spread_gives_book_value_approx(self):
        """When ROE ≈ cost of equity, IV should ≈ book value."""
        inputs = {
            "bvps": 100.0,
            "current_roe": 0.145,   # equals default cost_of_equity
            "eps": 14.5,
            "payout": 0.30,
        }
        params = dict(BANK_DEFAULT_ASSUMPTIONS)
        # Force sustainable_roe = r as well
        params["sustainable_roe_floor"] = 0.145
        params["sustainable_roe_spread"] = 0.0

        value, comps = _compute_bank_value(inputs, params)
        # With no spread, all three components should hug book value.
        assert 80.0 < value < 130.0, f"got {value}, components={comps}"

    def test_higher_roe_gives_higher_value(self):
        base_inputs = {
            "bvps": 100.0,
            "current_roe": 0.15,
            "eps": 15.0,
            "payout": 0.30,
        }
        params = dict(BANK_DEFAULT_ASSUMPTIONS)
        v_low, _ = _compute_bank_value(base_inputs, params)

        high_inputs = dict(base_inputs, current_roe=0.25, eps=25.0)
        v_high, _ = _compute_bank_value(high_inputs, params)

        assert v_high > v_low

    def test_quality_adjustments_sum(self):
        inputs = {
            "npl_ratio": 0.20,
            "cost_of_risk": 0.03,
            "capital_adequacy_ratio": 0.13,
        }
        adjustments = _quality_adjustments(inputs, BANK_DEFAULT_ASSUMPTIONS)
        assert adjustments["npl_severe"] == 0.10
        assert adjustments["cost_of_risk_elevated"] == 0.05
        assert adjustments["capital_tight"] == 0.10
