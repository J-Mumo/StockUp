"""CompanyNote model - user notes on companies (buy/sell thesis, observations)."""

from datetime import datetime
from sqlalchemy import String, DateTime, Text, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class CompanyNote(Base):
    __tablename__ = "company_notes"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), nullable=False)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    note_text: Mapped[str] = mapped_column(Text, nullable=False)
    tag: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # Tags: buy_thesis, sell_thesis, observation, risk, catalyst
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # Relationships
    company = relationship("Company")
    user = relationship("User")

    def __repr__(self) -> str:
        return f"<CompanyNote(id={self.id}, company_id={self.company_id})>"
