"""Celery tasks for AI-generated per-company research narratives.

Scheduled + on-demand tasks that decide when to spend an LLM call to keep
each company's stored analysis fresh.

Tasks:

* :func:`refresh_ai_analysis_single` — regenerate for a single company if
  the fingerprint or staleness rules say so. Enqueued after new financials
  are ingested or a valuation recalc changes materially.
* :func:`refresh_stale_ai_analyses` — scheduled daily sweep that catches
  companies whose analysis has crossed the staleness ceiling or seen a
  large price move since generation.

Neither task raises on LLM failure — a bad LLM day shouldn't crash the
worker. Errors are logged and the task returns a ``status='failed'`` dict.
"""

from __future__ import annotations

import logging
from datetime import datetime

from tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Single-company on-demand regeneration
# ---------------------------------------------------------------------------

@celery_app.task(
    name="tasks.ai_analysis_tasks.refresh_ai_analysis_single",
    bind=True,
    max_retries=2,
    default_retry_delay=120,
    acks_late=True,
)
def refresh_ai_analysis_single(self, company_id: int, triggered_by: str):
    """Regenerate the AI analysis for one company if inputs have changed.

    Called after a valuation recalculation or a fresh financial statement
    ingest to give the LLM a chance to catch up. Honours the fingerprint
    cache — if nothing material changed we skip the LLM call.

    Args:
        company_id: Company to (potentially) regenerate for.
        triggered_by: Provenance tag stored on any new row. Typical values:
            ``'new_financials'``, ``'iv_change'``, ``'scheduled'``.
    """
    from app.database import SessionLocal
    from app.services import company_ai_analysis_service as svc

    db = SessionLocal()
    try:
        row, decision = svc.get_or_generate_analysis(
            db=db, company_id=company_id, triggered_by=triggered_by
        )
        logger.info(
            "[ai_analysis_tasks] company=%s trigger=%s decision=%s row_id=%s",
            company_id,
            triggered_by,
            decision.reason,
            row.id,
        )
        return {
            "status": "success",
            "company_id": company_id,
            "regenerated": decision.regenerate,
            "reason": decision.reason,
            "row_id": row.id,
        }
    except ValueError as exc:
        # Company doesn't exist — no point retrying.
        logger.warning(
            "[ai_analysis_tasks] company=%s missing: %s", company_id, exc
        )
        return {
            "status": "skipped",
            "company_id": company_id,
            "reason": "company_not_found",
        }
    except Exception as exc:  # noqa: BLE001 — retry decides on the exception
        db.rollback()
        logger.error(
            "[ai_analysis_tasks] company=%s trigger=%s failed: %s",
            company_id,
            triggered_by,
            exc,
            exc_info=True,
        )
        # LLM errors are typically transient (rate limits, provider blips).
        # Retry with exponential-ish backoff via Celery.
        try:
            raise self.retry(exc=exc)
        except self.MaxRetriesExceededError:
            return {
                "status": "failed",
                "company_id": company_id,
                "error": str(exc),
            }
    finally:
        db.close()


# ---------------------------------------------------------------------------
# Scheduled staleness sweep
# ---------------------------------------------------------------------------

@celery_app.task(
    name="tasks.ai_analysis_tasks.refresh_stale_ai_analyses",
    bind=True,
    max_retries=0,   # scheduled — next run will retry anything that failed
    acks_late=True,
)
def refresh_stale_ai_analyses(self):
    """Sweep for companies whose analysis is stale or price has drifted.

    Runs daily. For each active company:

    * If there's no analysis, or the fingerprint has changed, or the last
      analysis is older than the staleness ceiling, enqueue a single
      regeneration task per company (so LLM calls are parallelised by the
      broker and one slow provider response doesn't block the whole sweep).
    * Companies whose fingerprint is fresh and whose analysis is recent
      are skipped without incurring LLM cost.
    """
    from app.database import SessionLocal
    from app.models.company import Company
    from app.services import company_ai_analysis_service as svc

    started_at = datetime.utcnow()
    logger.info(
        "[ai_analysis_tasks] Starting stale AI-analysis sweep at %s",
        started_at.isoformat(),
    )

    db = SessionLocal()
    enqueued = 0
    skipped = 0
    errored = 0
    try:
        companies = (
            db.query(Company).filter(Company.is_active.is_(True)).all()
        )
        for company in companies:
            try:
                (
                    _c,
                    financials,
                    valuation,
                    latest_price,
                ) = svc._load_company_inputs(db, company.id)
            except ValueError:
                errored += 1
                continue
            if not financials:
                # No financials → nothing meaningful to analyse yet.
                skipped += 1
                continue

            fingerprint = svc.compute_input_fingerprint(
                company, financials, valuation, latest_price
            )
            current = svc.get_latest_analysis(db, company.id)
            decision = svc.should_regenerate(
                current, fingerprint, latest_price
            )
            if not decision.regenerate:
                skipped += 1
                continue

            refresh_ai_analysis_single.delay(
                company_id=company.id,
                triggered_by="scheduled",
            )
            enqueued += 1

        elapsed = (datetime.utcnow() - started_at).total_seconds()
        logger.info(
            "[ai_analysis_tasks] Sweep complete in %.1fs — "
            "enqueued=%d, skipped=%d, errored=%d",
            elapsed,
            enqueued,
            skipped,
            errored,
        )
        return {
            "status": "success",
            "enqueued": enqueued,
            "skipped": skipped,
            "errored": errored,
            "elapsed_seconds": elapsed,
        }
    except Exception as exc:  # noqa: BLE001
        logger.error(
            "[ai_analysis_tasks] Sweep failed: %s", exc, exc_info=True
        )
        return {"status": "failed", "error": str(exc)}
    finally:
        db.close()
