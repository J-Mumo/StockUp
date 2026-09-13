"""Tests for the 4-dimensional recommendation scorer."""

from __future__ import annotations

from datetime import date, timedelta
from unittest.mock import MagicMock

import pytest

from app.models.financial_statement import FinancialStatement
from app.models.price_history import PriceHistory
from app.services.recommendation_dimensions import (
    PortfolioContext,
    compose,
    compute_dimensions,
    score_position,
    score_quality,
    score_trend,
    score_valuation,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _price(day_offset: int, close: float, today: date) -> PriceHistory:
    p = MagicMock(spec=PriceHistory)
    p.price_date = today - timedelta(days=day_offset)
    p.close_price = close
    return p


def _fs(fiscal_year: int, net_income: float | None = None, revenue: float | None = None) -> FinancialStatement:
    fs = MagicMock(spec=FinancialStatement)
    fs.fiscal_year = fiscal_year
    fs.net_income = net_income
    fs.revenue = revenue
    return fs


# ---------------------------------------------------------------------------
# Valuation
# ---------------------------------------------------------------------------

class TestScoreValuation:
    def test_none_mos_inapplicable(self):
        r = score_valuation(None)
        assert r.applicable is False
        assert r.score is None

    def test_floor_mos_scores_zero(self):
        assert score_valuation(-0.20).score == 0
        assert score_valuation(-0.50).score == 0  # clipped

    def test_zero_mos_scores_third(self):
        r = score_valuation(0.0)
        assert r.score == 33
        assert r.applicable is True

    def test_twenty_pct_mos_scores_two_thirds(self):
        assert score_valuation(0.20).score == 67

    def test_cap_mos_scores_hundred(self):
        assert score_valuation(0.40).score == 100
        assert score_valuation(1.00).score == 100  # clipped


# ---------------------------------------------------------------------------
# Quality
# ---------------------------------------------------------------------------

class TestScoreQuality:
    def test_all_pass(self):
        assert score_quality(10, 10).score == 100

    def test_half(self):
        assert score_quality(5, 10).score == 50

    def test_zero_max_inapplicable(self):
        r = score_quality(0, 0)
        assert r.applicable is False
        assert r.score is None


# ---------------------------------------------------------------------------
# Trend
# ---------------------------------------------------------------------------

class TestScoreTrend:
    def test_all_up_scores_hundred(self):
        today = date(2026, 9, 13)
        # 250 rising daily closes so SMA-50 > SMA-200 and 6M/12M returns > 0.
        prices = [
            _price(day_offset=250 - i, close=100 + i, today=today)
            for i in range(250)
        ]
        # Fundamentals rising for last 4 years.
        fins = [
            _fs(2022, net_income=100), _fs(2023, net_income=120),
            _fs(2024, net_income=140), _fs(2025, net_income=160),
        ]
        r = score_trend(prices, fins, today=today)
        assert r.applicable is True
        assert r.score == 100

    def test_all_down_scores_zero(self):
        today = date(2026, 9, 13)
        prices = [
            _price(day_offset=250 - i, close=200 - i * 0.5, today=today)
            for i in range(250)
        ]
        fins = [
            _fs(2022, net_income=200), _fs(2023, net_income=180),
            _fs(2024, net_income=160), _fs(2025, net_income=140),
        ]
        r = score_trend(prices, fins, today=today)
        assert r.applicable is True
        assert r.score == 0

    def test_no_price_no_fundamentals_inapplicable(self):
        r = score_trend([], [], today=date(2026, 9, 13))
        assert r.applicable is False
        assert r.score is None

    def test_only_fundamentals_still_applicable(self):
        fins = [
            _fs(2022, net_income=100), _fs(2023, net_income=120),
            _fs(2024, net_income=140), _fs(2025, net_income=160),
        ]
        r = score_trend([], fins, today=date(2026, 9, 13))
        assert r.applicable is True
        assert r.score == 100


# ---------------------------------------------------------------------------
# Position
# ---------------------------------------------------------------------------

class TestScorePosition:
    def test_no_position_inapplicable(self):
        r = score_position(None)
        assert r.applicable is False
        assert r.score is None
        r2 = score_position(PortfolioContext(net_qty=0))
        assert r2.applicable is False

    def test_healthy_position(self):
        # Small weight, up 25%
        ctx = PortfolioContext(
            net_qty=100, avg_cost=100.0, current_price=125.0,
            portfolio_value=1_000_000, sector_value=50_000,
        )
        r = score_position(ctx, sector="Banking")
        # 50 base + 20 (P/L ≥ 20%) - 0 (weight = 1.25%) - 0 (sector 5%) = 70
        assert r.score == 70

    def test_overexposed_and_losing(self):
        # 20% weight, down 30%
        ctx = PortfolioContext(
            net_qty=1000, avg_cost=100.0, current_price=70.0,
            portfolio_value=350_000, sector_value=200_000,
        )
        r = score_position(ctx, sector="Banking")
        # 50 - 20 (loss ≥ -20%) - 15 (weight > 15%) - 10 (sector > 30%) = 5
        assert r.score == 5

    def test_small_gain(self):
        ctx = PortfolioContext(
            net_qty=100, avg_cost=100.0, current_price=110.0,
            portfolio_value=1_000_000, sector_value=None,
        )
        r = score_position(ctx)
        # 50 + 10 = 60
        assert r.score == 60


# ---------------------------------------------------------------------------
# Composite
# ---------------------------------------------------------------------------

class TestCompose:
    def _dim(self, score, applicable=True):
        from app.services.recommendation_dimensions import DimensionScore
        return DimensionScore(name="x", score=score, applicable=applicable)

    def test_all_applicable(self):
        # 100 * 0.4 + 80 * 0.3 + 50 * 0.2 + 50 * 0.1 = 40 + 24 + 10 + 5 = 79
        score, verdict = compose(
            self._dim(100), self._dim(80), self._dim(50), self._dim(50),
        )
        assert score == 79
        assert verdict == "Strong Buy"

    def test_position_inapplicable_renormalizes(self):
        # Weights become 40/30/20 → 44.4/33.3/22.2. 100*0.444 + 80*0.333 + 50*0.222 = 82.2 → 82
        score, verdict = compose(
            self._dim(100), self._dim(80), self._dim(50), self._dim(None, applicable=False),
        )
        assert score == 82
        assert verdict == "Strong Buy"

    def test_no_applicable_dimensions(self):
        score, verdict = compose(
            self._dim(None, applicable=False),
            self._dim(None, applicable=False),
            self._dim(None, applicable=False),
            self._dim(None, applicable=False),
        )
        assert score is None
        assert verdict is None

    def test_avoid_when_no_position(self):
        # All applicable dims low, position inapplicable.
        score, verdict = compose(
            self._dim(5), self._dim(5), self._dim(5),
            self._dim(None, applicable=False),
        )
        assert verdict == "Avoid"

    def test_sell_when_position_held(self):
        score, verdict = compose(
            self._dim(5), self._dim(5), self._dim(5), self._dim(5),
        )
        assert verdict == "Sell"


# ---------------------------------------------------------------------------
# Top-level integration
# ---------------------------------------------------------------------------

class TestComputeDimensions:
    def test_end_to_end_no_portfolio(self):
        today = date(2026, 9, 13)
        prices = [
            _price(day_offset=250 - i, close=100 + i, today=today)
            for i in range(250)
        ]
        fins = [
            _fs(2022, net_income=100), _fs(2023, net_income=120),
            _fs(2024, net_income=140), _fs(2025, net_income=160),
        ]
        dims = compute_dimensions(
            mos=0.30,
            quality_score=8, quality_max_score=10,
            quality_subscores=[],
            prices=prices, financials=fins,
            position=None,
            today=today,
        )
        assert dims.valuation.score == 83
        assert dims.quality.score == 80
        assert dims.trend.score == 100
        assert dims.position.applicable is False
        # Composite over 3 dims, weights 40/30/20 → normalize by 0.9.
        # (83*0.4 + 80*0.3 + 100*0.2) / 0.9 = (33.2 + 24 + 20) / 0.9 = 85.78 → 86
        assert dims.composite_score == 86
        assert dims.composite_verdict == "Strong Buy"
