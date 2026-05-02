"""FinancialStatement model - company financial data entered manually."""

from datetime import datetime, date
from sqlalchemy import (
    String, DateTime, Date, Numeric, Integer, Text, ForeignKey, Index
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class FinancialStatement(Base):
    __tablename__ = "financial_statements"
    __table_args__ = (
        Index("ix_financial_company_year", "company_id", "fiscal_year"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), nullable=False)
    fiscal_year: Mapped[int] = mapped_column(Integer, nullable=False)
    period_type: Mapped[str] = mapped_column(String(20), default="annual")  # annual, quarterly

    # Income Statement
    revenue: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    net_income: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    earnings_per_share: Mapped[float | None] = mapped_column(Numeric(12, 4), nullable=True)

    # Balance Sheet
    total_assets: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    total_liabilities: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    total_equity: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    shareholders_equity: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    book_value_per_share: Mapped[float | None] = mapped_column(Numeric(12, 4), nullable=True)

    # Cash Flow Statement
    operating_cash_flow: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    capital_expenditures: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    free_cash_flow: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    dividends_per_share: Mapped[float | None] = mapped_column(Numeric(12, 4), nullable=True)

    # Ratios
    return_on_equity: Mapped[float | None] = mapped_column(Numeric(8, 4), nullable=True)
    debt_to_equity: Mapped[float | None] = mapped_column(Numeric(8, 4), nullable=True)
    current_ratio: Mapped[float | None] = mapped_column(Numeric(8, 4), nullable=True)

    # Metadata
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    report_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    entered_by_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # Relationships
    company = relationship("Company", back_populates="financials")
    entered_by = relationship("User", back_populates="entered_financials")

    def __repr__(self) -> str:
        return f"<FinancialStatement(company_id={self.company_id}, year={self.fiscal_year})>"
