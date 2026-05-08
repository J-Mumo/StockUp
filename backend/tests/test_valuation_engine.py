"""Tests for the valuation engine — DCF, EPV, Book Value, composite, and MOS.

Verifies math with known inputs and edge cases.
"""

import pytest
from unittest.mock import MagicMock
from datetime import date, datetime

from app.services.valuation_engine import (
    calculate_dcf,
    calculate_epv,
    calculate_book_value,
    calculate_weighted_intrinsic_value,
    calculate_margin_of_safety,
    compute_valuation,
    _calculate_cagr,
    _remove_outliers,
    DEFAULT_ASSUMPTIONS,
)
from app.models.financial_statement import FinancialStatement
from app.models.company import Company
from app.models.price_history import PriceHistory
from app.models.intrinsic_value import IntrinsicValue


# ---------------------------------------------------------------------------
# Helpers — create mock FinancialStatement objects
# ---------------------------------------------------------------------------

def _make_fs(
    fiscal_year: int,
    free_cash_flow: float | None = None,
    net_income: float | None = None,
    total_equity: float | None = None,
    shareholders_equity: float | None = None,
    book_value_per_share: float | None = None,
    return_on_equity: float | None = None,
    debt_to_equity: float | None = None,
    current_ratio: float | None = None,
    dividends_per_share: float | None = None,
    revenue: float | None = None,
) -> FinancialStatement:
    """Create a mock FinancialStatement for testing."""
    fs = MagicMock(spec=FinancialStatement)
    fs.fiscal_year = fiscal_year
    fs.free_cash_flow = free_cash_flow
    fs.net_income = net_income
    fs.total_equity = total_equity
    fs.shareholders_equity = shareholders_equity
    fs.book_value_per_share = book_value_per_share
    fs.return_on_equity = return_on_equity
    fs.debt_to_equity = debt_to_equity
    fs.current_ratio = current_ratio
    fs.dividends_per_share = dividends_per_share
    fs.revenue = revenue
    fs.operating_cash_flow = None
    fs.capital_expenditures = None
    fs.earnings_per_share = None
    fs.total_assets = None
    fs.total_liabilities = None
    return fs


# ---------------------------------------------------------------------------
# Test: _calculate_cagr utility
# ---------------------------------------------------------------------------

class TestCAGR:
    def test_positive_growth(self):
        """CAGR of [100, 110, 121, 133.1] over 3 periods ≈ 10%."""
        values = [100.0, 110.0, 121.0, 133.1]
        cagr = _calculate_cagr(values)
        assert abs(cagr - 0.10) < 0.01

    def test_negative_growth(self):
        """CAGR of [100, 90, 81] over 2 periods ≈ -10%."""
        values = [100.0, 90.0, 81.0]
        cagr = _calculate_cagr(values)
        assert abs(cagr - (-0.10)) < 0.01

    def test_single_value(self):
        """Single value returns 0."""
        assert _calculate_cagr([100.0]) == 0.0

    def test_empty_list(self):
        """Empty list returns 0."""
        assert _calculate_cagr([]) == 0.0

    def test_zero_start(self):
        """Zero start value uses fallback growth calculation."""
        values = [0.0, 50.0, 100.0]
        cagr = _calculate_cagr(values)
        # With first value 0, uses YoY from second period only: (100-50)/50 = 1.0
        assert cagr == 1.0


# ---------------------------------------------------------------------------
# Test: _remove_outliers utility
# ---------------------------------------------------------------------------

class TestRemoveOutliers:
    def test_no_outliers(self):
        """Normal distribution — all values kept."""
        values = [100.0, 102.0, 98.0, 101.0, 99.0]
        result = _remove_outliers(values, 2.0)
        assert result == values

    def test_obvious_outlier(self):
        """Extreme values removed using MAD-based detection."""
        values = [100.0, 102.0, 98.0, 101.0, 500.0]
        result = _remove_outliers(values, 2.0)
        assert 500.0 not in result
        # MAD-based detection is aggressive: median=101, MAD=1, threshold≈2.97
        # So 98 (distance=3) is borderline. The key assertion is that the
        # gross outlier (500) is removed and normal-range values dominate.
        assert len(result) >= 3
        assert all(v < 200 for v in result)

    def test_too_few_values(self):
        """With < 3 values, returns as-is."""
        values = [100.0, 200.0]
        result = _remove_outliers(values, 2.0)
        assert result == values


# ---------------------------------------------------------------------------
# Test: DCF Calculator (Step 24)
# ---------------------------------------------------------------------------

class TestDCF:
    def test_basic_dcf(self):
        """DCF with known steady FCFs should produce sensible value."""
        # Company with 1B shares, consistent 10B FCF, growing at 5%
        financials = [
            _make_fs(2021, free_cash_flow=10_000_000_000),
            _make_fs(2022, free_cash_flow=10_500_000_000),
            _make_fs(2023, free_cash_flow=11_025_000_000),
            _make_fs(2024, free_cash_flow=11_576_000_000),
            _make_fs(2025, free_cash_flow=12_155_000_000),
        ]
        shares = 1_000_000_000

        result = calculate_dcf(financials, shares)

        assert result.error is None
        assert result.intrinsic_value_per_share is not None
        assert result.intrinsic_value_per_share > 0
        # With ~5% growth, 12% discount, value should be roughly 100-200 per share
        assert 50 < result.intrinsic_value_per_share < 500
        assert result.growth_rate_used is not None
        assert abs(result.growth_rate_used - 0.05) < 0.01
        assert len(result.projected_fcfs) == 10
        assert result.terminal_value is not None
        assert result.terminal_value > 0

    def test_dcf_insufficient_data(self):
        """DCF fails gracefully with < 3 years of FCF data."""
        financials = [
            _make_fs(2024, free_cash_flow=10_000_000_000),
            _make_fs(2025, free_cash_flow=11_000_000_000),
        ]
        result = calculate_dcf(financials, 1_000_000_000)
        assert result.error is not None
        assert "Insufficient" in result.error
        assert result.intrinsic_value_per_share is None

    def test_dcf_no_shares(self):
        """DCF fails if shares_outstanding is 0 or None."""
        financials = [_make_fs(y, free_cash_flow=1e9) for y in range(2020, 2026)]
        result = calculate_dcf(financials, 0)
        assert result.error is not None

    def test_dcf_negative_fcf(self):
        """DCF handles all-negative FCFs."""
        financials = [
            _make_fs(2021, free_cash_flow=-5_000_000_000),
            _make_fs(2022, free_cash_flow=-3_000_000_000),
            _make_fs(2023, free_cash_flow=-4_000_000_000),
        ]
        result = calculate_dcf(financials, 1_000_000_000)
        assert result.error is not None
        assert "negative" in result.error.lower()

    def test_dcf_growth_rate_capped(self):
        """Growth rate should be capped at max_growth_rate_cap (20%)."""
        # Exponential growth: 1B → 10B in 4 periods = ~78% CAGR, should be capped
        financials = [
            _make_fs(2021, free_cash_flow=1_000_000_000),
            _make_fs(2022, free_cash_flow=2_000_000_000),
            _make_fs(2023, free_cash_flow=5_000_000_000),
            _make_fs(2024, free_cash_flow=10_000_000_000),
        ]
        result = calculate_dcf(financials, 1_000_000_000)
        assert result.error is None
        assert result.growth_rate_used <= 0.20

    def test_dcf_custom_assumptions(self):
        """DCF respects custom discount rate and projection years."""
        financials = [_make_fs(y, free_cash_flow=5e9) for y in range(2020, 2026)]
        custom = {"discount_rate": 0.15, "projection_years": 5}
        result = calculate_dcf(financials, 1_000_000_000, assumptions=custom)
        assert result.error is None
        assert len(result.projected_fcfs) == 5


# ---------------------------------------------------------------------------
# Test: EPV Calculator (Step 25)
# ---------------------------------------------------------------------------

class TestEPV:
    def test_basic_epv(self):
        """EPV with consistent earnings produces expected value."""
        # Net income of 5B, 1B shares, 12% cost of capital
        # EPV = 5B / 0.12 = 41.67B → 41.67 per share
        financials = [
            _make_fs(2021, net_income=5_000_000_000),
            _make_fs(2022, net_income=5_200_000_000),
            _make_fs(2023, net_income=4_800_000_000),
            _make_fs(2024, net_income=5_100_000_000),
            _make_fs(2025, net_income=4_900_000_000),
        ]
        shares = 1_000_000_000

        result = calculate_epv(financials, shares)

        assert result.error is None
        assert result.intrinsic_value_per_share is not None
        # Average ~5B, /0.12 = ~41.67B, /1B shares = ~41.67
        assert 35 < result.intrinsic_value_per_share < 50
        assert result.normalized_earnings is not None
        assert 4_500_000_000 < result.normalized_earnings < 5_500_000_000

    def test_epv_outlier_removal(self):
        """EPV removes outlier years."""
        financials = [
            _make_fs(2021, net_income=5_000_000_000),
            _make_fs(2022, net_income=5_100_000_000),
            _make_fs(2023, net_income=50_000_000_000),  # outlier (10x normal)
            _make_fs(2024, net_income=5_200_000_000),
            _make_fs(2025, net_income=4_900_000_000),
        ]
        shares = 1_000_000_000
        result = calculate_epv(financials, shares)

        assert result.error is None
        # Outlier should be removed, normalized earnings ~5B
        assert result.normalized_earnings < 10_000_000_000

    def test_epv_insufficient_data(self):
        """EPV fails with < 2 years of earnings data."""
        financials = [_make_fs(2025, net_income=5_000_000_000)]
        result = calculate_epv(financials, 1_000_000_000)
        assert result.error is not None
        assert "Insufficient" in result.error

    def test_epv_negative_earnings(self):
        """EPV returns error for consistently negative earnings."""
        financials = [
            _make_fs(2021, net_income=-1_000_000_000),
            _make_fs(2022, net_income=-2_000_000_000),
            _make_fs(2023, net_income=-500_000_000),
        ]
        result = calculate_epv(financials, 1_000_000_000)
        assert result.error is not None
        assert "negative" in result.error.lower()

    def test_epv_no_shares(self):
        """EPV fails if shares is 0."""
        financials = [_make_fs(y, net_income=5e9) for y in range(2020, 2025)]
        result = calculate_epv(financials, 0)
        assert result.error is not None


# ---------------------------------------------------------------------------
# Test: Book Value (Step 26)
# ---------------------------------------------------------------------------

class TestBookValue:
    def test_computed_from_equity(self):
        """BV computed from total_equity / shares_outstanding."""
        financials = [_make_fs(2025, total_equity=50_000_000_000)]
        shares = 1_000_000_000
        result = calculate_book_value(financials, shares)

        assert result.error is None
        assert result.book_value_per_share == 50.0
        assert result.source == "computed"
        assert result.total_equity == 50_000_000_000

    def test_fallback_to_shareholders_equity(self):
        """Uses shareholders_equity if total_equity is None."""
        financials = [_make_fs(2025, shareholders_equity=30_000_000_000)]
        shares = 1_000_000_000
        result = calculate_book_value(financials, shares)

        assert result.error is None
        assert result.book_value_per_share == 30.0
        assert result.source == "computed"

    def test_fallback_to_reported_bvps(self):
        """Uses reported book_value_per_share if equity data missing."""
        financials = [_make_fs(2025, book_value_per_share=25.0)]
        shares = 1_000_000_000
        result = calculate_book_value(financials, shares)

        assert result.error is None
        assert result.book_value_per_share == 25.0
        assert result.source == "reported"

    def test_no_data(self):
        """Returns error when no equity or BV/share data available."""
        financials = [_make_fs(2025)]
        result = calculate_book_value(financials, 1_000_000_000)
        assert result.error is not None

    def test_empty_financials(self):
        """Returns error with empty financials list."""
        result = calculate_book_value([], 1_000_000_000)
        assert result.error is not None

    def test_uses_latest_year(self):
        """Uses the most recent fiscal year data."""
        financials = [
            _make_fs(2023, total_equity=40_000_000_000),
            _make_fs(2025, total_equity=60_000_000_000),
            _make_fs(2024, total_equity=50_000_000_000),
        ]
        result = calculate_book_value(financials, 1_000_000_000)
        assert result.book_value_per_share == 60.0  # 2025 is latest


# ---------------------------------------------------------------------------
# Test: Weighted Intrinsic Value (Step 27)
# ---------------------------------------------------------------------------

class TestWeightedIV:
    def test_all_methods_available(self):
        """With DCF available, uses pure DCF (100% weight)."""
        iv, weights = calculate_weighted_intrinsic_value(100.0, 80.0, 60.0)
        # Pure DCF strategy: 100% DCF when available
        assert iv == pytest.approx(100.0)
        assert weights["dcf"] == pytest.approx(1.0)

    def test_dcf_missing(self):
        """Without DCF, falls back to EPV(70%) + BV(30%)."""
        iv, weights = calculate_weighted_intrinsic_value(None, 80.0, 60.0)
        # Fallback weights: EPV=0.7, BV=0.3
        # IV = 0.7*80 + 0.3*60 = 56 + 18 = 74
        assert iv == pytest.approx(74.0)
        assert weights["epv"] == pytest.approx(0.7)
        assert weights["bv"] == pytest.approx(0.3)

    def test_only_bv_available(self):
        """Only BV available — gets 100% weight."""
        iv, weights = calculate_weighted_intrinsic_value(None, None, 50.0)
        assert iv == pytest.approx(50.0)
        assert weights["bv"] == pytest.approx(1.0)

    def test_all_none(self):
        """All methods None → returns None."""
        iv, weights = calculate_weighted_intrinsic_value(None, None, None)
        assert iv is None
        assert weights == {}

    def test_negative_values_excluded(self):
        """Negative or zero values are treated as unavailable."""
        iv, weights = calculate_weighted_intrinsic_value(-10.0, 0.0, 50.0)
        assert iv == pytest.approx(50.0)
        assert "bv" in weights

    def test_custom_weights(self):
        """Custom fallback weights are respected (DCF still takes priority)."""
        custom = {"fallback_epv_weight": 0.6, "fallback_bv_weight": 0.4}
        # With DCF available, still uses pure DCF
        iv, weights = calculate_weighted_intrinsic_value(100.0, 80.0, 60.0, custom)
        assert iv == pytest.approx(100.0)
        assert weights["dcf"] == pytest.approx(1.0)

    def test_custom_fallback_weights_without_dcf(self):
        """Custom fallback weights apply when DCF is unavailable."""
        custom = {"fallback_epv_weight": 0.6, "fallback_bv_weight": 0.4}
        iv, weights = calculate_weighted_intrinsic_value(None, 80.0, 60.0, custom)
        # IV = 0.6*80 + 0.4*60 = 48 + 24 = 72
        assert iv == pytest.approx(72.0)
        assert weights["epv"] == pytest.approx(0.6)
        assert weights["bv"] == pytest.approx(0.4)


# ---------------------------------------------------------------------------
# Test: Margin of Safety (Step 28)
# ---------------------------------------------------------------------------

class TestMOS:
    def test_undervalued(self):
        """MOS positive when price below IV."""
        mos = calculate_margin_of_safety(100.0, 70.0)
        # 1 - 70/100 = 0.30
        assert mos == pytest.approx(0.30)

    def test_overvalued(self):
        """MOS negative when price above IV."""
        mos = calculate_margin_of_safety(100.0, 120.0)
        # 1 - 120/100 = -0.20
        assert mos == pytest.approx(-0.20)

    def test_fairly_valued(self):
        """MOS zero when price equals IV."""
        mos = calculate_margin_of_safety(100.0, 100.0)
        assert mos == pytest.approx(0.0)

    def test_none_iv(self):
        """Returns None if IV is None."""
        assert calculate_margin_of_safety(None, 50.0) is None

    def test_none_price(self):
        """Returns None if price is None."""
        assert calculate_margin_of_safety(100.0, None) is None

    def test_zero_iv(self):
        """Returns None if IV is zero (avoid division by zero)."""
        assert calculate_margin_of_safety(0.0, 50.0) is None


# ---------------------------------------------------------------------------
# Test: Full valuation pipeline (Step 29) — integration with DB
# ---------------------------------------------------------------------------

class TestComputeValuation:
    """Integration tests using the DB fixtures from conftest."""

    def test_compute_valuation_success(self, db, company, user):
        """Full valuation computation with sufficient data."""
        # Create 5 years of financial data
        for year in range(2021, 2026):
            fs = FinancialStatement(
                company_id=company.id,
                fiscal_year=year,
                period_type="annual",
                revenue=100_000_000_000 * (1.05 ** (year - 2021)),
                net_income=20_000_000_000 * (1.05 ** (year - 2021)),
                total_equity=80_000_000_000,
                free_cash_flow=15_000_000_000 * (1.05 ** (year - 2021)),
                return_on_equity=0.25,
                debt_to_equity=0.30,
                current_ratio=1.5,
                entered_by_user_id=user.id,
            )
            db.add(fs)
        db.flush()

        # Add a price record
        from app.models.price_history import PriceHistory
        price = PriceHistory(
            company_id=company.id,
            price_date=date(2026, 5, 1),
            close_price=50.0,
            volume=100000,
            source="test",
            fetched_at=datetime.utcnow(),
        )
        db.add(price)
        db.flush()

        result = compute_valuation(db, company.id)

        assert not isinstance(result, str), f"Expected ValuationResult, got: {result}"
        assert result.dcf.intrinsic_value_per_share is not None
        assert result.epv.intrinsic_value_per_share is not None
        assert result.book_value.book_value_per_share is not None
        assert result.weighted_intrinsic_value is not None
        assert result.current_market_price == 50.0
        assert result.margin_of_safety_pct is not None

        # Verify persisted to DB
        iv_record = (
            db.query(IntrinsicValue)
            .filter(IntrinsicValue.company_id == company.id)
            .first()
        )
        assert iv_record is not None
        assert iv_record.dcf_value is not None
        assert iv_record.assumptions is not None

    def test_compute_valuation_company_not_found(self, db):
        """Returns error string for non-existent company."""
        result = compute_valuation(db, 99999)
        assert result == "company_not_found"

    def test_compute_valuation_no_financials(self, db, company):
        """Returns error string when no financial data exists."""
        result = compute_valuation(db, company.id)
        assert result == "no_financial_data"

    def test_compute_valuation_no_shares(self, db, market):
        """Returns error string when shares_outstanding is missing."""
        from app.models.company import Company
        c = Company(
            market_id=market.id,
            name="No Shares Co",
            ticker_symbol="NOSH",
            is_active=True,
            shares_outstanding=None,
        )
        db.add(c)
        db.flush()

        # Add a financial record
        fs = FinancialStatement(
            company_id=c.id,
            fiscal_year=2025,
            net_income=1_000_000,
        )
        db.add(fs)
        db.flush()

        result = compute_valuation(db, c.id)
        assert result == "no_shares_outstanding"
