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
        for company_id in company_ids:
            triggered = check_and_trigger_alerts(db, company_id)
            total_triggered += len(triggered)

        db.commit()

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
