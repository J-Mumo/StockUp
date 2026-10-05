"""Celery application configuration with Redis broker and Beat scheduler.

Usage:
    # Start worker (Windows - must use solo pool):
    celery -A tasks.celery_app worker --pool=solo --loglevel=info

    # Start beat scheduler (separate terminal on Windows):
    celery -A tasks.celery_app beat --loglevel=info

    # Linux/macOS - can combine worker + beat:
    celery -A tasks.celery_app worker --beat --loglevel=info
"""

import os
import platform
import sys

from celery import Celery
from celery.schedules import crontab

# Ensure the backend directory is on sys.path for imports
backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

# Load settings
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")

# Create Celery app
celery_app = Celery(
    "stockup",
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=[
        "tasks.price_tasks",
        "tasks.valuation_tasks",
        "tasks.alert_tasks",
        "tasks.ai_analysis_tasks",
    ],
)

# Celery configuration
celery_app.conf.update(
    # Serialization
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Africa/Nairobi",
    enable_utc=True,

    # Retry policy (Step 44)
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_default_retry_delay=60,  # 1 minute initial delay
    task_max_retries=3,

    # Worker settings
    worker_prefetch_multiplier=1,
    worker_max_tasks_per_child=100,

    # Windows compatibility: prefork pool has permission issues on Windows
    # Use 'solo' pool instead (single-threaded but avoids billiard issues)
    worker_pool="solo" if platform.system() == "Windows" else "prefork",

    # Result backend
    result_expires=86400,  # 24 hours
)

# ---------------------------------------------------------------------------
# Celery Beat Schedule (Step 43)
# Celery crontab uses the configured Africa/Nairobi timezone: hour values
# below are LOCAL EAT hours, not UTC. The price fetch is currently disabled.
# ---------------------------------------------------------------------------

celery_app.conf.beat_schedule = {
    # NOTE: daily-price-fetch is intentionally disabled in production.
    # Marketscreener (and the other public NSE sources we've tried) blocks the
    # Hetzner VM's IP range with HTTP 403 from Akamai. Prices are ingested via
    # a local Windows scheduled task that runs `backend/scripts/local_price_updater.py`
    # from the operator's home IP and POSTs to `/api/internal/prices/upsert`.
    # Re-enable this block if/when a working server-side source is added.
    # "daily-price-fetch": {
    #     "task": "tasks.price_tasks.fetch_all_prices",
    #     "schedule": crontab(hour=18, minute=0),  # 6PM EAT
    # },
    "daily-valuation-recalc": {
        "task": "tasks.valuation_tasks.recalculate_all_valuations",
        "schedule": crontab(hour=19, minute=0),  # 7PM EAT
    },
    "daily-alert-evaluation": {
        "task": "tasks.alert_tasks.evaluate_all_alerts",
        "schedule": crontab(hour=19, minute=30),  # 7:30PM EAT
    },
    "notification-email-retry": {
        "task": "tasks.alert_tasks.retry_pending_notification_emails",
        "schedule": crontab(hour="*/2", minute=0),
    },
    "daily-notification-digest": {
        "task": "tasks.alert_tasks.send_daily_notification_digests",
        "schedule": crontab(hour=20, minute=0),  # 8PM EAT, after alert evaluation
    },
    "monthly-financials-refresh": {
        "task": "tasks.valuation_tasks.refresh_all_financials",
        "schedule": crontab(hour=2, minute=0, day_of_month="1"),  # 1st of month, 2AM EAT
    },
    "monthly-annual-report-parsing": {
        "task": "tasks.valuation_tasks.parse_annual_reports",
        "schedule": crontab(hour=3, minute=0, day_of_month="5"),  # 5th of month, 3AM EAT
    },
    # AI analysis staleness sweep — runs after the daily valuation recalc
    # so any material IV change gets picked up on the same evening. Honours
    # the fingerprint cache so companies whose inputs haven't moved don't
    # spend an LLM call.
    "daily-ai-analysis-refresh": {
        "task": "tasks.ai_analysis_tasks.refresh_stale_ai_analyses",
        "schedule": crontab(hour=20, minute=0),  # 8PM EAT
    },
}
