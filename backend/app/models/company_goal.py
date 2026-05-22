"""CompanyGoal and CompanyGoalProgress models.

Captures forward-looking commitments management makes in a given fiscal
year's annual report, and tracks how those commitments fare in
subsequent years. Designed for two-pass LLM extraction:

  Pass A — extract goals from year T report -> company_goals
  Pass B — assess each goal against year T+k report / data -> company_goal_progress
"""

from datetime import datetime
from sqlalchemy import (
    String,
    Integer,
    Text,
    DateTime,
    Numeric,
    ForeignKey,
    Index,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


# Allowed enum-like string values (validated by application code; kept as
# plain strings in the DB so we can evolve without migrations).
GOAL_CATEGORIES = {"financial", "strategic", "esg", "operational"}
GOAL_STATUSES = {
    "achieved",
    "on_track",
    "partially_achieved",
    "missed",
    "abandoned",
    "no_mention",
}
GOAL_CONFIDENCES = {"high", "medium", "low"}
ASSESSMENT_METHODS = {"mechanical", "llm", "manual"}


class CompanyGoal(Base):
    __tablename__ = "company_goals"
    __table_args__ = (
        Index("ix_company_goals_company_year", "company_id", "fiscal_year_set"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id"), nullable=False
    )
    fiscal_year_set: Mapped[int] = mapped_column(Integer, nullable=False)

    goal_text: Mapped[str] = mapped_column(String(500), nullable=False)
    goal_category: Mapped[str] = mapped_column(String(30), nullable=False)

    # Quantitative target structure (populated when the goal cites a
    # specific numeric target; left null for purely strategic goals).
    metric_name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    target_value: Mapped[float | None] = mapped_column(Numeric(20, 4), nullable=True)
    target_unit: Mapped[str | None] = mapped_column(String(20), nullable=True)
    target_horizon_year: Mapped[int | None] = mapped_column(Integer, nullable=True)

    source_section: Mapped[str | None] = mapped_column(String(40), nullable=True)
    source_quote: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    company = relationship("Company")
    progress = relationship(
        "CompanyGoalProgress",
        back_populates="goal",
        cascade="all, delete-orphan",
        order_by="CompanyGoalProgress.assessed_in_fiscal_year",
    )

    def __repr__(self) -> str:
        return (
            f"<CompanyGoal(company_id={self.company_id}, "
            f"year={self.fiscal_year_set}, category={self.goal_category}, "
            f"text={self.goal_text[:40]!r})>"
        )


class CompanyGoalProgress(Base):
    __tablename__ = "company_goal_progress"
    __table_args__ = (
        UniqueConstraint(
            "goal_id",
            "assessed_in_fiscal_year",
            name="ix_goal_progress_goal_year",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    goal_id: Mapped[int] = mapped_column(
        ForeignKey("company_goals.id", ondelete="CASCADE"), nullable=False
    )
    assessed_in_fiscal_year: Mapped[int] = mapped_column(Integer, nullable=False)

    status: Mapped[str] = mapped_column(String(30), nullable=False)
    actual_value: Mapped[float | None] = mapped_column(Numeric(20, 4), nullable=True)
    narrative: Mapped[str | None] = mapped_column(Text, nullable=True)
    evidence_quote: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[str] = mapped_column(String(10), default="medium")
    assessment_method: Mapped[str] = mapped_column(String(20), default="llm")

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    goal = relationship("CompanyGoal", back_populates="progress")

    def __repr__(self) -> str:
        return (
            f"<CompanyGoalProgress(goal_id={self.goal_id}, "
            f"year={self.assessed_in_fiscal_year}, status={self.status})>"
        )
