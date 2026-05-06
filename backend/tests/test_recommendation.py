"""Tests for the recommendation engine — decision matrix and quality factors.

Verifies the recommendation logic produces correct buy/sell/hold signals
based on margin of safety and quality factors.
"""

import pytest
from unittest.mock import MagicMock

from app.services.recommendation_engine import (
    generate_recommendation,
    assess_quality,
    _assess_roe,
    _assess_debt_to_equity,
    _assess_earnings_growth,
    _assess_fcf,
    _assess_dividends,
    _assess_current_ratio,
)
from app.models.financial_statement import FinancialStatement


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_fs(
    fiscal_year: int,
    return_on_equity: float | None = None,
    debt_to_equity: float | None = None,
    net_income: float | None = None,
    free_cash_flow: float | None = None,
    dividends_per_share: float | None = None,
    current_ratio: float | None = None,
    revenue: float | None = None,
) -> FinancialStatement:
    """Create a mock FinancialStatement for testing."""
    fs = MagicMock(spec=FinancialStatement)
    fs.fiscal_year = fiscal_year
    fs.return_on_equity = return_on_equity
    fs.debt_to_equity = debt_to_equity
    fs.net_income = net_income
    fs.free_cash_flow = free_cash_flow
    fs.dividends_per_share = dividends_per_share
    fs.current_ratio = current_ratio
    fs.revenue = revenue
    fs.total_equity = None
    fs.shareholders_equity = None
    fs.book_value_per_share = None
    fs.operating_cash_flow = None
    fs.capital_expenditures = None
    fs.earnings_per_share = None
    fs.total_assets = None
    fs.total_liabilities = None
    return fs


def _make_quality_financials(
    roe: float = 0.20,
    de: float = 0.30,
    base_income: float = 5e9,
    growth: float = 0.05,
    fcf_base: float = 3e9,
    dps: float = 2.0,
    cr: float = 1.5,
    years: int = 5,
) -> list[FinancialStatement]:
    """Create financials that represent a quality company."""
    return [
        _make_fs(
            fiscal_year=2021 + i,
            return_on_equity=roe,
            debt_to_equity=de,
            net_income=base_income * ((1 + growth) ** i),
            free_cash_flow=fcf_base * ((1 + growth) ** i),
            dividends_per_share=dps,
            current_ratio=cr,
        )
        for i in range(years)
    ]


# ---------------------------------------------------------------------------
# Test: Quality Factor Assessment
# ---------------------------------------------------------------------------

class TestQualityAssessment:
    def test_high_quality_company(self):
        """Company meeting all quality criteria scores 6/6."""
        financials = _make_quality_financials()
        quality = assess_quality(financials)

        assert quality.score == 6
        assert quality.has_high_roe is True
        assert quality.has_low_leverage is True
        assert quality.has_earnings_growth is True
        assert quality.has_positive_fcf is True
        assert quality.has_dividend_consistency is True
        assert quality.has_adequate_liquidity is True

    def test_low_quality_company(self):
        """Company failing all criteria scores 0/6."""
        financials = [
            _make_fs(
                fiscal_year=2021 + i,
                return_on_equity=0.05,   # below 15%
                debt_to_equity=1.5,      # above 0.5
                net_income=5e9 * (0.9 ** i),  # declining
                free_cash_flow=-1e9,     # negative
                dividends_per_share=0.0, # no dividends
                current_ratio=0.6,       # below 1.0
            )
            for i in range(5)
        ]
        quality = assess_quality(financials)

        assert quality.score == 0
        assert quality.has_high_roe is False
        assert quality.has_low_leverage is False
        assert quality.has_earnings_growth is False
        assert quality.has_positive_fcf is False
        assert quality.has_dividend_consistency is False
        assert quality.has_adequate_liquidity is False

    def test_empty_financials(self):
        """Empty financials → all factors fail gracefully."""
        quality = assess_quality([])
        assert quality.score == 0
        assert len(quality.factors) == 6  # All 6 factors still assessed


class TestROEFactor:
    def test_high_roe(self):
        """ROE consistently > 15% passes."""
        financials = [_make_fs(y, return_on_equity=0.20) for y in range(2021, 2026)]
        result = _assess_roe(financials)
        assert result.passed is True

    def test_low_roe(self):
        """ROE consistently < 15% fails."""
        financials = [_make_fs(y, return_on_equity=0.08) for y in range(2021, 2026)]
        result = _assess_roe(financials)
        assert result.passed is False

    def test_inconsistent_roe(self):
        """ROE alternating above/below 15% — depends on average."""
        financials = [
            _make_fs(2021, return_on_equity=0.20),
            _make_fs(2022, return_on_equity=0.05),
            _make_fs(2023, return_on_equity=0.25),
            _make_fs(2024, return_on_equity=0.03),
        ]
        result = _assess_roe(financials)
        # Average = 0.1325, and only 50% above threshold → marginal pass/fail
        # avg > 0.15 is False, so should fail
        assert result.passed is False


class TestDebtToEquityFactor:
    def test_low_leverage(self):
        """D/E < 0.5 passes."""
        financials = [_make_fs(2025, debt_to_equity=0.30)]
        result = _assess_debt_to_equity(financials)
        assert result.passed is True

    def test_high_leverage(self):
        """D/E > 0.5 fails."""
        financials = [_make_fs(2025, debt_to_equity=0.80)]
        result = _assess_debt_to_equity(financials)
        assert result.passed is False

    def test_no_data(self):
        """No D/E data fails."""
        financials = [_make_fs(2025)]
        result = _assess_debt_to_equity(financials)
        assert result.passed is False


class TestEarningsGrowthFactor:
    def test_positive_growth(self):
        """Consistent positive earnings growth passes."""
        financials = [
            _make_fs(y, net_income=5e9 * (1.1 ** (y - 2021)))
            for y in range(2021, 2026)
        ]
        result = _assess_earnings_growth(financials)
        assert result.passed is True

    def test_declining_earnings(self):
        """Declining earnings fails."""
        financials = [
            _make_fs(y, net_income=5e9 * (0.85 ** (y - 2021)))
            for y in range(2021, 2026)
        ]
        result = _assess_earnings_growth(financials)
        assert result.passed is False

    def test_single_year(self):
        """Single year of data — insufficient for trend."""
        financials = [_make_fs(2025, net_income=5e9)]
        result = _assess_earnings_growth(financials)
        assert result.passed is False


class TestFCFFactor:
    def test_positive_fcf(self):
        """Positive FCF in majority of years passes."""
        financials = [
            _make_fs(y, free_cash_flow=2e9)
            for y in range(2021, 2026)
        ]
        result = _assess_fcf(financials)
        assert result.passed is True

    def test_negative_fcf(self):
        """Negative FCF in majority of years fails."""
        financials = [
            _make_fs(y, free_cash_flow=-1e9)
            for y in range(2021, 2026)
        ]
        result = _assess_fcf(financials)
        assert result.passed is False


class TestDividendFactor:
    def test_consistent_dividends(self):
        """Paying dividends in 60%+ years passes."""
        financials = [_make_fs(y, dividends_per_share=2.0) for y in range(2021, 2026)]
        result = _assess_dividends(financials)
        assert result.passed is True

    def test_no_dividends(self):
        """Zero dividends fails."""
        financials = [_make_fs(y, dividends_per_share=0.0) for y in range(2021, 2026)]
        result = _assess_dividends(financials)
        assert result.passed is False


class TestCurrentRatioFactor:
    def test_adequate_liquidity(self):
        """Current ratio > 1.0 passes."""
        financials = [_make_fs(2025, current_ratio=1.8)]
        result = _assess_current_ratio(financials)
        assert result.passed is True

    def test_low_liquidity(self):
        """Current ratio < 1.0 fails."""
        financials = [_make_fs(2025, current_ratio=0.7)]
        result = _assess_current_ratio(financials)
        assert result.passed is False


# ---------------------------------------------------------------------------
# Test: Recommendation Decision Matrix
# ---------------------------------------------------------------------------

class TestRecommendationMatrix:
    """Test the full decision matrix from Step 30."""

    def test_strong_buy(self):
        """MOS > 30% + ROE > 15% + D/E < 0.5 → Strong Buy."""
        financials = _make_quality_financials(roe=0.25, de=0.30)
        rec = generate_recommendation(0.35, financials)
        assert rec.action == "Strong Buy"
        assert "Deep value" in rec.reason

    def test_buy_with_quality(self):
        """MOS > 30% + ROE > 15% but D/E > 0.5 → Buy."""
        financials = _make_quality_financials(roe=0.20, de=0.70)
        rec = generate_recommendation(0.35, financials)
        assert rec.action == "Buy"
        assert "strong earnings quality" in rec.reason

    def test_buy_no_quality(self):
        """MOS > 30% but low ROE → still Buy (on value alone)."""
        financials = _make_quality_financials(roe=0.08, de=0.70)
        rec = generate_recommendation(0.40, financials)
        assert rec.action == "Buy"
        assert "quality score" in rec.reason

    def test_accumulate(self):
        """MOS 10-30% + ROE > 15% → Accumulate."""
        financials = _make_quality_financials(roe=0.20, de=0.30)
        rec = generate_recommendation(0.20, financials)
        assert rec.action == "Accumulate"

    def test_hold_moderate_mos_low_quality(self):
        """MOS 10-30% but low ROE → Hold."""
        financials = _make_quality_financials(roe=0.08)
        rec = generate_recommendation(0.15, financials)
        assert rec.action == "Hold"

    def test_hold_small_mos(self):
        """MOS 0-10% → Hold."""
        financials = _make_quality_financials()
        rec = generate_recommendation(0.05, financials)
        assert rec.action == "Hold"
        assert "Fairly valued" in rec.reason

    def test_hold_trim(self):
        """MOS -10% to 0% → Hold/Trim."""
        financials = _make_quality_financials()
        rec = generate_recommendation(-0.05, financials)
        assert rec.action == "Hold/Trim"
        assert "Slightly overvalued" in rec.reason

    def test_sell(self):
        """MOS -10% to -20% → Sell."""
        financials = _make_quality_financials()
        rec = generate_recommendation(-0.15, financials)
        assert rec.action == "Sell"
        assert "Overvalued" in rec.reason

    def test_strong_sell(self):
        """MOS < -20% → Strong Sell."""
        financials = _make_quality_financials()
        rec = generate_recommendation(-0.25, financials)
        assert rec.action == "Strong Sell"
        assert "Significantly overvalued" in rec.reason

    def test_none_mos(self):
        """MOS is None → Hold with insufficient data message."""
        financials = _make_quality_financials()
        rec = generate_recommendation(None, financials)
        assert rec.action == "Hold"
        assert "Insufficient data" in rec.reason

    def test_boundary_30_pct(self):
        """At exactly 30% MOS without ROE → should be in Accumulate/Hold band."""
        # MOS > 0.30 is strictly greater than, so 0.30 exact falls into the 10-30 band
        financials = _make_quality_financials(roe=0.20)
        rec = generate_recommendation(0.30, financials)
        # 0.30 is not > 0.30, so it goes to 10-30% band with ROE → Accumulate
        assert rec.action == "Accumulate"

    def test_boundary_negative_10_pct(self):
        """At exactly -10% → Hold/Trim (>= -0.10)."""
        financials = _make_quality_financials()
        rec = generate_recommendation(-0.10, financials)
        assert rec.action == "Hold/Trim"

    def test_boundary_negative_20_pct(self):
        """At exactly -20% → Sell (>= -0.20)."""
        financials = _make_quality_financials()
        rec = generate_recommendation(-0.20, financials)
        assert rec.action == "Sell"


# ---------------------------------------------------------------------------
# Test: Recommendation output structure
# ---------------------------------------------------------------------------

class TestRecommendationOutput:
    def test_recommendation_has_quality(self):
        """Recommendation includes quality assessment."""
        financials = _make_quality_financials()
        rec = generate_recommendation(0.35, financials)

        assert rec.quality is not None
        assert rec.quality.score >= 0
        assert rec.quality.max_score == 6
        assert len(rec.quality.factors) == 6

    def test_to_dict_serialization(self):
        """Recommendation serializes to dict correctly."""
        financials = _make_quality_financials()
        rec = generate_recommendation(0.20, financials)
        d = rec.to_dict()

        assert "action" in d
        assert "reason" in d
        assert "quality" in d
        assert "factors" in d["quality"]
        assert isinstance(d["quality"]["factors"], list)
