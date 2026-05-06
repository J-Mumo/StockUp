"""Watchlists router — CRUD for watchlists and watchlist items.

Endpoints:
    GET    /api/watchlists/                    — List user watchlists
    POST   /api/watchlists/                    — Create watchlist
    GET    /api/watchlists/{id}                — Watchlist detail with items
    DELETE /api/watchlists/{id}                — Delete watchlist
    POST   /api/watchlists/{id}/items          — Add company to watchlist
    PUT    /api/watchlists/{id}/items/{iid}    — Update target prices/notes
    DELETE /api/watchlists/{id}/items/{iid}    — Remove company from watchlist
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.company import Company
from app.models.price_history import PriceHistory
from app.models.user import User
from app.models.watchlist import Watchlist, WatchlistItem
from app.schemas.watchlist import (
    WatchlistCreate,
    WatchlistDetailResponse,
    WatchlistItemCreate,
    WatchlistItemResponse,
    WatchlistItemUpdate,
    WatchlistResponse,
)

router = APIRouter(prefix="/api/watchlists", tags=["watchlists"])


# ---------------------------------------------------------------------------
# Watchlist CRUD
# ---------------------------------------------------------------------------

@router.get("", response_model=list[WatchlistResponse])
def list_watchlists(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all watchlists for the current user."""
    watchlists = (
        db.query(Watchlist)
        .filter(Watchlist.user_id == current_user.id)
        .order_by(desc(Watchlist.created_at))
        .all()
    )
    return [_watchlist_to_response(w) for w in watchlists]


@router.post("", response_model=WatchlistResponse, status_code=status.HTTP_201_CREATED)
def create_watchlist(
    data: WatchlistCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a new watchlist."""
    watchlist = Watchlist(
        user_id=current_user.id,
        name=data.name,
    )
    db.add(watchlist)
    db.commit()
    db.refresh(watchlist)
    return _watchlist_to_response(watchlist)


@router.get("/{watchlist_id}", response_model=WatchlistDetailResponse)
def get_watchlist(
    watchlist_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get a watchlist with all its items and current prices."""
    watchlist = _get_user_watchlist(db, watchlist_id, current_user.id)

    # Load items with company info and prices
    items = (
        db.query(WatchlistItem)
        .filter(WatchlistItem.watchlist_id == watchlist.id)
        .order_by(WatchlistItem.added_at)
        .all()
    )

    # Preload companies and prices
    company_ids = [item.company_id for item in items]
    companies = {
        c.id: c for c in db.query(Company).filter(Company.id.in_(company_ids)).all()
    } if company_ids else {}

    latest_prices = _get_latest_prices(db, company_ids)

    item_responses = [
        _item_to_response(item, companies.get(item.company_id), latest_prices.get(item.company_id))
        for item in items
    ]

    return WatchlistDetailResponse(
        id=watchlist.id,
        user_id=watchlist.user_id,
        name=watchlist.name,
        created_at=watchlist.created_at,
        items=item_responses,
    )


@router.delete("/{watchlist_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_watchlist(
    watchlist_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a watchlist and all its items."""
    watchlist = _get_user_watchlist(db, watchlist_id, current_user.id)
    db.delete(watchlist)
    db.commit()
    return None


# ---------------------------------------------------------------------------
# Watchlist Items
# ---------------------------------------------------------------------------

@router.post(
    "/{watchlist_id}/items",
    response_model=WatchlistItemResponse,
    status_code=status.HTTP_201_CREATED,
)
def add_item(
    watchlist_id: int,
    data: WatchlistItemCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Add a company to a watchlist."""
    watchlist = _get_user_watchlist(db, watchlist_id, current_user.id)

    # Validate company exists
    company = db.query(Company).filter(Company.id == data.company_id).first()
    if company is None:
        raise HTTPException(status_code=404, detail="Company not found")

    # Check if company already in watchlist
    existing = (
        db.query(WatchlistItem)
        .filter(
            WatchlistItem.watchlist_id == watchlist.id,
            WatchlistItem.company_id == data.company_id,
        )
        .first()
    )
    if existing:
        raise HTTPException(
            status_code=400, detail="Company already in this watchlist"
        )

    item = WatchlistItem(
        watchlist_id=watchlist.id,
        company_id=data.company_id,
        target_buy_price=data.target_buy_price,
        target_sell_price=data.target_sell_price,
        notes=data.notes,
    )
    db.add(item)
    db.commit()
    db.refresh(item)

    current_price = _get_company_latest_price(db, data.company_id)
    return _item_to_response(item, company, current_price)


@router.put("/{watchlist_id}/items/{item_id}", response_model=WatchlistItemResponse)
def update_item(
    watchlist_id: int,
    item_id: int,
    data: WatchlistItemUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update target prices or notes for a watchlist item."""
    _get_user_watchlist(db, watchlist_id, current_user.id)

    item = (
        db.query(WatchlistItem)
        .filter(WatchlistItem.id == item_id, WatchlistItem.watchlist_id == watchlist_id)
        .first()
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Watchlist item not found")

    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(item, key, value)

    db.commit()
    db.refresh(item)

    company = db.query(Company).filter(Company.id == item.company_id).first()
    current_price = _get_company_latest_price(db, item.company_id)
    return _item_to_response(item, company, current_price)


@router.delete("/{watchlist_id}/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_item(
    watchlist_id: int,
    item_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Remove a company from a watchlist."""
    _get_user_watchlist(db, watchlist_id, current_user.id)

    item = (
        db.query(WatchlistItem)
        .filter(WatchlistItem.id == item_id, WatchlistItem.watchlist_id == watchlist_id)
        .first()
    )
    if item is None:
        raise HTTPException(status_code=404, detail="Watchlist item not found")

    db.delete(item)
    db.commit()
    return None


# ---------------------------------------------------------------------------
# Internal Helpers
# ---------------------------------------------------------------------------

def _get_user_watchlist(db: Session, watchlist_id: int, user_id: int) -> Watchlist:
    """Get watchlist ensuring it belongs to the user; raises 404 if not found."""
    watchlist = (
        db.query(Watchlist)
        .filter(Watchlist.id == watchlist_id, Watchlist.user_id == user_id)
        .first()
    )
    if watchlist is None:
        raise HTTPException(status_code=404, detail="Watchlist not found")
    return watchlist


def _get_latest_prices(db: Session, company_ids: list[int]) -> dict[int, float]:
    """Get latest closing price for each company."""
    if not company_ids:
        return {}
    prices = {}
    for cid in company_ids:
        price = _get_company_latest_price(db, cid)
        if price is not None:
            prices[cid] = price
    return prices


def _get_company_latest_price(db: Session, company_id: int) -> float | None:
    """Get latest closing price for a single company."""
    latest = (
        db.query(PriceHistory)
        .filter(PriceHistory.company_id == company_id)
        .order_by(desc(PriceHistory.price_date))
        .first()
    )
    return float(latest.close_price) if latest else None


def _watchlist_to_response(watchlist: Watchlist) -> WatchlistResponse:
    """Convert Watchlist model to response schema."""
    return WatchlistResponse(
        id=watchlist.id,
        user_id=watchlist.user_id,
        name=watchlist.name,
        item_count=len(watchlist.items) if watchlist.items else 0,
        created_at=watchlist.created_at,
    )


def _item_to_response(
    item: WatchlistItem,
    company: Company | None = None,
    current_price: float | None = None,
) -> WatchlistItemResponse:
    """Convert WatchlistItem model to response schema."""
    return WatchlistItemResponse(
        id=item.id,
        watchlist_id=item.watchlist_id,
        company_id=item.company_id,
        company_name=company.name if company else None,
        company_ticker=company.ticker_symbol if company else None,
        target_buy_price=float(item.target_buy_price) if item.target_buy_price else None,
        target_sell_price=float(item.target_sell_price) if item.target_sell_price else None,
        current_price=current_price,
        notes=item.notes,
        added_at=item.added_at,
    )
