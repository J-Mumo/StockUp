"""Celery tasks for alert evaluation.

Scheduled daily at 7:30PM EAT (16:30 UTC) via Celery Beat — runs after valuations.
"""

import logging
from datetime import datetime

from tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(
    name="tasks.alert_tasks.evaluate_all_alerts",
    bind=True,
    max_retries=2,
    default_retry_delay=60,
    acks_late=True,
)
def evaluate_all_alerts(self):
    """Evaluate all active alerts across all companies.

    Iterates through companies that have active (untriggered) alerts and
    checks conditions against the latest price/valuation data.

    Alert types supported:
      - margin_of_safety: MOS >= threshold (as percentage)
      - price_above: latest close >= threshold
      - price_below: latest close <= threshold
    """
    from sqlalchemy import distinct

    from app.database import SessionLocal
    from app.models.alert import Alert
    from app.routers.alerts import check_and_trigger_alerts

    started_at = datetime.utcnow()
    logger.info(f"[alert_tasks] Starting alert evaluation at {started_at.isoformat()}")

    db = SessionLocal()
    try:
        # Get distinct company_ids that have active, untriggered alerts
        company_ids = (
            db.query(distinct(Alert.company_id))
            .filter(Alert.is_active == True, Alert.is_triggered == False)
            .all()
        )
        company_ids = [cid[0] for cid in company_ids]

        if not company_ids:
            logger.info("[alert_tasks] No active alerts to evaluate")
            return {"status": "success", "companies_checked": 0, "alerts_triggered": 0}

        total_triggered = 0
        notification_ids: list[int] = []
        for company_id in company_ids:
            triggered = check_and_trigger_alerts(db, company_id)
            total_triggered += len(triggered)
            for alert in triggered:
                notification = next(
                    (n for n in alert.user.notifications if n.alert_id == alert.id),
                    None,
                )
                if notification is not None:
                    notification_ids.append(notification.id)

        db.commit()

        for notification_id in notification_ids:
            send_notification_email.delay(notification_id)

        elapsed = (datetime.utcnow() - started_at).total_seconds()
        logger.info(
            f"[alert_tasks] Evaluation complete in {elapsed:.1f}s — "
            f"companies_checked={len(company_ids)}, alerts_triggered={total_triggered}"
        )
        return {
            "status": "success",
            "companies_checked": len(company_ids),
            "alerts_triggered": total_triggered,
            "elapsed_seconds": elapsed,
        }
    except Exception as exc:
        db.rollback()
        logger.error(f"[alert_tasks] Evaluation failed: {exc}", exc_info=True)
        raise self.retry(exc=exc)
    finally:
        db.close()


@celery_app.task(
    name="tasks.alert_tasks.evaluate_company_alerts",
    bind=True,
    max_retries=2,
    default_retry_delay=30,
)
def evaluate_company_alerts(self, company_id: int):
    """Evaluate alerts for a single company.

    Useful for triggering after an on-demand valuation recalculation.

    Args:
        company_id: ID of the company to check alerts for.
    """
    from app.database import SessionLocal
    from app.routers.alerts import check_and_trigger_alerts

    logger.info(f"[alert_tasks] Evaluating alerts for company_id={company_id}")

    db = SessionLocal()
    try:
        triggered = check_and_trigger_alerts(db, company_id)
        db.commit()

        for alert in triggered:
            notification = next(
                (n for n in alert.user.notifications if n.alert_id == alert.id),
                None,
            )
            if notification is not None:
                send_notification_email.delay(notification.id)

        logger.info(
            f"[alert_tasks] company_id={company_id}: "
            f"{len(triggered)} alert(s) triggered"
        )
        return {
            "status": "success",
            "company_id": company_id,
            "alerts_triggered": len(triggered),
        }
    except Exception as exc:
        db.rollback()
        logger.error(
            f"[alert_tasks] Evaluate company_id={company_id} failed: {exc}",
            exc_info=True,
        )
        raise self.retry(exc=exc)
    finally:
        db.close()


@celery_app.task(
    name="tasks.alert_tasks.send_notification_email",
    bind=True,
    max_retries=2,
    default_retry_delay=120,
)
def send_notification_email(self, notification_id: int):
    """Deliver an event to the account's signup email address via SMTP."""
    from app.database import SessionLocal
    from app.services.notification_service import deliver_notification_email

    db = SessionLocal()
    try:
        return {"notification_id": notification_id, "status": deliver_notification_email(db, notification_id)}
    except Exception as exc:
        db.rollback()
        raise self.retry(exc=exc)
    finally:
        db.close()


@celery_app.task(name="tasks.alert_tasks.retry_pending_notification_emails")
def retry_pending_notification_emails():
    """Retry failed / pending immediate deliveries after transient SMTP errors."""
    from app.database import SessionLocal
    from app.models.notification import Notification

    db = SessionLocal()
    try:
        ids = [
            row[0]
            for row in db.query(Notification.id)
            .filter(Notification.email_status.in_(("pending", "failed")))
            .limit(200)
            .all()
        ]
        for notification_id in ids:
            send_notification_email.delay(notification_id)
        return {"queued": len(ids)}
    finally:
        db.close()


@celery_app.task(name="tasks.alert_tasks.send_daily_notification_digests")
def send_daily_notification_digests():
    """Send opted-in users' queued daily notification digests."""
    from app.database import SessionLocal
    from app.services.notification_service import deliver_daily_digests

    db = SessionLocal()
    try:
        return deliver_daily_digests(db)
    finally:
        db.close()
