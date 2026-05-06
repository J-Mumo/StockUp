"""Tests for alert CRUD and alert triggering logic.

Tests the alerts API endpoints and the check_and_trigger_alerts function.
"""

import pytest
from datetime import date, datetime

from app.models.alert import Alert
from app.models.company import Company
from app.models.intrinsic_value import IntrinsicValue
from app.models.price_history import PriceHistory
from app.routers.alerts import check_and_trigger_alerts


# ---------------------------------------------------------------------------
# Test: Alert CRUD via API
# ---------------------------------------------------------------------------

class TestAlertsCRUD:
    """Test alert CRUD endpoints."""

    def test_create_alert(self, client, auth_headers, company):
        """Create an alert returns 201 with correct data."""
        response = client.post(
            "/api/alerts",
            json={
                "company_id": company.id,
                "alert_type": "margin_of_safety",
                "condition": "mos_above_30",
                "threshold_value": 30.0,
            },
            headers=auth_headers,
        )
        assert response.status_code == 201
        data = response.json()
        assert data["company_id"] == company.id
        assert data["alert_type"] == "margin_of_safety"
        assert data["condition"] == "mos_above_30"
        assert data["threshold_value"] == 30.0
        assert data["is_active"] is True
        assert data["is_triggered"] is False
        assert data["is_read"] is False

    def test_create_alert_invalid_company(self, client, auth_headers):
        """Creating alert for non-existent company returns 404."""
        response = client.post(
            "/api/alerts",
            json={
                "company_id": 99999,
                "alert_type": "price_below",
                "condition": "price_below_50",
                "threshold_value": 50.0,
            },
            headers=auth_headers,
        )
        assert response.status_code == 404

    def test_create_alert_invalid_type(self, client, auth_headers, company):
        """Creating alert with invalid type returns 422."""
        response = client.post(
            "/api/alerts",
            json={
                "company_id": company.id,
                "alert_type": "invalid_type",
                "condition": "whatever",
                "threshold_value": 30.0,
            },
            headers=auth_headers,
        )
        assert response.status_code == 422

    def test_list_alerts(self, client, auth_headers, db, user, company):
        """List alerts returns user's alerts."""
        # Create some alerts directly
        for i in range(3):
            alert = Alert(
                user_id=user.id,
                company_id=company.id,
                alert_type="price_below",
                condition=f"price_below_{50 + i * 10}",
                threshold_value=50.0 + i * 10,
            )
            db.add(alert)
        db.flush()

        response = client.get("/api/alerts", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 3

    def test_list_alerts_filter_triggered(self, client, auth_headers, db, user, company):
        """Filter alerts by triggered status."""
        # Create one triggered and one not
        alert1 = Alert(
            user_id=user.id,
            company_id=company.id,
            alert_type="price_below",
            condition="price_below_50",
            threshold_value=50.0,
            is_triggered=False,
        )
        alert2 = Alert(
            user_id=user.id,
            company_id=company.id,
            alert_type="price_above",
            condition="price_above_100",
            threshold_value=100.0,
            is_triggered=True,
            triggered_at=datetime.utcnow(),
            message="Price reached 105",
        )
        db.add_all([alert1, alert2])
        db.flush()

        response = client.get("/api/alerts?is_triggered=true", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["is_triggered"] is True

    def test_get_alert(self, client, auth_headers, db, user, company):
        """Get single alert by ID."""
        alert = Alert(
            user_id=user.id,
            company_id=company.id,
            alert_type="margin_of_safety",
            condition="mos_above_25",
            threshold_value=25.0,
        )
        db.add(alert)
        db.flush()

        response = client.get(f"/api/alerts/{alert.id}", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == alert.id
        assert data["threshold_value"] == 25.0

    def test_get_alert_not_found(self, client, auth_headers):
        """Get non-existent alert returns 404."""
        response = client.get("/api/alerts/99999", headers=auth_headers)
        assert response.status_code == 404

    def test_update_alert(self, client, auth_headers, db, user, company):
        """Update alert modifies fields."""
        alert = Alert(
            user_id=user.id,
            company_id=company.id,
            alert_type="price_below",
            condition="price_below_40",
            threshold_value=40.0,
        )
        db.add(alert)
        db.flush()

        response = client.put(
            f"/api/alerts/{alert.id}",
            json={"threshold_value": 35.0, "is_active": False},
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["threshold_value"] == 35.0
        assert data["is_active"] is False

    def test_delete_alert(self, client, auth_headers, db, user, company):
        """Delete alert returns 204."""
        alert = Alert(
            user_id=user.id,
            company_id=company.id,
            alert_type="price_above",
            condition="price_above_100",
            threshold_value=100.0,
        )
        db.add(alert)
        db.flush()

        response = client.delete(f"/api/alerts/{alert.id}", headers=auth_headers)
        assert response.status_code == 204

        # Confirm deleted
        response = client.get(f"/api/alerts/{alert.id}", headers=auth_headers)
        assert response.status_code == 404

    def test_mark_alert_read(self, client, auth_headers, db, user, company):
        """Mark alert as read."""
        alert = Alert(
            user_id=user.id,
            company_id=company.id,
            alert_type="margin_of_safety",
            condition="mos_above_30",
            threshold_value=30.0,
            is_triggered=True,
            message="MOS reached 35%",
        )
        db.add(alert)
        db.flush()

        response = client.post(f"/api/alerts/{alert.id}/mark-read", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["is_read"] is True

    def test_alerts_unauthorized(self, client):
        """Alerts require authentication."""
        response = client.get("/api/alerts")
        assert response.status_code == 401


# ---------------------------------------------------------------------------
# Test: Alert Triggering Logic
# ---------------------------------------------------------------------------

class TestAlertTriggering:
    """Test the check_and_trigger_alerts function."""

    def test_trigger_mos_alert(self, db, user, company):
        """MOS alert triggers when margin of safety exceeds threshold."""
        # Create alert for MOS > 30%
        alert = Alert(
            user_id=user.id,
            company_id=company.id,
            alert_type="margin_of_safety",
            condition="mos_above_30",
            threshold_value=30.0,  # 30%
            is_active=True,
            is_triggered=False,
        )
        db.add(alert)

        # Create valuation with MOS = 35%
        iv = IntrinsicValue(
            company_id=company.id,
            valuation_date=date(2026, 5, 1),
            weighted_intrinsic_value=100.0,
            current_market_price=65.0,
            margin_of_safety_pct=0.35,  # 35%
            calculated_at=datetime.utcnow(),
        )
        db.add(iv)
        db.flush()

        triggered = check_and_trigger_alerts(db, company.id)

        assert len(triggered) == 1
        assert triggered[0].id == alert.id
        assert triggered[0].is_triggered is True
        assert triggered[0].triggered_at is not None
        assert "35.0%" in triggered[0].message

    def test_no_trigger_below_threshold(self, db, user, company):
        """MOS alert does NOT trigger when below threshold."""
        alert = Alert(
            user_id=user.id,
            company_id=company.id,
            alert_type="margin_of_safety",
            condition="mos_above_30",
            threshold_value=30.0,
            is_active=True,
            is_triggered=False,
        )
        db.add(alert)

        # Valuation with MOS = 20% (below 30% threshold)
        iv = IntrinsicValue(
            company_id=company.id,
            valuation_date=date(2026, 5, 1),
            margin_of_safety_pct=0.20,
            calculated_at=datetime.utcnow(),
        )
        db.add(iv)
        db.flush()

        triggered = check_and_trigger_alerts(db, company.id)
        assert len(triggered) == 0
        assert alert.is_triggered is False

    def test_trigger_price_below_alert(self, db, user, company):
        """Price below alert triggers when price drops below threshold."""
        alert = Alert(
            user_id=user.id,
            company_id=company.id,
            alert_type="price_below",
            condition="price_below_40",
            threshold_value=40.0,
            is_active=True,
            is_triggered=False,
        )
        db.add(alert)

        # Price at 38 (below 40 threshold)
        price = PriceHistory(
            company_id=company.id,
            price_date=date(2026, 5, 1),
            close_price=38.0,
            volume=100000,
            source="test",
            fetched_at=datetime.utcnow(),
        )
        db.add(price)
        db.flush()

        triggered = check_and_trigger_alerts(db, company.id)

        assert len(triggered) == 1
        assert triggered[0].is_triggered is True
        assert "38.00" in triggered[0].message

    def test_trigger_price_above_alert(self, db, user, company):
        """Price above alert triggers when price exceeds threshold."""
        alert = Alert(
            user_id=user.id,
            company_id=company.id,
            alert_type="price_above",
            condition="price_above_100",
            threshold_value=100.0,
            is_active=True,
            is_triggered=False,
        )
        db.add(alert)

        price = PriceHistory(
            company_id=company.id,
            price_date=date(2026, 5, 1),
            close_price=105.0,
            volume=100000,
            source="test",
            fetched_at=datetime.utcnow(),
        )
        db.add(price)
        db.flush()

        triggered = check_and_trigger_alerts(db, company.id)

        assert len(triggered) == 1
        assert triggered[0].is_triggered is True
        assert "105.00" in triggered[0].message

    def test_inactive_alert_not_triggered(self, db, user, company):
        """Inactive alerts are not checked."""
        alert = Alert(
            user_id=user.id,
            company_id=company.id,
            alert_type="price_below",
            condition="price_below_50",
            threshold_value=50.0,
            is_active=False,  # Inactive
            is_triggered=False,
        )
        db.add(alert)

        price = PriceHistory(
            company_id=company.id,
            price_date=date(2026, 5, 1),
            close_price=30.0,  # Well below threshold
            volume=100000,
            source="test",
            fetched_at=datetime.utcnow(),
        )
        db.add(price)
        db.flush()

        triggered = check_and_trigger_alerts(db, company.id)
        assert len(triggered) == 0

    def test_already_triggered_not_retriggered(self, db, user, company):
        """Already triggered alerts don't trigger again."""
        alert = Alert(
            user_id=user.id,
            company_id=company.id,
            alert_type="price_below",
            condition="price_below_50",
            threshold_value=50.0,
            is_active=True,
            is_triggered=True,  # Already triggered
            triggered_at=datetime.utcnow(),
        )
        db.add(alert)

        price = PriceHistory(
            company_id=company.id,
            price_date=date(2026, 5, 1),
            close_price=30.0,
            volume=100000,
            source="test",
            fetched_at=datetime.utcnow(),
        )
        db.add(price)
        db.flush()

        triggered = check_and_trigger_alerts(db, company.id)
        assert len(triggered) == 0

    def test_multiple_alerts_triggered(self, db, user, company):
        """Multiple alerts can trigger simultaneously."""
        alert1 = Alert(
            user_id=user.id,
            company_id=company.id,
            alert_type="price_below",
            condition="price_below_50",
            threshold_value=50.0,
            is_active=True,
            is_triggered=False,
        )
        alert2 = Alert(
            user_id=user.id,
            company_id=company.id,
            alert_type="price_below",
            condition="price_below_40",
            threshold_value=40.0,
            is_active=True,
            is_triggered=False,
        )
        db.add_all([alert1, alert2])

        price = PriceHistory(
            company_id=company.id,
            price_date=date(2026, 5, 1),
            close_price=35.0,  # Below both thresholds
            volume=100000,
            source="test",
            fetched_at=datetime.utcnow(),
        )
        db.add(price)
        db.flush()

        triggered = check_and_trigger_alerts(db, company.id)
        assert len(triggered) == 2

    def test_no_alerts_for_company(self, db, company):
        """No active alerts for company returns empty list."""
        triggered = check_and_trigger_alerts(db, company.id)
        assert triggered == []
