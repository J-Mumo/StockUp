"""PriceHistory model - daily stock price records."""

from datetime import datetime, date
from sqlalchemy import (
    String, DateTime, Date, Numeric, BigInteger, ForeignKey, UniqueConstraint, Index
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class PriceHistory(Base):
    __tablename__ = "price_history"
    __table_args__ = (
        UniqueConstraint("company_id", "price_date", name="uq_company_price_date"),
        Index("ix_price_history_date", "price_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), nullable=False)
    price_date: Mapped[date] = mapped_column(Date, nullable=False)
    open_price: Mapped[float | None] = mapped_column(Numeric(12, 4), nullable=True)
    high_price: Mapped[float | None] = mapped_column(Numeric(12, 4), nullable=True)
    low_price: Mapped[float | None] = mapped_column(Numeric(12, 4), nullable=True)
    close_price: Mapped[float] = mapped_column(Numeric(12, 4), nullable=False)
    volume: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    change_percent: Mapped[float | None] = mapped_column(Numeric(8, 4), nullable=True)
    source: Mapped[str] = mapped_column(String(20), default="yfinance")  # yfinance, scraper
    fetched_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Relationships
    company = relationship("Company", back_populates="prices")

    def __repr__(self) -> str:
        return f"<PriceHistory(company_id={self.company_id}, date={self.price_date}, close={self.close_price})>"
