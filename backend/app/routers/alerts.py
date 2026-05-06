"""Alerts router — CRUD for user stock alerts + alert triggering.

Supports alert types: margin_of_safety, price_above, price_below, custom.
Alerts are triggered when valuations are recalculated.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.alert import Alert
from app.models.company import Company
from app.models.intrinsic_value import IntrinsicValue
from app.models.price_history import PriceHistory
from app.models.user import User
from app.schemas.analysis import AlertCreate, AlertResponse, AlertUpdate

router = APIRouter(prefix="/api/alerts", tags=["alerts"])


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

@router.get("", response_model=list[AlertResponse])
def list_alerts(
    is_triggered: bool | None = Query(None, description="Filter by triggered status"),
    is_read: bool | None = Query(None, description="Filter by read status"),
    company_id: int | None = Query(None, description="Filter by company"),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List all alerts for the current user with optional filters."""
    query = db.query(Alert).filter(Alert.user_id == current_user.id)

    if is_triggered is not None:
        query = query.filter(Alert.is_triggered == is_triggered)
    if is_read is not None:
        query = query.filter(Alert.is_read == is_read)
    if company_id is not None:
        query = query.filter(Alert.company_id == company_id)

    alerts = query.order_by(desc(Alert.created_at)).all()
    return [_alert_to_response(a) for a in alerts]


@router.post("", response_model=AlertResponse, status_code=status.HTTP_201_CREATED)
def create_alert(
    data: AlertCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Create a new alert for a company."""
    # Validate company exists
    company = db.query(Company).filter(Company.id == data.company_id).first()
    if company is None:
        raise HTTPException(status_code=404, detail="Company not found")

    alert = Alert(
        user_id=current_user.id,
        company_id=data.company_id,
        alert_type=data.alert_type,
        condition=data.condition,
        threshold_value=data.threshold_value,
        is_active=True,
        is_triggered=False,
        is_read=False,
    )
    db.add(alert)
    db.commit()
    db.refresh(alert)
    return _alert_to_response(alert)


@router.get("/{alert_id}", response_model=AlertResponse)
def get_alert(
    alert_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Get a single alert by ID (must belong to current user)."""
    alert = _get_user_alert(db, alert_id, current_user.id)
    return _alert_to_response(alert)


@router.put("/{alert_id}", response_model=AlertResponse)
def update_alert(
    alert_id: int,
    data: AlertUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Update an existing alert."""
    alert = _get_user_alert(db, alert_id, current_user.id)

    update_data = data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(alert, key, value)

    db.commit()
    db.refresh(alert)
    return _alert_to_response(alert)


@router.delete("/{alert_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_alert(
    alert_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete an alert."""
    alert = _get_user_alert(db, alert_id, current_user.id)
    db.delete(alert)
    db.commit()
    return None


@router.post("/{alert_id}/mark-read", response_model=AlertResponse)
def mark_alert_read(
    alert_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Mark an alert as read."""
    alert = _get_user_alert(db, alert_id, current_user.id)
    alert.is_read = True
    db.commit()
    db.refresh(alert)
    return _alert_to_response(alert)


# ---------------------------------------------------------------------------
# Alert Triggering
# ---------------------------------------------------------------------------

def check_and_trigger_alerts(db: Session, company_id: int) -> list[Alert]:
    """Check and trigger alerts for a company after valuation recalculation.

    Called by the valuation engine after computing new valuations.

    Checks:
        - margin_of_safety alerts: triggered when MOS exceeds threshold
        - price_above: triggered when price exceeds threshold
        - price_below: triggered when price drops below threshold

    Returns list of newly triggered alerts.
    """
    # Get active alerts for this company
    active_alerts = (
        db.query(Alert)
        .filter(
            Alert.company_id == company_id,
            Alert.is_active == True,
            Alert.is_triggered == False,
        )
        .all()
    )

    if not active_alerts:
        return []

    # Get latest valuation
    latest_val = (
        db.query(IntrinsicValue)
        .filter(IntrinsicValue.company_id == company_id)
        .order_by(desc(IntrinsicValue.valuation_date))
        .first()
    )

    # Get latest price
    latest_price = (
        db.query(PriceHistory)
        .filter(PriceHistory.company_id == company_id)
        .order_by(desc(PriceHistory.price_date))
        .first()
    )

    triggered: list[Alert] = []

    for alert in active_alerts:
        should_trigger = False
        message = ""

        if alert.alert_type == "margin_of_safety" and latest_val:
            mos = float(latest_val.margin_of_safety_pct) if latest_val.margin_of_safety_pct else None
            if mos is not None:
                # threshold_value is the MOS percentage threshold (e.g., 30 for 30%)
                threshold_decimal = float(alert.threshold_value) / 100.0
                if mos >= threshold_decimal:
                    should_trigger = True
                    message = (
                        f"Margin of safety reached {mos*100:.1f}% "
                        f"(threshold: {float(alert.threshold_value):.1f}%)"
                    )

        elif alert.alert_type == "price_below" and latest_price:
            price = float(latest_price.close_price)
            threshold = float(alert.threshold_value)
            if price <= threshold:
                should_trigger = True
                message = f"Price dropped to {price:.2f} (threshold: {threshold:.2f})"

        elif alert.alert_type == "price_above" and latest_price:
            price = float(latest_price.close_price)
            threshold = float(alert.threshold_value)
            if price >= threshold:
                should_trigger = True
                message = f"Price rose to {price:.2f} (threshold: {threshold:.2f})"

        if should_trigger:
            alert.is_triggered = True
            alert.triggered_at = datetime.utcnow()
            alert.message = message
            triggered.append(alert)

    if triggered:
        db.flush()

    return triggered


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _get_user_alert(db: Session, alert_id: int, user_id: int) -> Alert:
    """Get alert ensuring it belongs to the user; raises 404 if not found."""
    alert = (
        db.query(Alert)
        .filter(Alert.id == alert_id, Alert.user_id == user_id)
        .first()
    )
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found")
    return alert


def _alert_to_response(alert: Alert) -> AlertResponse:
    """Convert Alert model to response schema."""
    return AlertResponse(
        id=alert.id,
        user_id=alert.user_id,
        company_id=alert.company_id,
        alert_type=alert.alert_type,
        condition=alert.condition,
        threshold_value=float(alert.threshold_value),
        is_active=alert.is_active,
        is_triggered=alert.is_triggered,
        is_read=alert.is_read,
        message=alert.message,
        triggered_at=alert.triggered_at,
        created_at=alert.created_at,
    )
