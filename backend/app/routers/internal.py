"""Internal API endpoints for machine-to-machine use.

These endpoints are guarded by a shared secret in ``X-Internal-Token`` and
support the local price fetcher (which runs on the operator's machine to
bypass MarketScreener's IP-level bot protection blocking the Hetzner VM).

DO NOT expose this router without a strong ``INTERNAL_API_TOKEN`` env var.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import get_settings
from app.data.price_fetcher import upsert_price
from app.database import get_db
from app.models.company import Company


router = APIRouter(prefix="/api/internal", tags=["internal"])
settings = get_settings()


def _require_token(x_internal_token: str = Header(default="")) -> None:
    expected = (settings.internal_api_token or "").strip()
    if not expected:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Internal API disabled (INTERNAL_API_TOKEN not configured)",
        )
    if not x_internal_token or x_internal_token != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid internal token",
        )


# ---------------------------------------------------------------------------
# GET /api/internal/companies-with-ms-url
# ---------------------------------------------------------------------------

class MSCompanyOut(BaseModel):
    id: int
    ticker: str
    marketscreener_graphics_url: str


@router.get("/companies-with-ms-url", response_model=list[MSCompanyOut])
def list_ms_companies(
    _: None = Depends(_require_token),
    db: Session = Depends(get_db),
):
    """Return active companies that have a Marketscreener graphics URL."""
    rows = (
        db.query(Company)
        .filter(
            Company.is_active.is_(True),
            Company.marketscreener_graphics_url.isnot(None),
        )
        .order_by(Company.ticker_symbol.asc())
        .all()
    )
    return [
        MSCompanyOut(
            id=c.id,
            ticker=c.ticker_symbol,
            marketscreener_graphics_url=c.marketscreener_graphics_url,
        )
        for c in rows
    ]


# ---------------------------------------------------------------------------
# POST /api/internal/prices/upsert
# ---------------------------------------------------------------------------

class CandleIn(BaseModel):
    date: date
    open: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    close: float
    volume: Optional[int] = None


class PricesUpsertIn(BaseModel):
    ticker: str = Field(..., description="NSE ticker symbol")
    source: str = Field("marketscreener", description="Data source label")
    candles: list[CandleIn]


class PricesUpsertOut(BaseModel):
    ticker: str
    company_id: int
    received: int
    upserted: int


@router.post("/prices/upsert", response_model=PricesUpsertOut)
def upsert_prices(
    payload: PricesUpsertIn,
    _: None = Depends(_require_token),
    db: Session = Depends(get_db),
):
    """Upsert a batch of daily OHLCV candles for a company (idempotent)."""
    company = (
        db.query(Company)
        .filter(Company.ticker_symbol == payload.ticker.upper())
        .first()
    )
    if not company:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Unknown ticker: {payload.ticker}",
        )

    upserted = 0
    for candle in payload.candles:
        row = {
            "price_date": candle.date,
            "open_price": candle.open,
            "high_price": candle.high,
            "low_price": candle.low,
            "close_price": candle.close,
            "volume": candle.volume,
            "source": payload.source,
        }
        try:
            if upsert_price(db, company.id, row):
                upserted += 1
        except Exception:
            db.rollback()
            raise
    db.commit()

    return PricesUpsertOut(
        ticker=company.ticker_symbol,
        company_id=company.id,
        received=len(payload.candles),
        upserted=upserted,
    )
