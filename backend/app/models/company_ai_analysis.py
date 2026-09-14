"""CompanyAIAnalysis model — LLM-generated per-company research narrative.

Stores a grounded, cached AI critique of the current valuation output for a
company. One row per (company, snapshot of inputs); latest row per company
is what's surfaced on the company detail page.

Design notes:

* **Shared across users, not user-scoped.** Unlike ``AnalysisSnapshot``
  (which is a user's saved report), this is a system-generated view of the
  company — every user sees the same latest analysis so we don't LLM-thrash.
* **Fingerprint-based cache key.** ``input_fingerprint`` is a stable hash
  of the underlying financials + latest price + valuation output. If the
  fingerprint matches the last row we don't regenerate.
* **History preserved.** Each new generation inserts a new row rather than
  updating the previous one, so users can see how the AI's view evolved
  after a new annual report or a material price move.
* **Trigger provenance.** ``triggered_by`` records *why* the analysis was
  generated (user open, new financials, price move, scheduled staleness,
  manual refresh) so we can audit LLM spend.

The persisted structured output shape (``structured_json``):

    {
        "verdict": str,                    # short label, e.g. "Consider" / "Wait"
        "iv_low_kes": float | None,
        "iv_high_kes": float | None,
        "bull_points": [str, ...],
        "bear_points": [str, ...],
        "key_risks": [str, ...],
        "caveats": [str, ...],
        "sector_specific_notes": [str, ...],
    }
"""

from datetime import datetime
from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class CompanyAIAnalysis(Base):
    __tablename__ = "company_ai_analyses"
    __table_args__ = (
        Index("ix_ai_analysis_company_generated", "company_id", "generated_at"),
        Index("ix_ai_analysis_fingerprint", "company_id", "input_fingerprint"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(
        ForeignKey("companies.id", ondelete="CASCADE"), nullable=False
    )

    # When the LLM call completed successfully.
    generated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )

    # Provenance — which model produced this row, and under which prompt.
    # Prompt versioning matters: when we materially change the system prompt
    # we don't want to silently mix old-format and new-format rows in the UI.
    model_name: Mapped[str] = mapped_column(String(64), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(16), nullable=False)

    # Hash of the input snapshot (financials + latest price + valuation).
    # If the fingerprint matches the last row we skip regeneration.
    input_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)

    # Canonical sector kind used to select the sector-specific prompt clauses.
    # Free-form so future subsector labels (energy/downstream, energy/generation)
    # don't require a schema change.
    sector_kind: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # Human-readable markdown narrative (what the UI renders).
    narrative_md: Mapped[str] = mapped_column(Text, nullable=False)

    # Machine-readable extraction (see module docstring for shape).
    structured_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Why this analysis was generated. One of:
    #   'user_open' | 'new_financials' | 'price_move' | 'iv_change' |
    #   'scheduled' | 'manual'
    triggered_by: Mapped[str] = mapped_column(String(32), nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )

    # Relationships
    company = relationship("Company")

    def __repr__(self) -> str:
        return (
            f"<CompanyAIAnalysis(company_id={self.company_id}, "
            f"generated_at={self.generated_at.isoformat()}, "
            f"triggered_by={self.triggered_by})>"
        )
