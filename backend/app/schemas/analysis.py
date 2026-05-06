"""Pydantic schemas for alerts and analysis snapshots APIs."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Alerts
# ---------------------------------------------------------------------------

class AlertCreate(BaseModel):
    """Payload for creating a new alert."""
    company_id: int
    alert_type: str = Field(
        ...,
        pattern=r"^(margin_of_safety|price_above|price_below|custom)$",
        description="Type of alert trigger",
    )
    condition: str = Field(
        ...,
        max_length=50,
        description="Condition string, e.g. 'mos_above_30', 'price_below_50'",
    )
    threshold_value: float = Field(
        ...,
        description="Numeric threshold for the alert condition",
    )


class AlertUpdate(BaseModel):
    """Payload for updating an alert."""
    alert_type: str | None = Field(
        None,
        pattern=r"^(margin_of_safety|price_above|price_below|custom)$",
    )
    condition: str | None = Field(None, max_length=50)
    threshold_value: float | None = None
    is_active: bool | None = None
    is_read: bool | None = None


class AlertResponse(BaseModel):
    """Alert response schema."""
    id: int
    user_id: int
    company_id: int
    alert_type: str
    condition: str
    threshold_value: float
    is_active: bool
    is_triggered: bool
    is_read: bool
    message: str | None = None
    triggered_at: datetime | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Analysis Snapshots
# ---------------------------------------------------------------------------

class AnalysisSnapshotCreate(BaseModel):
    """Payload for creating an analysis snapshot."""
    company_id: int
    title: str = Field(..., min_length=1, max_length=200)
    analysis_type: str = Field(
        ...,
        pattern=r"^(valuation|comparison|sector_analysis|custom)$",
        description="Type of analysis",
    )
    analysis_text: str | None = None
    data_snapshot: dict[str, Any] | None = None
    valuation_at_time: dict[str, Any] | None = None


class AnalysisSnapshotResponse(BaseModel):
    """Analysis snapshot response schema."""
    id: int
    company_id: int
    user_id: int
    title: str
    analysis_type: str
    analysis_text: str | None = None
    data_snapshot: dict[str, Any] | None = None
    valuation_at_time: dict[str, Any] | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


# ---------------------------------------------------------------------------
# Valuation compute request / response
# ---------------------------------------------------------------------------

class ValuationComputeRequest(BaseModel):
    """Request body for triggering a valuation computation."""
    discount_rate: float | None = Field(None, ge=0.01, le=0.50, description="Override discount rate")
    terminal_growth_rate: float | None = Field(None, ge=0.0, le=0.10, description="Override terminal growth")
    projection_years: int | None = Field(None, ge=5, le=20, description="Override projection period")
    dcf_weight: float | None = Field(None, ge=0.0, le=1.0)
    epv_weight: float | None = Field(None, ge=0.0, le=1.0)
    bv_weight: float | None = Field(None, ge=0.0, le=1.0)


class RecommendationResponse(BaseModel):
    """Recommendation engine output."""
    action: str
    reason: str
    margin_of_safety_pct: float | None = None
    quality_score: int
    quality_max_score: int
    quality_factors: list[dict[str, Any]] = []
