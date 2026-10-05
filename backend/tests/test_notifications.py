"""Tests for notification inbox and account-email preferences."""

from datetime import datetime

from app.models.notification import Notification
from app.models.watchlist import Watchlist, WatchlistItem
from app.services.notification_service import create_recommendation_change_notifications


class TestNotificationInbox:
    def test_preferences_default_to_signup_email_delivery(self, client, auth_headers):
        response = client.get("/api/notifications/preferences", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["email_enabled"] is True
        assert data["email_frequency"] == "immediate"

    def test_list_and_mark_notification_read(self, client, auth_headers, db, user, company):
        notification = Notification(
            user_id=user.id,
            company_id=company.id,
            notification_type="price_target",
            priority="normal",
            title="TEST: price target reached",
            body="Price crossed your configured target.",
            dedupe_key=f"test-notification-{user.id}-{company.id}",
            email_status="skipped",
            created_at=datetime.utcnow(),
        )
        db.add(notification)
        db.flush()

        response = client.get("/api/notifications", headers=auth_headers)
        assert response.status_code == 200
        assert response.json()["unread_count"] >= 1
        assert any(row["id"] == notification.id for row in response.json()["notifications"])

        response = client.post(f"/api/notifications/{notification.id}/mark-read", headers=auth_headers)
        assert response.status_code == 200
        assert response.json()["read_at"] is not None

    def test_update_email_preference(self, client, auth_headers):
        response = client.put(
            "/api/notifications/preferences",
            json={"email_enabled": False, "email_frequency": "off"},
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.json()["email_enabled"] is False
        assert response.json()["email_frequency"] == "off"

    def test_recommendation_change_only_notifies_watchers(self, db, user, company):
        watchlist = Watchlist(user_id=user.id, name="Test watchlist")
        db.add(watchlist)
        db.flush()
        db.add(WatchlistItem(watchlist_id=watchlist.id, company_id=company.id))
        db.flush()

        created = create_recommendation_change_notifications(
            db,
            company,
            previous_action="Hold",
            new_action="Accumulate",
            valuation_id=123456,
        )
        assert len(created) == 1
        assert created[0].user_id == user.id
        assert created[0].notification_type == "recommendation_change"

        repeat = create_recommendation_change_notifications(
            db,
            company,
            previous_action="Hold",
            new_action="Accumulate",
            valuation_id=123456,
        )
        assert repeat == []