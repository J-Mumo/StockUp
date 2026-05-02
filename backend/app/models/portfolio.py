"""Portfolio and PortfolioTransaction models."""

from datetime import datetime, date
from sqlalchemy import (
    String, DateTime, Date, Numeric, Text, ForeignKey, Index
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Portfolio(Base):
    __tablename__ = "portfolios"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    initial_capital: Mapped[float | None] = mapped_column(Numeric(18, 2), nullable=True)
    currency: Mapped[str] = mapped_column(String(10), default="KES")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # Relationships
    user = relationship("User", back_populates="portfolios")
    transactions = relationship(
        "PortfolioTransaction", back_populates="portfolio", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<Portfolio(name={self.name}, user_id={self.user_id})>"


class PortfolioTransaction(Base):
    __tablename__ = "portfolio_transactions"
    __table_args__ = (
        Index("ix_portfolio_txn_date", "portfolio_id", "transaction_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    portfolio_id: Mapped[int] = mapped_column(ForeignKey("portfolios.id"), nullable=False)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), nullable=False)
    transaction_type: Mapped[str] = mapped_column(String(10), nullable=False)  # buy, sell
    quantity: Mapped[float] = mapped_column(Numeric(12, 4), nullable=False)
    price_per_share: Mapped[float] = mapped_column(Numeric(12, 4), nullable=False)
    total_amount: Mapped[float] = mapped_column(Numeric(18, 2), nullable=False)
    fees: Mapped[float | None] = mapped_column(Numeric(12, 2), default=0)
    transaction_date: Mapped[date] = mapped_column(Date, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Relationships
    portfolio = relationship("Portfolio", back_populates="transactions")
    company = relationship("Company")

    def __repr__(self) -> str:
        return f"<PortfolioTransaction(type={self.transaction_type}, company_id={self.company_id}, qty={self.quantity})>"
