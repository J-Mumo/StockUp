"""Tests for notification inbox and account-email preferences."""

from datetime import datetime

from app.models.portfolio import Portfolio, PortfolioTransaction
from app.models.notification import NotificationPreference
from app.services.recommendation_engine import QualityAssessment, QualityScore
from app.services import notification_service


def _quality(sector_kind="industrial"):
    return QualityAssessment(
        sector_kind=sector_kind,
        factors=[QualityScore(name=str(i), passed=True) for i in range(10)],
    )

from app.models.notification import Notification
from app.models.watchlist import Watchlist, WatchlistItem
from app.services.notification_service import create_recommendation_change_notifications
from app.services.notification_service import create_strong_buy_opportunity_notifications


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

    def test_strong_buy_opportunity_requires_opt_in_and_unowned(self, db, user, company):
        preference = NotificationPreference(user_id=user.id, opportunity_alerts_enabled=True)
        db.add(preference)
        db.flush()
        quality = _quality()
        created = create_strong_buy_opportunity_notifications(
            db, company, valuation_id=7001, margin_of_safety=0.25,
            quality=quality, previous_action="Hold", new_action="Strong Buy",
        )
        assert len(created) == 1
        assert created[0].notification_type == "strong_buy_opportunity"
        assert created[0].email_status == "queued_digest"

        # It is an entry transition, not a daily repeat.
        assert create_strong_buy_opportunity_notifications(
            db, company, valuation_id=7001, margin_of_safety=0.25,
            quality=quality, previous_action="Strong Buy", new_action="Strong Buy",
        ) == []

        # Re-entering on a different valuation day must not resend the same
        # company's discovery, even after the first notification was sent.
        created[0].email_status = "sent"
        assert create_strong_buy_opportunity_notifications(
            db, company, valuation_id=7002, margin_of_safety=0.31,
            quality=quality, previous_action="Hold", new_action="Strong Buy",
        ) == []
        assert create_strong_buy_opportunity_notifications(
            db, company, valuation_id=7003, margin_of_safety=0.31,
            quality=quality, previous_action=None, new_action="Strong Buy",
        ) == []

    def test_owned_company_and_missing_bank_credit_metrics_are_excluded(self, db, user, company, company2):
        db.add(NotificationPreference(user_id=user.id, opportunity_alerts_enabled=True))
        portfolio = Portfolio(user_id=user.id, name="test")
        db.add(portfolio)
        db.flush()
        db.add(PortfolioTransaction(
            portfolio_id=portfolio.id, company_id=company.id,
            transaction_type="buy", quantity=5, price_per_share=10,
            total_amount=50, transaction_date=datetime.utcnow().date(),
        ))
        db.flush()
        assert create_strong_buy_opportunity_notifications(
            db, company, valuation_id=7201, margin_of_safety=0.4,
            quality=_quality(), previous_action="Hold", new_action="Strong Buy",
        ) == []
        assert create_strong_buy_opportunity_notifications(
            db, company2, valuation_id=7202, margin_of_safety=0.4,
            quality=_quality("bank"), previous_action="Hold", new_action="Strong Buy",
            bank_metrics={"npl_ratio": 0.08},
        ) == []
        assert create_strong_buy_opportunity_notifications(
            db, company2, valuation_id=7203, margin_of_safety=0.4,
            quality=_quality("bank"), previous_action="Hold", new_action="Strong Buy",
            bank_metrics={"npl_ratio": 0.08, "cost_of_risk": 0.01},
        )

    def test_opportunities_are_digest_only_even_for_immediate_email(self, db, user, company, company2, monkeypatch):
        db.add(NotificationPreference(user_id=user.id, opportunity_alerts_enabled=True))
        db.flush()
        events = []
        for i, item in enumerate((company, company2), 1):
            events.extend(create_strong_buy_opportunity_notifications(
                db, item, valuation_id=7300 + i, margin_of_safety=0.35,
                quality=_quality("bank" if item == company2 else "industrial"),
                previous_action="Hold", new_action="Strong Buy",
                bank_metrics={"npl_ratio": 0.08, "cost_of_risk": 0.01},
            ))
        assert len(events) == 2
        assert notification_service.deliver_notification_email(db, events[0].id) == "queued_digest"
        sent_messages = []
        monkeypatch.setattr(notification_service, "_send_smtp_message", sent_messages.append)
        settings = notification_service.get_settings()
        monkeypatch.setattr(notification_service, "get_settings", lambda: settings.model_copy(update={
            "smtp_host": "fake.test", "smtp_from_email": "alerts@stockup.test",
        }))
        result = notification_service.deliver_daily_digests(db)
        assert result["sent"] == 2
        assert len(sent_messages) == 1
        assert user.email in sent_messages[0]["To"]
        assert company.ticker_symbol in sent_messages[0].get_content()
        assert company2.ticker_symbol in sent_messages[0].get_content()
        assert all(event.email_status == "sent" for event in events)

    def test_opportunity_inbox_can_be_hidden_without_losing_dedupe(self, client, auth_headers, db, user, company):
        db.add(NotificationPreference(user_id=user.id, opportunity_alerts_enabled=True, in_app_enabled=False))
        db.flush()
        created = create_strong_buy_opportunity_notifications(
            db, company, valuation_id=7401, margin_of_safety=0.3,
            quality=_quality(), previous_action="Hold", new_action="Strong Buy",
        )
        assert len(created) == 1
        response = client.get("/api/notifications", headers=auth_headers)
        assert response.status_code == 200
        assert response.json() == {"notifications": [], "unread_count": 0}

    def test_legacy_opportunity_is_not_rediscovered(self, db, user, company):
        db.add(NotificationPreference(user_id=user.id, opportunity_alerts_enabled=True))
        db.add(Notification(
            user_id=user.id, company_id=company.id,
            notification_type="strong_buy_opportunity", title="old", body="old",
            dedupe_key=f"opportunity:strong-buy:123:{user.id}", email_status="sent",
        ))
        db.flush()
        assert create_strong_buy_opportunity_notifications(
            db, company, valuation_id=7402, margin_of_safety=0.3,
            quality=_quality(), previous_action="Hold", new_action="Strong Buy",
        ) == []

    def test_watchlist_change_does_not_duplicate_discovery(self, db, user, company):
        db.add(NotificationPreference(user_id=user.id, opportunity_alerts_enabled=True))
        watchlist = Watchlist(user_id=user.id, name="watch")
        db.add(watchlist)
        db.flush()
        db.add(WatchlistItem(watchlist_id=watchlist.id, company_id=company.id))
        db.flush()
        assert create_recommendation_change_notifications(
            db, company, previous_action="Hold", new_action="Strong Buy", valuation_id=7701,
        )
        assert create_strong_buy_opportunity_notifications(
            db, company, valuation_id=7701, margin_of_safety=0.35,
            quality=_quality(), previous_action="Hold", new_action="Strong Buy",
        ) == []

    def test_digest_rechecks_opt_out_before_sending(self, db, user, company, monkeypatch):
        preference = NotificationPreference(user_id=user.id, opportunity_alerts_enabled=True)
        db.add(preference)
        db.flush()
        event = create_strong_buy_opportunity_notifications(
            db, company, valuation_id=7501, margin_of_safety=0.3,
            quality=_quality(), previous_action="Hold", new_action="Strong Buy",
        )[0]
        preference.opportunity_alerts_enabled = False
        def unexpected_send(message):
            raise AssertionError("opted-out user must not receive an email")
        monkeypatch.setattr(notification_service, "_send_smtp_message", unexpected_send)
        notification_service.deliver_daily_digests(db)
        assert event.email_status == "suppressed"

    def test_only_one_opportunity_digest_per_user_per_eat_day(self, db, user, company, company2, monkeypatch):
        db.add(NotificationPreference(user_id=user.id, opportunity_alerts_enabled=True))
        db.flush()
        messages = []
        monkeypatch.setattr(notification_service, "_send_smtp_message", messages.append)
        settings = notification_service.get_settings()
        monkeypatch.setattr(notification_service, "get_settings", lambda: settings.model_copy(update={
            "smtp_host": "fake.test", "smtp_from_email": "alerts@stockup.test",
        }))
        first = create_strong_buy_opportunity_notifications(
            db, company, valuation_id=7601, margin_of_safety=0.35,
            quality=_quality(), previous_action="Hold", new_action="Strong Buy",
        )[0]
        assert notification_service.deliver_daily_digests(db)["sent"] == 1
        second = create_strong_buy_opportunity_notifications(
            db, company2, valuation_id=7602, margin_of_safety=0.35,
            quality=_quality("bank"), previous_action="Hold", new_action="Strong Buy",
            bank_metrics={"npl_ratio": 0.08, "cost_of_risk": 0.01},
        )[0]
        assert notification_service.deliver_daily_digests(db)["sent"] == 0
        assert len(messages) == 1
        assert first.email_status == "sent"
        assert second.email_status == "queued_digest"