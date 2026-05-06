"""End-to-end smoke test script for StockUp API.

Verifies all major API endpoints are operational.
Run against a live server: python -m pytest backend/tests/test_smoke.py -v

Requirements:
  - API server running at http://localhost:8000
  - Database seeded with at least one market/company
  - Redis running (for health check)

Usage:
  pytest backend/tests/test_smoke.py -v --tb=short
  # Or standalone:
  python backend/tests/test_smoke.py
"""

import os
import sys

import requests

BASE_URL = os.getenv("STOCKUP_API_URL", "http://localhost:8000")


def _url(path: str) -> str:
    return f"{BASE_URL}{path}"


def _register_and_login() -> dict:
    """Register a test user and return auth headers."""
    import time

    email = f"smoke_{int(time.time())}@test.com"
    password = "SmokeTest123!"

    # Register
    resp = requests.post(
        _url("/api/auth/register"),
        json={"email": email, "password": password, "full_name": "Smoke Test"},
    )
    if resp.status_code not in (201, 409):  # 409 = already exists
        print(f"  WARN: Register returned {resp.status_code}: {resp.text}")

    # Login
    resp = requests.post(
        _url("/api/auth/login"),
        json={"email": email, "password": password},
    )
    if resp.status_code != 200:
        print(f"  FAIL: Login returned {resp.status_code}: {resp.text}")
        return {}

    token = resp.json().get("access_token")
    return {"Authorization": f"Bearer {token}"}


def test_health():
    """Health endpoint returns 200."""
    resp = requests.get(_url("/health"))
    assert resp.status_code == 200
    data = resp.json()
    print(f"  Health: {data['status']}, DB: {data['database']}, Redis: {data['redis']}")
    assert data["status"] in ("healthy", "degraded")


def test_root():
    """Root endpoint returns app info."""
    resp = requests.get(_url("/"))
    assert resp.status_code == 200
    data = resp.json()
    assert data["app"] == "StockUp"
    assert data["status"] == "running"


def test_markets():
    """Markets endpoint returns at least NSE."""
    resp = requests.get(_url("/api/stocks/markets"))
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 1
    codes = [m["code"] for m in data]
    assert "NSE" in codes
    print(f"  Markets: {len(data)} found")


def test_companies():
    """Companies endpoint returns listed companies."""
    resp = requests.get(_url("/api/stocks/companies"))
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) >= 1
    print(f"  Companies: {len(data)} found")
    return data


def test_company_prices():
    """Company prices endpoint returns price history."""
    # Get first company
    companies = requests.get(_url("/api/stocks/companies")).json()
    if not companies:
        print("  SKIP: No companies found")
        return

    cid = companies[0]["id"]
    resp = requests.get(_url(f"/api/stocks/companies/{cid}/prices"))
    assert resp.status_code == 200
    data = resp.json()
    print(f"  Prices for company {cid}: {len(data)} records")


def test_auth_flow():
    """Register, login, and access protected endpoint."""
    headers = _register_and_login()
    assert headers, "Failed to authenticate"

    # Access a protected endpoint
    resp = requests.get(_url("/api/portfolio"), headers=headers)
    assert resp.status_code == 200
    print(f"  Auth: Login successful, portfolio access OK")
    return headers


def test_portfolio_workflow():
    """Full portfolio workflow: create, transact, check holdings."""
    headers = _register_and_login()
    if not headers:
        print("  SKIP: Auth failed")
        return

    # Create portfolio
    resp = requests.post(
        _url("/api/portfolio"),
        json={"name": "Smoke Test Portfolio", "initial_capital": 100000},
        headers=headers,
    )
    assert resp.status_code == 201
    portfolio = resp.json()
    pid = portfolio["id"]
    print(f"  Portfolio created: id={pid}")

    # Get companies to transact
    companies = requests.get(_url("/api/stocks/companies")).json()
    if not companies:
        print("  SKIP: No companies for transaction test")
        return

    cid = companies[0]["id"]

    # Record a buy
    resp = requests.post(
        _url(f"/api/portfolio/{pid}/transactions"),
        json={
            "company_id": cid,
            "transaction_type": "buy",
            "quantity": 100,
            "price_per_share": 50.0,
            "transaction_date": "2025-06-01",
        },
        headers=headers,
    )
    assert resp.status_code == 201
    print(f"  Transaction recorded: buy 100 shares")

    # Check holdings
    resp = requests.get(_url(f"/api/portfolio/{pid}/holdings"), headers=headers)
    assert resp.status_code == 200
    holdings = resp.json()
    assert len(holdings.get("holdings", [])) >= 1
    print(f"  Holdings: {len(holdings['holdings'])} positions")

    # Check performance
    resp = requests.get(_url(f"/api/portfolio/{pid}/performance"), headers=headers)
    assert resp.status_code == 200
    print(f"  Performance: OK")

    # Cleanup - delete portfolio
    resp = requests.delete(_url(f"/api/portfolio/{pid}"), headers=headers)
    assert resp.status_code == 204


def test_watchlist_workflow():
    """Create watchlist, add item, list, remove."""
    headers = _register_and_login()
    if not headers:
        print("  SKIP: Auth failed")
        return

    # Create watchlist
    resp = requests.post(
        _url("/api/watchlists"),
        json={"name": "Smoke Watchlist"},
        headers=headers,
    )
    assert resp.status_code == 201
    wl = resp.json()
    wid = wl["id"]
    print(f"  Watchlist created: id={wid}")

    # Add item
    companies = requests.get(_url("/api/stocks/companies")).json()
    if companies:
        cid = companies[0]["id"]
        resp = requests.post(
            _url(f"/api/watchlists/{wid}/items"),
            json={"company_id": cid, "notes": "Smoke test item"},
            headers=headers,
        )
        assert resp.status_code == 201
        print(f"  Watchlist item added: company_id={cid}")

    # Delete watchlist
    resp = requests.delete(_url(f"/api/watchlists/{wid}"), headers=headers)
    assert resp.status_code == 204


def test_alerts_workflow():
    """Create alert, list, delete."""
    headers = _register_and_login()
    if not headers:
        print("  SKIP: Auth failed")
        return

    companies = requests.get(_url("/api/stocks/companies")).json()
    if not companies:
        print("  SKIP: No companies for alert test")
        return

    cid = companies[0]["id"]

    # Create alert
    resp = requests.post(
        _url("/api/alerts"),
        json={
            "company_id": cid,
            "alert_type": "price_below",
            "condition": "price_below_10",
            "threshold_value": 10.0,
        },
        headers=headers,
    )
    assert resp.status_code == 201
    alert = resp.json()
    aid = alert["id"]
    print(f"  Alert created: id={aid}")

    # List
    resp = requests.get(_url("/api/alerts"), headers=headers)
    assert resp.status_code == 200
    assert len(resp.json()) >= 1

    # Delete
    resp = requests.delete(_url(f"/api/alerts/{aid}"), headers=headers)
    assert resp.status_code == 204


def test_dashboard():
    """Dashboard endpoint returns aggregated data."""
    headers = _register_and_login()
    if not headers:
        print("  SKIP: Auth failed")
        return

    resp = requests.get(_url("/api/dashboard"), headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert "portfolio" in data
    assert "alerts" in data
    assert "watchlists" in data
    assert "market_stats" in data
    print(f"  Dashboard: total_companies={data['market_stats'].get('total_companies')}")


def test_analysis_recommendation():
    """Recommendation endpoint for a company."""
    companies = requests.get(_url("/api/stocks/companies")).json()
    if not companies:
        print("  SKIP: No companies")
        return

    cid = companies[0]["id"]
    resp = requests.get(_url(f"/api/analysis/companies/{cid}/recommendation"))
    assert resp.status_code == 200
    data = resp.json()
    assert "action" in data
    assert "quality_score" in data
    print(f"  Recommendation for company {cid}: {data['action']}")


# ---------------------------------------------------------------------------
# CLI runner
# ---------------------------------------------------------------------------

def run_all():
    """Run all smoke tests and print results."""
    tests = [
        ("Health Check", test_health),
        ("Root Endpoint", test_root),
        ("Markets", test_markets),
        ("Companies", test_companies),
        ("Company Prices", test_company_prices),
        ("Auth Flow", test_auth_flow),
        ("Portfolio Workflow", test_portfolio_workflow),
        ("Watchlist Workflow", test_watchlist_workflow),
        ("Alerts Workflow", test_alerts_workflow),
        ("Dashboard", test_dashboard),
        ("Analysis Recommendation", test_analysis_recommendation),
    ]

    print(f"\n{'='*60}")
    print(f"StockUp E2E Smoke Tests — {BASE_URL}")
    print(f"{'='*60}\n")

    passed = 0
    failed = 0

    for name, test_fn in tests:
        try:
            print(f"[TEST] {name}")
            test_fn()
            print(f"  ✓ PASSED\n")
            passed += 1
        except AssertionError as e:
            print(f"  ✗ FAILED: {e}\n")
            failed += 1
        except requests.ConnectionError:
            print(f"  ✗ FAILED: Cannot connect to {BASE_URL}\n")
            failed += 1
        except Exception as e:
            print(f"  ✗ ERROR: {type(e).__name__}: {e}\n")
            failed += 1

    print(f"{'='*60}")
    print(f"Results: {passed} passed, {failed} failed, {passed + failed} total")
    print(f"{'='*60}\n")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(run_all())
