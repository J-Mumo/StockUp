"""Company model - represents a listed company on a market."""

from datetime import datetime
from sqlalchemy import String, Boolean, DateTime, Integer, BigInteger, Text, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Company(Base):
    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(primary_key=True)
    market_id: Mapped[int] = mapped_column(ForeignKey("markets.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    ticker_symbol: Mapped[str] = mapped_column(String(20), unique=True, nullable=False)
    yfinance_ticker: Mapped[str | None] = mapped_column(String(20), unique=True, nullable=True)
    sector: Mapped[str | None] = mapped_column(String(100), nullable=True)
    industry: Mapped[str | None] = mapped_column(String(100), nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    website: Mapped[str | None] = mapped_column(String(200), nullable=True)
    investor_relations_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    marketscreener_graphics_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    shares_outstanding: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # Relationships
    market = relationship("Market", back_populates="companies")
    prices = relationship("PriceHistory", back_populates="company", cascade="all, delete-orphan")
    financials = relationship("FinancialStatement", back_populates="company", cascade="all, delete-orphan")
    valuations = relationship("IntrinsicValue", back_populates="company", cascade="all, delete-orphan")

    def __repr__(self) -> str:
        return f"<Company(ticker={self.ticker_symbol}, name={self.name})>"
