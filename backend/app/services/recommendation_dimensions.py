"""Four-dimensional recommendation scoring.

Computes independent 0-100 scores for Valuation, Quality, Trend and Position,
plus a composite verdict. See ``plans/recommendation-4d.md`` for the design.

The existing ``Recommendation.action`` (MOS + quality-gate) is unchanged;
dimensions are additive so the UI can show a scorecard alongside the label.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from app.models.financial_statement import FinancialStatement
from app.models.price_history import PriceHistory


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class DimensionDriver:
    """A single driver line for a dimension (value + verdict flag)."""
    name: str
    value: Any = None
    passed: bool | None = None
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "value": self.value,
            "passed": self.passed,
            "detail": self.detail,
        }


@dataclass
class DimensionScore:
    """A single dimension result."""
    name: str
    score: int | None                # 0-100, or None if inapplicable
    applicable: bool
    drivers: list[DimensionDriver] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "score": self.score,
            "applicable": self.applicable,
            "drivers": [d.to_dict() for d in self.drivers],
        }


@dataclass
class PortfolioContext:
    """Per-user snapshot needed to score the Position dimension.

    - ``net_qty`` and ``avg_cost`` are aggregated from portfolio_transactions
      (buys positive, sells negative).
    - ``current_price`` is the most recent close.
    - ``portfolio_value`` is total mark-to-market across all holdings.
    - ``sector_value`` is total mark-to-market across all holdings in the
      same sector as *this* company.
    """
    net_qty: float = 0.0
    avg_cost: float | None = None
    current_price: float | None = None
    portfolio_value: float | None = None
    sector_value: float | None = None


@dataclass
class Dimensions:
    """The four dimensions + composite."""
    valuation: DimensionScore
    quality: DimensionScore
    trend: DimensionScore
    position: DimensionScore
    composite_score: int | None
    composite_verdict: str | None
    # Two-stage summary (Buffett-style separation):
    #   business_score   — "How good is the company?" (Quality + Trend)
    #   valuation_score  — "How attractive is the stock at today's price?"
    # Kept as a top-level mirror of the Valuation dimension so the UI can
    # render a symmetric Business/Valuation header without re-computing.
    business_score: int | None = None
    valuation_score: int | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "valuation": self.valuation.to_dict(),
            "quality": self.quality.to_dict(),
            "trend": self.trend.to_dict(),
            "position": self.position.to_dict(),
            "composite_score": self.composite_score,
            "composite_verdict": self.composite_verdict,
            "business_score": self.business_score,
            "valuation_score": self.valuation_score,
        }


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Composite default weights.
_DEFAULT_WEIGHTS = {
    "valuation": 0.40,
    "quality":   0.30,
    "trend":     0.20,
    "position":  0.10,
}

# Two-stage summary weights: the "Business" aggregate mixes company-intrinsic
# signals only. Position is user-specific and Valuation is price-specific,
# so both are excluded here. Quality is weighted heavier than Trend because
# it reflects durable business economics rather than recent momentum.
_BUSINESS_WEIGHTS = {
    "quality": 0.60,
    "trend":   0.40,
}

# Valuation curve: MOS below _VAL_FLOOR → 0, above _VAL_CAP → 100.
_VAL_FLOOR = -0.20
_VAL_CAP = 0.40

# Trend windows (calendar days).
_TREND_6M_DAYS = 183
_TREND_12M_DAYS = 365


# ---------------------------------------------------------------------------
# Individual scorers
# ---------------------------------------------------------------------------

def score_valuation(mos: float | None, extras: dict[str, Any] | None = None) -> DimensionScore:
    """Score the Valuation dimension from margin of safety."""
    if mos is None:
        return DimensionScore(
            name="Valuation",
            score=None,
            applicable=False,
            drivers=[DimensionDriver(
                name="Margin of safety",
                detail="No valuation computed yet",
            )],
        )

    ratio = (mos - _VAL_FLOOR) / (_VAL_CAP - _VAL_FLOOR)
    ratio = max(0.0, min(1.0, ratio))
    score = int(round(ratio * 100))

    drivers = [
        DimensionDriver(
            name="Margin of safety",
            value=round(mos, 4),
            passed=mos > 0,
            detail=f"{mos * 100:.1f}% (0 pts at ≤ -20%, 100 pts at ≥ +40%)",
        ),
    ]
    if extras:
        iv = extras.get("weighted_intrinsic_value")
        price = extras.get("current_market_price")
        if iv is not None and price is not None:
            drivers.append(DimensionDriver(
                name="IV vs price",
                value=None,
                detail=f"IV {iv:.2f} vs price {price:.2f}",
            ))
    return DimensionScore(
        name="Valuation", score=score, applicable=True, drivers=drivers
    )


def score_quality(quality_score: int, max_score: int, subscores: list[dict[str, Any]] | None = None) -> DimensionScore:
    """Score the Quality dimension from the existing QualityAssessment."""
    if max_score <= 0:
        return DimensionScore(
            name="Quality", score=None, applicable=False, drivers=[]
        )

    score = int(round(quality_score / max_score * 100))
    drivers: list[DimensionDriver] = []
    for s in subscores or []:
        drivers.append(DimensionDriver(
            name=s.get("name", ""),
            value=(
                f"{s.get('score')}/{s.get('max_score')}"
                if s.get("applicable") else "n/a"
            ),
            passed=bool(s.get("passed")) if s.get("applicable") else None,
            detail=s.get("detail", ""),
        ))
    return DimensionScore(
        name="Quality", score=score, applicable=True, drivers=drivers
    )


def score_trend(
    prices: list[PriceHistory],
    financials: list[FinancialStatement],
    today: date | None = None,
) -> DimensionScore:
    """Score the Trend dimension from price momentum + fundamental momentum."""
    today = today or date.today()
    drivers: list[DimensionDriver] = []
    signals: list[bool] = []

    sorted_prices = sorted(prices, key=lambda p: p.price_date)

    # Price signals require at least ~12 months of data.
    if sorted_prices:
        latest_price = float(sorted_prices[-1].close_price)

        # 6-month return
        target_6m = today - timedelta(days=_TREND_6M_DAYS)
        p6 = _price_at_or_before(sorted_prices, target_6m)
        if p6 is not None:
            ret_6m = (latest_price - p6) / p6
            passed = ret_6m > 0
            signals.append(passed)
            drivers.append(DimensionDriver(
                name="6-month return",
                value=round(ret_6m, 4),
                passed=passed,
                detail=f"{ret_6m * 100:+.1f}%",
            ))

        # 12-month return
        target_12m = today - timedelta(days=_TREND_12M_DAYS)
        p12 = _price_at_or_before(sorted_prices, target_12m)
        if p12 is not None:
            ret_12m = (latest_price - p12) / p12
            passed = ret_12m > 0
            signals.append(passed)
            drivers.append(DimensionDriver(
                name="12-month return",
                value=round(ret_12m, 4),
                passed=passed,
                detail=f"{ret_12m * 100:+.1f}%",
            ))

        # 50-day vs 200-day SMA
        sma_50 = _sma(sorted_prices, 50)
        sma_200 = _sma(sorted_prices, 200)
        if sma_50 is not None and sma_200 is not None:
            passed = sma_50 >= sma_200
            signals.append(passed)
            drivers.append(DimensionDriver(
                name="50d SMA vs 200d SMA",
                value=round(sma_50 / sma_200, 4) if sma_200 else None,
                passed=passed,
                detail=(
                    f"50d {sma_50:.2f} {'≥' if passed else '<'} "
                    f"200d {sma_200:.2f}"
                ),
            ))

    # Fundamental momentum: NI direction (fall back to revenue).
    fund_signal, fund_driver = _fundamental_momentum(financials)
    if fund_driver is not None:
        signals.append(fund_signal)
        drivers.append(fund_driver)

    if not signals:
        return DimensionScore(
            name="Trend",
            score=None,
            applicable=False,
            drivers=drivers or [DimensionDriver(
                name="No trend data",
                detail="Need price history or ≥ 4 fiscal years",
            )],
        )

    score = int(round(sum(1 for s in signals if s) / len(signals) * 100))
    return DimensionScore(
        name="Trend", score=score, applicable=True, drivers=drivers
    )


def score_position(ctx: PortfolioContext | None, sector: str | None = None) -> DimensionScore:
    """Score the Position dimension from the user's current holding."""
    if ctx is None or ctx.net_qty <= 0:
        return DimensionScore(
            name="Position",
            score=None,
            applicable=False,
            drivers=[DimensionDriver(
                name="No position",
                detail="You do not currently hold this security",
            )],
        )

    score = 50
    drivers: list[DimensionDriver] = []

    # Unrealized P/L
    upl_pct: float | None = None
    if ctx.avg_cost and ctx.current_price and ctx.avg_cost > 0:
        upl_pct = (ctx.current_price - ctx.avg_cost) / ctx.avg_cost
        if upl_pct >= 0.20:
            adj = 20
        elif upl_pct >= 0:
            adj = 10
        elif upl_pct >= -0.20:
            adj = -10
        else:
            adj = -20
        score += adj
        drivers.append(DimensionDriver(
            name="Unrealized P/L",
            value=round(upl_pct, 4),
            passed=upl_pct >= 0,
            detail=(
                f"{upl_pct * 100:+.1f}% (cost {ctx.avg_cost:.2f} → "
                f"price {ctx.current_price:.2f}) → {adj:+d} pts"
            ),
        ))

    # Portfolio weight
    position_value: float | None = None
    weight: float | None = None
    if ctx.current_price is not None and ctx.portfolio_value and ctx.portfolio_value > 0:
        position_value = ctx.net_qty * ctx.current_price
        weight = position_value / ctx.portfolio_value
        adj = 0
        if weight > 0.15:
            adj = -15
        score += adj
        drivers.append(DimensionDriver(
            name="Portfolio weight",
            value=round(weight, 4),
            passed=weight <= 0.15,
            detail=(
                f"{weight * 100:.1f}% of portfolio"
                + (f" → {adj:+d} pts (overexposed)" if adj else "")
            ),
        ))

    # Sector concentration
    if (
        ctx.sector_value is not None
        and ctx.portfolio_value
        and ctx.portfolio_value > 0
    ):
        sector_weight = ctx.sector_value / ctx.portfolio_value
        adj = 0
        if sector_weight > 0.30:
            adj = -10
        score += adj
        drivers.append(DimensionDriver(
            name="Sector concentration",
            value=round(sector_weight, 4),
            passed=sector_weight <= 0.30,
            detail=(
                f"{sector_weight * 100:.1f}% in {sector or 'sector'}"
                + (f" → {adj:+d} pts" if adj else "")
            ),
        ))

    drivers.insert(0, DimensionDriver(
        name="Current holding",
        value=ctx.net_qty,
        detail=(
            f"{ctx.net_qty:g} shares"
            + (f" @ avg cost {ctx.avg_cost:.2f}" if ctx.avg_cost else "")
        ),
    ))

    score = max(0, min(100, score))
    return DimensionScore(
        name="Position", score=score, applicable=True, drivers=drivers
    )


# ---------------------------------------------------------------------------
# Composite
# ---------------------------------------------------------------------------

def compose(
    valuation: DimensionScore,
    quality: DimensionScore,
    trend: DimensionScore,
    position: DimensionScore,
    weights: dict[str, float] | None = None,
) -> tuple[int | None, str | None]:
    """Weighted mean of applicable dimensions → (score, verdict)."""
    weights = weights or _DEFAULT_WEIGHTS
    pairs = [
        ("valuation", valuation),
        ("quality",   quality),
        ("trend",     trend),
        ("position",  position),
    ]
    applicable = [(name, dim) for name, dim in pairs if dim.applicable and dim.score is not None]
    if not applicable:
        return None, None

    total_weight = sum(weights[name] for name, _ in applicable)
    if total_weight <= 0:
        return None, None

    composite = sum(dim.score * weights[name] for name, dim in applicable) / total_weight
    composite = int(round(composite))

    verdict = _composite_verdict(composite, position_applicable=position.applicable)
    return composite, verdict


def _composite_verdict(score: int, position_applicable: bool) -> str:
    if score >= 75:
        return "Strong Buy"
    if score >= 60:
        return "Buy"
    if score >= 45:
        return "Accumulate"
    if score >= 30:
        return "Hold"
    if score >= 15:
        return "Trim" if position_applicable else "Avoid"
    return "Sell" if position_applicable else "Avoid"


def _business_score(
    quality: DimensionScore,
    trend: DimensionScore,
    weights: dict[str, float] | None = None,
) -> int | None:
    """Aggregate the company-intrinsic dimensions into a single 0-100 score.

    Returns ``None`` if neither Quality nor Trend is applicable — this
    signals to the UI that we can't say anything about business quality.
    """
    weights = weights or _BUSINESS_WEIGHTS
    parts: list[tuple[float, int]] = []
    if quality.applicable and quality.score is not None:
        parts.append((weights["quality"], quality.score))
    if trend.applicable and trend.score is not None:
        parts.append((weights["trend"], trend.score))
    if not parts:
        return None
    total_weight = sum(w for w, _ in parts)
    if total_weight <= 0:
        return None
    weighted = sum(w * s for w, s in parts) / total_weight
    return int(round(weighted))


# ---------------------------------------------------------------------------
# Top-level entry point
# ---------------------------------------------------------------------------

def compute_dimensions(
    *,
    mos: float | None,
    quality_score: int,
    quality_max_score: int,
    quality_subscores: list[dict[str, Any]] | None,
    prices: list[PriceHistory] | None,
    financials: list[FinancialStatement],
    position: PortfolioContext | None,
    sector: str | None = None,
    valuation_extras: dict[str, Any] | None = None,
    today: date | None = None,
) -> Dimensions:
    """Compute all four dimensions + composite."""
    val = score_valuation(mos, extras=valuation_extras)
    qual = score_quality(quality_score, quality_max_score, subscores=quality_subscores)
    trnd = score_trend(prices or [], financials, today=today)
    pos = score_position(position, sector=sector)
    composite, verdict = compose(val, qual, trnd, pos)
    return Dimensions(
        valuation=val,
        quality=qual,
        trend=trnd,
        position=pos,
        composite_score=composite,
        composite_verdict=verdict,
        business_score=_business_score(qual, trnd),
        valuation_score=val.score if val.applicable else None,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _price_at_or_before(
    sorted_prices: list[PriceHistory], target: date
) -> float | None:
    """Return the close price on or before ``target``. None if all prices
    are after target."""
    picked: float | None = None
    for p in sorted_prices:
        if p.price_date <= target:
            picked = float(p.close_price)
        else:
            break
    return picked


def _sma(sorted_prices: list[PriceHistory], window: int) -> float | None:
    """Simple moving average of the last ``window`` closes."""
    if len(sorted_prices) < window:
        return None
    tail = sorted_prices[-window:]
    return statistics.mean(float(p.close_price) for p in tail)


def _fundamental_momentum(
    financials: list[FinancialStatement],
) -> tuple[bool, DimensionDriver | None]:
    """Direction of last 3 NI YoY pairs (fallback to revenue)."""
    sorted_fs = sorted(financials, key=lambda f: f.fiscal_year)

    def _series(attr: str) -> list[tuple[int, float]]:
        out: list[tuple[int, float]] = []
        for fs in sorted_fs:
            v = getattr(fs, attr, None)
            if v is not None:
                try:
                    out.append((fs.fiscal_year, float(v)))
                except (TypeError, ValueError):
                    pass
        return out

    for attr, label in (("net_income", "Net income"), ("revenue", "Revenue")):
        series = _series(attr)
        if len(series) < 4:
            continue
        recent = series[-4:]
        pairs = [(recent[i][1] > recent[i - 1][1]) for i in range(1, len(recent))]
        up = sum(1 for p in pairs if p)
        passed = up >= 2
        return passed, DimensionDriver(
            name=f"{label} YoY momentum",
            value=up,
            passed=passed,
            detail=f"{up}/{len(pairs)} recent years up",
        )
    return False, None
