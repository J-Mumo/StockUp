"""IntrinsicValue model - computed valuations for companies."""

from datetime import datetime, date
from sqlalchemy import String, DateTime, Date, Numeric, Text, JSON, ForeignKey, Index
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class IntrinsicValue(Base):
    __tablename__ = "intrinsic_values"
    __table_args__ = (
        Index("ix_intrinsic_company_date", "company_id", "valuation_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), nullable=False)
    valuation_date: Mapped[date] = mapped_column(Date, nullable=False)

    # Valuation results
    dcf_value: Mapped[float | None] = mapped_column(Numeric(12, 4), nullable=True)
    epv_value: Mapped[float | None] = mapped_column(Numeric(12, 4), nullable=True)
    book_value_estimate: Mapped[float | None] = mapped_column(Numeric(12, 4), nullable=True)
    weighted_intrinsic_value: Mapped[float | None] = mapped_column(Numeric(12, 4), nullable=True)

    # Market comparison
    current_market_price: Mapped[float | None] = mapped_column(Numeric(12, 4), nullable=True)
    margin_of_safety_pct: Mapped[float | None] = mapped_column(Numeric(8, 4), nullable=True)

    # Recommendation
    recommendation: Mapped[str | None] = mapped_column(String(20), nullable=True)
    recommendation_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Calculation details (stored as JSON for full auditability)
    assumptions: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    calculation_details: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    calculated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Relationships
    company = relationship("Company", back_populates="valuations")

    def __repr__(self) -> str:
        return f"<IntrinsicValue(company_id={self.company_id}, date={self.valuation_date}, iv={self.weighted_intrinsic_value})>"
