"""Pydantic schemas for the goal-tracking API."""

from datetime import datetime
from pydantic import BaseModel


class CompanyGoalProgressRead(BaseModel):
    id: int
    assessed_in_fiscal_year: int
    status: str
    actual_value: float | None = None
    narrative: str | None = None
    evidence_quote: str | None = None
    confidence: str
    assessment_method: str
    created_at: datetime

    model_config = {"from_attributes": True}


class CompanyGoalRead(BaseModel):
    id: int
    company_id: int
    fiscal_year_set: int
    goal_text: str
    goal_category: str
    metric_name: str | None = None
    target_value: float | None = None
    target_unit: str | None = None
    target_horizon_year: int | None = None
    source_section: str | None = None
    source_quote: str | None = None
    created_at: datetime
    updated_at: datetime
    progress: list[CompanyGoalProgressRead] = []

    model_config = {"from_attributes": True}


class GoalScorecardRow(BaseModel):
    """Aggregate counts for a single goal-setting fiscal year."""

    fiscal_year_set: int
    goals_total: int
    achieved: int
    on_track: int
    partially_achieved: int
    missed: int
    abandoned: int
    no_mention: int
    not_yet_assessed: int
