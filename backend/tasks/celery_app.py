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
# Daily schedule in EAT (UTC+3):
#   6PM EAT = 15:00 UTC — fetch prices
#   7PM EAT = 16:00 UTC — recalculate valuations
#   7:30PM EAT = 16:30 UTC — evaluate alerts
# ---------------------------------------------------------------------------

celery_app.conf.beat_schedule = {
    "daily-price-fetch": {
        "task": "tasks.price_tasks.fetch_all_prices",
        "schedule": crontab(hour=15, minute=0),  # 6PM EAT
        "options": {"queue": "default"},
    },
    "daily-valuation-recalc": {
        "task": "tasks.valuation_tasks.recalculate_all_valuations",
        "schedule": crontab(hour=16, minute=0),  # 7PM EAT
        "options": {"queue": "default"},
    },
    "daily-alert-evaluation": {
        "task": "tasks.alert_tasks.evaluate_all_alerts",
        "schedule": crontab(hour=16, minute=30),  # 7:30PM EAT
        "options": {"queue": "default"},
    },
    "monthly-financials-refresh": {
        "task": "tasks.valuation_tasks.refresh_all_financials",
        "schedule": crontab(hour=23, minute=0, day_of_month="1"),  # 1st of month, 2AM EAT (23:00 UTC prev day)
        "options": {"queue": "default"},
    },
    "monthly-annual-report-parsing": {
        "task": "tasks.valuation_tasks.parse_annual_reports",
        "schedule": crontab(hour=0, minute=0, day_of_month="5"),  # 5th of month, 3AM EAT (00:00 UTC)
        "options": {"queue": "default"},
    },
}
