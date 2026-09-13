"""Base types and abstract interface for sector-specific valuators."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from app.models.company import Company
from app.models.financial_statement import FinancialStatement


# ---------------------------------------------------------------------------
# Component result containers
#
# These mirror the historical DCFResult / EPVResult / BookValueResult shapes
# so IntrinsicValue rows written by the new strategies remain readable by the
# existing frontend without any schema translation.
# ---------------------------------------------------------------------------


@dataclass
class DCFResult:
    intrinsic_value_per_share: float | None = None
    total_intrinsic_value: float | None = None
    projected_fcfs: list[float] = field(default_factory=list)
    terminal_value: float | None = None
    growth_rate_used: float | None = None
    historical_fcfs: list[float] = field(default_factory=list)
    # Assumptions actually applied to this DCF run — surfaced so the UI can
    # explain *how* the intrinsic value was produced without users having to
    # cross-reference ``assumptions_used``.
    base_fcf: float | None = None
    discount_rate: float | None = None
    terminal_growth_rate: float | None = None
    projection_years: int | None = None
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
            "base_fcf": self.base_fcf,
            "discount_rate": self.discount_rate,
            "terminal_growth_rate": self.terminal_growth_rate,
            "projection_years": self.projection_years,
            "error": self.error,
        }


@dataclass
class EPVResult:
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
    """Composite valuation result — sector-agnostic wire format."""

    dcf: DCFResult = field(default_factory=DCFResult)
    epv: EPVResult = field(default_factory=EPVResult)
    book_value: BookValueResult = field(default_factory=BookValueResult)
    weighted_intrinsic_value: float | None = None
    current_market_price: float | None = None
    margin_of_safety_pct: float | None = None
    assumptions_used: dict[str, Any] = field(default_factory=dict)
    weights_applied: dict[str, float] = field(default_factory=dict)

    # Sector-aware extensions
    model_used: str = "industrial_dcf"
    scenario_values: dict[str, float] = field(default_factory=dict)
    component_values: dict[str, float] = field(default_factory=dict)
    quality_adjustments: dict[str, float] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def to_calculation_details(self) -> dict[str, Any]:
        return {
            "model_used": self.model_used,
            "dcf": self.dcf.to_dict(),
            "epv": self.epv.to_dict(),
            "book_value": self.book_value.to_dict(),
            "weights_applied": self.weights_applied,
            "scenario_values": self.scenario_values,
            "component_values": self.component_values,
            "quality_adjustments": self.quality_adjustments,
            "notes": self.notes,
        }


class SectorValuator(ABC):
    """Base class for sector-specific valuation strategies."""

    #: Machine-readable model identifier written to ``intrinsic_values.model_used``.
    model_name: str = "unknown"

    @abstractmethod
    def value(
        self,
        company: Company,
        financials: list[FinancialStatement],
        market_price: float | None,
        assumptions: dict[str, Any] | None = None,
    ) -> ValuationResult:
        """Compute a valuation and return a ``ValuationResult``."""


# ---------------------------------------------------------------------------
# Shared utilities used by multiple strategies
# ---------------------------------------------------------------------------


def get_numeric(value: Any) -> float | None:
    """Safely convert a potentially Decimal/None value to float."""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def calculate_margin_of_safety(
    intrinsic_value: float | None,
    market_price: float | None,
) -> float | None:
    """MOS = 1 - (market_price / intrinsic_value). None if IV unusable."""
    if intrinsic_value is None or market_price is None:
        return None
    if intrinsic_value <= 0:
        return None
    return 1.0 - (market_price / intrinsic_value)
