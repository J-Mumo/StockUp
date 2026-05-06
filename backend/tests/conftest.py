"""Pytest configuration and shared fixtures for StockUp tests.

Uses the main stockup database with transaction rollback per test for isolation.
No data is persisted — each test runs inside a transaction that is rolled back.

The key pattern: we start a real transaction on a raw connection, bind the
session to that connection, and after the test we rollback the transaction.
This ensures test data never hits the actual DB even if flush() is called.

To avoid conflicts with existing data, fixtures use unique codes/tickers
(e.g., 'TEST_NSE' instead of 'NSE').
"""

import os
import pytest
from datetime import date, datetime
from typing import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, Session
from fastapi.testclient import TestClient

# Override env before importing app modules
os.environ["DATABASE_URL"] = "postgresql://stockup:stockup123@localhost:5432/stockup"
os.environ["APP_DEBUG"] = "false"
os.environ["APP_ENV"] = "testing"

from app.database import Base, get_db
from app.main import app
from app.models.market import Market
from app.models.company import Company
from app.models.price_history import PriceHistory
from app.models.financial_statement import FinancialStatement
from app.models.intrinsic_value import IntrinsicValue
from app.models.user import User
from app.utils.security import create_access_token, get_password_hash


# ---------------------------------------------------------------------------
# Database engine and session for tests
# ---------------------------------------------------------------------------

TEST_DATABASE_URL = "postgresql://stockup:stockup123@localhost:5432/stockup"

engine = create_engine(TEST_DATABASE_URL, echo=False, pool_pre_ping=True)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


# ---------------------------------------------------------------------------
# Function-scoped: transaction rollback per test using SAVEPOINT
# ---------------------------------------------------------------------------

@pytest.fixture()
def db() -> Generator[Session, None, None]:
    """Provide a transactional database session that rolls back after each test.
    
    Uses the nested transaction (SAVEPOINT) pattern:
    1. Begin a real transaction on the connection
    2. Create session bound to that connection
    3. Any session.commit() becomes a SAVEPOINT (not a real commit)
    4. After test, rollback the outer transaction — undoing everything
    """
    connection = engine.connect()
    transaction = connection.begin()
    session = TestingSessionLocal(bind=connection)

    # Make session.commit() use SAVEPOINTs instead of real commits
    # This way flush() and commit() work normally in test code
    # but nothing actually hits the DB permanently
    nested = connection.begin_nested()

    @event.listens_for(session, "after_transaction_end")
    def end_savepoint(session, transaction):
        nonlocal nested
        if not nested.is_active:
            nested = connection.begin_nested()

    yield session

    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture()
def client(db: Session) -> Generator[TestClient, None, None]:
    """FastAPI test client with DB session override."""

    def _override_get_db():
        yield db

    app.dependency_overrides[get_db] = _override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Data fixtures — use unique test data to avoid conflicts with production
# ---------------------------------------------------------------------------

@pytest.fixture()
def market(db: Session) -> Market:
    """Create a test market."""
    m = Market(
        name="Test Securities Exchange",
        code="TNSE",
        country="Testland",
        currency="TST",
        is_active=True,
    )
    db.add(m)
    db.flush()
    return m


@pytest.fixture()
def company(db: Session, market: Market) -> Company:
    """Create a test company."""
    c = Company(
        market_id=market.id,
        name="Test Telco PLC",
        ticker_symbol="TTEL",
        yfinance_ticker="TTEL.NR",
        sector="Telecommunications",
        industry="Telecom Services",
        description="Test telco company",
        is_active=True,
        shares_outstanding=40_000_000,
    )
    db.add(c)
    db.flush()
    return c


@pytest.fixture()
def company2(db: Session, market: Market) -> Company:
    """Create a second test company."""
    c = Company(
        market_id=market.id,
        name="Test Bank Holdings",
        ticker_symbol="TBNK",
        yfinance_ticker="TBNK.NR",
        sector="Banking",
        industry="Commercial Banks",
        is_active=True,
        shares_outstanding=3_000_000,
    )
    db.add(c)
    db.flush()
    return c


@pytest.fixture()
def prices(db: Session, company: Company) -> list[PriceHistory]:
    """Create sample price records for the test company."""
    records = []
    base_prices = [
        (date(2026, 4, 28), 42.50, 500000, -1.2),
        (date(2026, 4, 29), 43.00, 600000, 1.18),
        (date(2026, 4, 30), 42.75, 450000, -0.58),
        (date(2026, 5, 1), 43.25, 700000, 1.17),
        (date(2026, 5, 2), 43.50, 550000, 0.58),
    ]
    for price_date, close, volume, change_pct in base_prices:
        p = PriceHistory(
            company_id=company.id,
            price_date=price_date,
            close_price=close,
            volume=volume,
            change_percent=change_pct,
            source="test",
            fetched_at=datetime.utcnow(),
        )
        db.add(p)
        records.append(p)
    db.flush()
    return records


@pytest.fixture()
def financial(db: Session, company: Company, user: User) -> FinancialStatement:
    """Create a sample financial statement."""
    f = FinancialStatement(
        company_id=company.id,
        fiscal_year=2025,
        period_type="annual",
        revenue=300_000_000_000,
        net_income=75_000_000_000,
        earnings_per_share=1.87,
        total_assets=500_000_000_000,
        total_liabilities=200_000_000_000,
        total_equity=300_000_000_000,
        book_value_per_share=7.49,
        free_cash_flow=50_000_000_000,
        return_on_equity=0.25,
        debt_to_equity=0.67,
        entered_by_user_id=user.id,
    )
    db.add(f)
    db.flush()
    return f


@pytest.fixture()
def user(db: Session) -> User:
    """Create a test user."""
    u = User(
        email="testuser_fixture@stockup.test",
        hashed_password=get_password_hash("TestPass123!"),
        first_name="Test",
        last_name="User",
        is_active=True,
    )
    db.add(u)
    db.flush()
    return u


@pytest.fixture()
def auth_headers(user: User) -> dict:
    """Generate Authorization headers with a valid JWT for the test user."""
    token = create_access_token(data={"sub": str(user.id)})
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def valuation(db: Session, company: Company) -> IntrinsicValue:
    """Create a sample valuation record."""
    v = IntrinsicValue(
        company_id=company.id,
        valuation_date=date(2026, 5, 1),
        dcf_value=55.0,
        epv_value=48.0,
        book_value_estimate=35.0,
        weighted_intrinsic_value=49.5,
        current_market_price=43.25,
        margin_of_safety_pct=12.6,
        recommendation="Accumulate",
        recommendation_reason="Fairly valued with high ROE",
        assumptions={"discount_rate": 0.12, "growth_rate": 0.03},
        calculation_details={"dcf_years": 10},
        calculated_at=datetime.utcnow(),
    )
    db.add(v)
    db.flush()
    return v
