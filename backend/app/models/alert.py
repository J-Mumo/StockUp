"""Alert model - user-configurable stock alerts."""

from datetime import datetime
from sqlalchemy import (
    String, Boolean, DateTime, Numeric, Text, ForeignKey, Index
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Alert(Base):
    __tablename__ = "alerts"
    __table_args__ = (
        Index("ix_alerts_user_status", "user_id", "is_triggered", "is_read"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), nullable=False)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"), nullable=False)
    alert_type: Mapped[str] = mapped_column(String(30), nullable=False)
    # Types: margin_of_safety, price_above, price_below, custom
    condition: Mapped[str] = mapped_column(String(50), nullable=False)
    # e.g., "mos_above_30", "price_below_50"
    threshold_value: Mapped[float] = mapped_column(Numeric(12, 4), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    is_triggered: Mapped[bool] = mapped_column(Boolean, default=False)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    triggered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    # Relationships
    user = relationship("User", back_populates="alerts")
    company = relationship("Company")

    def __repr__(self) -> str:
        return f"<Alert(user_id={self.user_id}, type={self.alert_type}, triggered={self.is_triggered})>"
