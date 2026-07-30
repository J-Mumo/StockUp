"""StockUp - Main FastAPI application entrypoint."""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.routers import auth, stocks, alerts, analysis, portfolio, watchlists, dashboard, notes, company_chat, goals

settings = get_settings()

# Configure logging
logging.basicConfig(
    level=logging.DEBUG if settings.app_debug else logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events."""
    logger.info(f"Starting {settings.app_name} in {settings.app_env} mode")
    yield
    logger.info(f"Shutting down {settings.app_name}")


app = FastAPI(
    title=settings.app_name,
    description="Buffett-style stock analysis and tracking platform for the Kenyan market",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:3000"],  # React dev servers
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(auth.router)
app.include_router(stocks.router)
app.include_router(alerts.router)
app.include_router(analysis.router)
app.include_router(portfolio.router)
app.include_router(watchlists.router)
app.include_router(dashboard.router)
app.include_router(notes.router)
app.include_router(company_chat.router)
app.include_router(goals.router)


@app.get("/", tags=["health"])
def root():
    """Root endpoint."""
    return {
        "app": settings.app_name,
        "version": "0.1.0",
        "status": "running",
    }


@app.get("/health", tags=["health"])
def health_check():
    """Health check endpoint - verifies DB and Redis connectivity."""
    from sqlalchemy import text
    from app.database import SessionLocal

    # Check database
    db_status = "ok"
    try:
        db = SessionLocal()
        db.execute(text("SELECT 1"))
        db.close()
    except Exception as e:
        db_status = f"error: {str(e)}"

    # Check Redis
    redis_status = "ok"
    try:
        import redis as redis_lib
        r = redis_lib.from_url(settings.redis_url)
        r.ping()
        r.close()
    except Exception as e:
        redis_status = f"error: {str(e)}"

    return {
        "status": "healthy" if db_status == "ok" and redis_status == "ok" else "degraded",
        "database": db_status,
        "redis": redis_status,
    }


@app.get("/health/data", tags=["health"])
def data_freshness_check(max_business_days_stale: int = 3):
    """Fails (HTTP 503) when the latest price_history row is older than
    max_business_days_stale business days. Point an uptime monitor at this
    to catch silent scraper regressions (like the kwayisi outage that went
    unnoticed for 3 weeks)."""
    from datetime import date, timedelta
    from fastapi.responses import JSONResponse
    from sqlalchemy import text
    from app.database import SessionLocal

    db = SessionLocal()
    try:
        latest = db.execute(text("SELECT MAX(price_date) FROM price_history")).scalar()
    finally:
        db.close()

    today = date.today()
    if latest is None:
        return JSONResponse(
            status_code=503,
            content={
                "status": "stale",
                "latest_price_date": None,
                "reason": "price_history table is empty",
            },
        )

    # Count business days (Mon-Fri) between latest and today, exclusive of latest.
    business_days = 0
    cursor = latest + timedelta(days=1)
    while cursor <= today:
        if cursor.weekday() < 5:
            business_days += 1
        cursor += timedelta(days=1)

    fresh = business_days <= max_business_days_stale
    payload = {
        "status": "fresh" if fresh else "stale",
        "latest_price_date": latest.isoformat(),
        "business_days_stale": business_days,
        "threshold_business_days": max_business_days_stale,
    }
    return payload if fresh else JSONResponse(status_code=503, content=payload)
