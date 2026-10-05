"""Notification event creation and SMTP delivery.

All outbound email uses ``User.email`` (the address used at signup). The app
does not store a second notification address, avoiding a common source of
misdirected account notifications.
"""

from __future__ import annotations

import logging
import smtplib
from datetime import datetime
from email.message import EmailMessage

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.alert import Alert
from app.models.company import Company
from app.models.notification import Notification, NotificationPreference
from app.models.user import User
from app.models.watchlist import Watchlist, WatchlistItem

logger = logging.getLogger(__name__)


def get_or_create_preferences(db: Session, user_id: int) -> NotificationPreference:
    """Return default-on notification preferences for a user."""
    preference = (
        db.query(NotificationPreference)
        .filter(NotificationPreference.user_id == user_id)
        .first()
    )
    if preference is None:
        preference = NotificationPreference(user_id=user_id)
        db.add(preference)
        db.flush()
    return preference


def _category_enabled(preference: NotificationPreference, notification_type: str) -> bool:
    if notification_type.startswith("price_"):
        return preference.price_alerts_enabled
    if notification_type.startswith("mos_") or notification_type.startswith("valuation_"):
        return preference.valuation_alerts_enabled
    if notification_type.startswith("recommendation_"):
        return preference.recommendation_alerts_enabled
    return True


def create_alert_notification(
    db: Session,
    alert: Alert,
    company: Company,
) -> Notification | None:
    """Create one durable event for a freshly triggered alert.

    The alert id makes the event idempotent even if Celery retries an alert
    evaluation task. An alert itself is one-shot, and the notification is too.
    """
    preference = get_or_create_preferences(db, alert.user_id)
    notification_type = {
        "price_above": "price_target",
        "price_below": "price_target",
        "margin_of_safety": "mos_target",
    }.get(alert.alert_type, "alert")
    if not _category_enabled(preference, notification_type):
        return None

    dedupe_key = f"alert:{alert.id}"
    existing = db.query(Notification).filter(Notification.dedupe_key == dedupe_key).first()
    if existing is not None:
        return existing

    label = {
        "price_target": "Price target",
        "mos_target": "Margin of safety target",
        "alert": "Alert",
    }[notification_type]
    title = f"{company.ticker_symbol}: {label} reached"
    notification = Notification(
        user_id=alert.user_id,
        company_id=company.id,
        alert_id=alert.id,
        notification_type=notification_type,
        priority="high" if notification_type == "mos_target" else "normal",
        title=title,
        body=alert.message or f"Your {alert.alert_type.replace('_', ' ')} alert triggered.",
        link_path=f"/stocks/{company.id}",
        payload={
            "ticker": company.ticker_symbol,
            "alert_type": alert.alert_type,
            "threshold": float(alert.threshold_value),
        },
        dedupe_key=dedupe_key,
        # The sender decides whether it is sent, suppressed, or skipped due
        # to intentionally absent SMTP configuration.
        email_status="pending",
    )
    db.add(notification)
    db.flush()
    return notification


def create_recommendation_change_notifications(
    db: Session,
    company: Company,
    *,
    previous_action: str,
    new_action: str,
    valuation_id: int,
) -> list[Notification]:
    """Create watchlist-only events when a company's recommendation changes."""
    if previous_action == new_action:
        return []
    watcher_ids = [
        row[0]
        for row in db.query(Watchlist.user_id)
        .join(WatchlistItem, WatchlistItem.watchlist_id == Watchlist.id)
        .filter(WatchlistItem.company_id == company.id)
        .distinct()
        .all()
    ]
    created: list[Notification] = []
    for user_id in watcher_ids:
        preference = get_or_create_preferences(db, user_id)
        if not preference.recommendation_alerts_enabled:
            continue
        dedupe_key = f"recommendation:{valuation_id}:{user_id}"
        if db.query(Notification.id).filter(Notification.dedupe_key == dedupe_key).first():
            continue
        notification = Notification(
            user_id=user_id,
            company_id=company.id,
            notification_type="recommendation_change",
            priority="high",
            title=f"{company.ticker_symbol}: recommendation changed to {new_action}",
            body=(
                f"StockUp's recommendation changed from {previous_action} to {new_action} "
                "after the latest valuation update."
            ),
            link_path=f"/stocks/{company.id}",
            payload={"previous_action": previous_action, "new_action": new_action},
            dedupe_key=dedupe_key,
            email_status="pending",
        )
        db.add(notification)
        db.flush()
        created.append(notification)
    return created


def deliver_notification_email(db: Session, notification_id: int) -> str:
    """Deliver one notification to the signed-up email address via SMTP.

    Returns a delivery state for Celery logging. SMTP is intentionally
    optional in development: the in-app event remains available and delivery
    is recorded as ``skipped`` instead of repeatedly retrying configuration
    that does not exist.
    """
    notification = db.get(Notification, notification_id)
    if notification is None:
        return "missing"
    if notification.email_status == "sent":
        return "already_sent"

    user = db.get(User, notification.user_id)
    if user is None or not user.is_active:
        notification.email_status = "suppressed"
        notification.email_error = "user unavailable or inactive"
        db.commit()
        return "suppressed"

    preference = get_or_create_preferences(db, user.id)
    if (
        not preference.email_enabled
        or preference.email_frequency == "off"
        or not _category_enabled(preference, notification.notification_type)
    ):
        notification.email_status = "suppressed"
        notification.email_error = "disabled by notification preference"
        db.commit()
        return "suppressed"
    if preference.email_frequency == "daily_digest":
        notification.email_status = "queued_digest"
        db.commit()
        return "queued_digest"

    settings = get_settings()
    if not settings.smtp_host or not settings.smtp_from_email:
        notification.email_status = "skipped"
        notification.email_error = "SMTP is not configured"
        db.commit()
        logger.info("Email notification %s retained in-app; SMTP is not configured", notification.id)
        return "skipped"

    detail_url = f"{settings.public_app_url.rstrip('/')}{notification.link_path or '/alerts'}"
    message = _build_email(
        to_email=user.email,
        subject=notification.title,
        body=f"{notification.body}\n\nView in StockUp: {detail_url}",
    )

    notification.email_attempted_at = datetime.utcnow()
    try:
        _send_smtp_message(message)
        notification.email_status = "sent"
        notification.email_sent_at = datetime.utcnow()
        notification.email_error = None
        db.commit()
        logger.info("Notification %s emailed to account user_id=%s", notification.id, user.id)
        return "sent"
    except Exception as exc:  # noqa: BLE001 - preserve delivery state for retry/audit
        notification.email_status = "failed"
        notification.email_error = str(exc)[:1000]
        db.commit()
        logger.exception("Failed to email notification %s to user_id=%s", notification.id, user.id)
        raise


def deliver_daily_digests(db: Session) -> dict[str, int]:
    """Send one grouped email per user for queued daily-digest notifications."""
    settings = get_settings()
    queued = (
        db.query(Notification)
        .filter(Notification.email_status == "queued_digest")
        .order_by(Notification.user_id, Notification.created_at)
        .all()
    )
    if not queued:
        return {"users": 0, "notifications": 0, "sent": 0, "skipped": 0}

    grouped: dict[int, list[Notification]] = {}
    for notification in queued:
        grouped.setdefault(notification.user_id, []).append(notification)

    sent = skipped = 0
    for user_id, notifications in grouped.items():
        user = db.get(User, user_id)
        preference = get_or_create_preferences(db, user_id)
        if user is None or not user.is_active or not preference.email_enabled:
            for notification in notifications:
                notification.email_status = "suppressed"
                notification.email_error = "user unavailable or email disabled"
            skipped += len(notifications)
            continue
        if not settings.smtp_host or not settings.smtp_from_email:
            for notification in notifications:
                notification.email_status = "skipped"
                notification.email_error = "SMTP is not configured"
            skipped += len(notifications)
            continue

        lines = [f"- {n.title}: {n.body}" for n in notifications]
        message = _build_email(
            to_email=user.email,
            subject=f"Your daily StockUp digest ({len(notifications)})",
            body="Here are your queued StockUp notifications:\n\n" + "\n".join(lines)
            + f"\n\nView your notification inbox: {settings.public_app_url.rstrip('/')}/alerts",
        )
        try:
            _send_smtp_message(message)
            now = datetime.utcnow()
            for notification in notifications:
                notification.email_status = "sent"
                notification.email_attempted_at = now
                notification.email_sent_at = now
                notification.email_error = None
            sent += len(notifications)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Failed to send daily notification digest to user_id=%s", user_id)
            for notification in notifications:
                notification.email_status = "failed"
                notification.email_error = str(exc)[:1000]
                notification.email_attempted_at = datetime.utcnow()
    db.commit()
    return {"users": len(grouped), "notifications": len(queued), "sent": sent, "skipped": skipped}


def _build_email(*, to_email: str, subject: str, body: str) -> EmailMessage:
    settings = get_settings()
    message = EmailMessage()
    message["Subject"] = f"[{settings.app_name}] {subject}"
    message["From"] = f"{settings.smtp_from_name} <{settings.smtp_from_email}>"
    # Never accept a destination email from the API payload: ``to_email`` is
    # always looked up from User.email by the callers above.
    message["To"] = to_email
    message.set_content(body + "\n")
    return message


def _send_smtp_message(message: EmailMessage) -> None:
    settings = get_settings()
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as server:
        if settings.smtp_use_tls:
            server.starttls()
        if settings.smtp_username:
            server.login(settings.smtp_username, settings.smtp_password)
        server.send_message(message)