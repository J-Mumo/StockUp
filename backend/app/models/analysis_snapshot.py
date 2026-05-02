"""AnalysisSnapshot model - saved analysis reports for future reference."""

from datetime import datetime
from sqlalchemy import String, DateTime, Text, JSON, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class AnalysisSnapshot(Base):
    __tablename__ = "analysis_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    analysis_type: Mapped[str] = mapped_column(String(50), nullable=False)
    # Types: valuation, comparison, sector_analysis, custom
    analysis_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    data_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    valuation_at_time: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Relationships
    company = relationship("Company")
    user = relationship("User", back_populates="analysis_snapshots")

    def __repr__(self) -> str:
        return f"<AnalysisSnapshot(title={self.title}, company_id={self.company_id})>"
