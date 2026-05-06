"""Integration tests for portfolio API — transactions, holdings, and performance.

Tests the full portfolio workflow:
  1. Create portfolio
  2. Record buy/sell transactions
  3. Verify holdings with weighted average cost basis
  4. Verify performance metrics (P&L, CAGR, allocation)
"""

from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.company import Company
from app.models.market import Market
from app.models.price_history import PriceHistory
from app.models.user import User


class TestPortfolioCRUD:
    """Test portfolio creation, listing, updating, and deletion."""

    def test_create_portfolio(self, client: TestClient, auth_headers: dict):
        """Create a new portfolio."""
        resp = client.post(
            "/api/portfolio",
            json={"name": "My NSE Portfolio", "description": "Test portfolio", "initial_capital": 500000.0},
            headers=auth_headers,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "My NSE Portfolio"
        assert data["description"] == "Test portfolio"
        assert data["initial_capital"] == 500000.0
        assert data["currency"] == "KES"

    def test_list_portfolios(self, client: TestClient, auth_headers: dict):
        """List portfolios returns user's portfolios."""
        # Create two portfolios
        client.post(
            "/api/portfolio",
            json={"name": "Portfolio A"},
            headers=auth_headers,
        )
        client.post(
            "/api/portfolio",
            json={"name": "Portfolio B"},
            headers=auth_headers,
        )
        resp = client.get("/api/portfolio", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 2
        names = [p["name"] for p in data]
        assert "Portfolio A" in names
        assert "Portfolio B" in names

    def test_get_portfolio(self, client: TestClient, auth_headers: dict):
        """Get a specific portfolio by ID."""
        create_resp = client.post(
            "/api/portfolio",
            json={"name": "Detail Test"},
            headers=auth_headers,
        )
        pid = create_resp.json()["id"]
        resp = client.get(f"/api/portfolio/{pid}", headers=auth_headers)
        assert resp.status_code == 200
        assert resp.json()["name"] == "Detail Test"

    def test_update_portfolio(self, client: TestClient, auth_headers: dict):
        """Update portfolio name and description."""
        create_resp = client.post(
            "/api/portfolio",
            json={"name": "Old Name"},
            headers=auth_headers,
        )
        pid = create_resp.json()["id"]
        resp = client.put(
            f"/api/portfolio/{pid}",
            json={"name": "New Name", "description": "Updated"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "New Name"
        assert resp.json()["description"] == "Updated"

    def test_delete_portfolio(self, client: TestClient, auth_headers: dict):
        """Delete a portfolio."""
        create_resp = client.post(
            "/api/portfolio",
            json={"name": "To Delete"},
            headers=auth_headers,
        )
        pid = create_resp.json()["id"]
        resp = client.delete(f"/api/portfolio/{pid}", headers=auth_headers)
        assert resp.status_code == 204

        # Verify deleted
        resp = client.get(f"/api/portfolio/{pid}", headers=auth_headers)
        assert resp.status_code == 404

    def test_get_nonexistent_portfolio_returns_404(self, client: TestClient, auth_headers: dict):
        """Getting a non-existent portfolio returns 404."""
        resp = client.get("/api/portfolio/99999", headers=auth_headers)
        assert resp.status_code == 404


class TestTransactions:
    """Test recording buy/sell transactions."""

    def test_buy_transaction(self, client: TestClient, auth_headers: dict, company: Company):
        """Record a buy transaction."""
        # Create portfolio
        portfolio = client.post(
            "/api/portfolio",
            json={"name": "Txn Test"},
            headers=auth_headers,
        ).json()

        resp = client.post(
            f"/api/portfolio/{portfolio['id']}/transactions",
            json={
                "company_id": company.id,
                "transaction_type": "buy",
                "quantity": 100,
                "price_per_share": 25.50,
                "transaction_date": "2025-01-15",
                "fees": 50.0,
                "notes": "Initial purchase",
            },
            headers=auth_headers,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["transaction_type"] == "buy"
        assert data["quantity"] == 100.0
        assert data["price_per_share"] == 25.50
        assert data["total_amount"] == 2550.0
        assert data["fees"] == 50.0

    def test_sell_transaction(self, client: TestClient, auth_headers: dict, company: Company):
        """Record a sell transaction after buying."""
        portfolio = client.post(
            "/api/portfolio",
            json={"name": "Sell Test"},
            headers=auth_headers,
        ).json()

        # Buy first
        client.post(
            f"/api/portfolio/{portfolio['id']}/transactions",
            json={
                "company_id": company.id,
                "transaction_type": "buy",
                "quantity": 200,
                "price_per_share": 20.00,
                "transaction_date": "2025-01-10",
            },
            headers=auth_headers,
        )

        # Then sell part
        resp = client.post(
            f"/api/portfolio/{portfolio['id']}/transactions",
            json={
                "company_id": company.id,
                "transaction_type": "sell",
                "quantity": 50,
                "price_per_share": 30.00,
                "transaction_date": "2025-02-15",
            },
            headers=auth_headers,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["transaction_type"] == "sell"
        assert data["quantity"] == 50.0
        assert data["total_amount"] == 1500.0

    def test_sell_more_than_held_fails(self, client: TestClient, auth_headers: dict, company: Company):
        """Cannot sell more shares than currently held."""
        portfolio = client.post(
            "/api/portfolio",
            json={"name": "Oversell Test"},
            headers=auth_headers,
        ).json()

        # Buy 50 shares
        client.post(
            f"/api/portfolio/{portfolio['id']}/transactions",
            json={
                "company_id": company.id,
                "transaction_type": "buy",
                "quantity": 50,
                "price_per_share": 10.00,
                "transaction_date": "2025-01-10",
            },
            headers=auth_headers,
        )

        # Try to sell 100
        resp = client.post(
            f"/api/portfolio/{portfolio['id']}/transactions",
            json={
                "company_id": company.id,
                "transaction_type": "sell",
                "quantity": 100,
                "price_per_share": 15.00,
                "transaction_date": "2025-02-10",
            },
            headers=auth_headers,
        )
        assert resp.status_code == 400

    def test_list_transactions(self, client: TestClient, auth_headers: dict, company: Company):
        """List transactions for a portfolio."""
        portfolio = client.post(
            "/api/portfolio",
            json={"name": "List Txn Test"},
            headers=auth_headers,
        ).json()

        # Add two transactions
        client.post(
            f"/api/portfolio/{portfolio['id']}/transactions",
            json={
                "company_id": company.id,
                "transaction_type": "buy",
                "quantity": 100,
                "price_per_share": 20.00,
                "transaction_date": "2025-01-10",
            },
            headers=auth_headers,
        )
        client.post(
            f"/api/portfolio/{portfolio['id']}/transactions",
            json={
                "company_id": company.id,
                "transaction_type": "buy",
                "quantity": 50,
                "price_per_share": 22.00,
                "transaction_date": "2025-02-10",
            },
            headers=auth_headers,
        )

        resp = client.get(
            f"/api/portfolio/{portfolio['id']}/transactions",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2


class TestHoldings:
    """Test holdings calculation with weighted average cost basis."""

    def test_holdings_after_single_buy(
        self, client: TestClient, auth_headers: dict, company: Company, db: Session
    ):
        """Holdings show correct cost basis after one buy."""
        portfolio = client.post(
            "/api/portfolio",
            json={"name": "Holdings Test"},
            headers=auth_headers,
        ).json()

        client.post(
            f"/api/portfolio/{portfolio['id']}/transactions",
            json={
                "company_id": company.id,
                "transaction_type": "buy",
                "quantity": 100,
                "price_per_share": 25.00,
                "transaction_date": "2025-01-10",
            },
            headers=auth_headers,
        )

        resp = client.get(
            f"/api/portfolio/{portfolio['id']}/holdings",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        holdings = data["holdings"]
        assert len(holdings) >= 1

        # Find our company holding
        holding = next((h for h in holdings if h["company_id"] == company.id), None)
        assert holding is not None
        assert holding["total_shares"] == 100.0
        assert holding["average_cost_basis"] == 25.00

    def test_holdings_weighted_average_after_multiple_buys(
        self, client: TestClient, auth_headers: dict, company: Company, db: Session
    ):
        """Weighted average cost basis after multiple buys at different prices."""
        portfolio = client.post(
            "/api/portfolio",
            json={"name": "WACB Test"},
            headers=auth_headers,
        ).json()

        # Buy 100 @ 20
        client.post(
            f"/api/portfolio/{portfolio['id']}/transactions",
            json={
                "company_id": company.id,
                "transaction_type": "buy",
                "quantity": 100,
                "price_per_share": 20.00,
                "transaction_date": "2025-01-10",
            },
            headers=auth_headers,
        )

        # Buy 100 @ 30
        client.post(
            f"/api/portfolio/{portfolio['id']}/transactions",
            json={
                "company_id": company.id,
                "transaction_type": "buy",
                "quantity": 100,
                "price_per_share": 30.00,
                "transaction_date": "2025-02-10",
            },
            headers=auth_headers,
        )

        resp = client.get(
            f"/api/portfolio/{portfolio['id']}/holdings",
            headers=auth_headers,
        )
        data = resp.json()
        holding = next((h for h in data["holdings"] if h["company_id"] == company.id), None)
        assert holding is not None
        assert holding["total_shares"] == 200.0
        # Weighted average: (100*20 + 100*30) / 200 = 25.00
        assert holding["average_cost_basis"] == 25.00

    def test_holdings_after_partial_sell(
        self, client: TestClient, auth_headers: dict, company: Company, db: Session
    ):
        """Holdings reflect reduced shares after a sell, cost basis unchanged."""
        portfolio = client.post(
            "/api/portfolio",
            json={"name": "Partial Sell Test"},
            headers=auth_headers,
        ).json()

        # Buy 200 @ 20
        client.post(
            f"/api/portfolio/{portfolio['id']}/transactions",
            json={
                "company_id": company.id,
                "transaction_type": "buy",
                "quantity": 200,
                "price_per_share": 20.00,
                "transaction_date": "2025-01-10",
            },
            headers=auth_headers,
        )

        # Sell 50 @ 25
        client.post(
            f"/api/portfolio/{portfolio['id']}/transactions",
            json={
                "company_id": company.id,
                "transaction_type": "sell",
                "quantity": 50,
                "price_per_share": 25.00,
                "transaction_date": "2025-02-10",
            },
            headers=auth_headers,
        )

        resp = client.get(
            f"/api/portfolio/{portfolio['id']}/holdings",
            headers=auth_headers,
        )
        data = resp.json()
        holding = next((h for h in data["holdings"] if h["company_id"] == company.id), None)
        assert holding is not None
        assert holding["total_shares"] == 150.0
        # Cost basis remains 20.00 (sell doesn't change avg cost)
        assert holding["average_cost_basis"] == 20.00

    def test_holdings_empty_after_full_sell(
        self, client: TestClient, auth_headers: dict, company: Company, db: Session
    ):
        """No holdings after selling all shares."""
        portfolio = client.post(
            "/api/portfolio",
            json={"name": "Full Sell Test"},
            headers=auth_headers,
        ).json()

        # Buy 100 @ 15
        client.post(
            f"/api/portfolio/{portfolio['id']}/transactions",
            json={
                "company_id": company.id,
                "transaction_type": "buy",
                "quantity": 100,
                "price_per_share": 15.00,
                "transaction_date": "2025-01-10",
            },
            headers=auth_headers,
        )

        # Sell all 100
        client.post(
            f"/api/portfolio/{portfolio['id']}/transactions",
            json={
                "company_id": company.id,
                "transaction_type": "sell",
                "quantity": 100,
                "price_per_share": 20.00,
                "transaction_date": "2025-02-10",
            },
            headers=auth_headers,
        )

        resp = client.get(
            f"/api/portfolio/{portfolio['id']}/holdings",
            headers=auth_headers,
        )
        data = resp.json()
        # Company should not appear in holdings (or show 0 shares)
        holding = next((h for h in data["holdings"] if h["company_id"] == company.id), None)
        assert holding is None or holding["total_shares"] == 0


class TestPerformance:
    """Test portfolio performance metrics (P&L, current value)."""

    def test_performance_with_price_gain(
        self, client: TestClient, auth_headers: dict, company: Company, db: Session
    ):
        """Performance shows unrealized gain when price increases."""
        # Set up a current price higher than cost basis
        today = date.today()
        price_record = PriceHistory(
            company_id=company.id,
            price_date=today,
            close_price=Decimal("35.00"),
        )
        db.add(price_record)
        db.flush()

        portfolio = client.post(
            "/api/portfolio",
            json={"name": "Perf Gain Test"},
            headers=auth_headers,
        ).json()

        # Buy 100 @ 25
        client.post(
            f"/api/portfolio/{portfolio['id']}/transactions",
            json={
                "company_id": company.id,
                "transaction_type": "buy",
                "quantity": 100,
                "price_per_share": 25.00,
                "transaction_date": str(today - timedelta(days=30)),
            },
            headers=auth_headers,
        )

        resp = client.get(
            f"/api/portfolio/{portfolio['id']}/performance",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        # Current value: 100 * 35 = 3500
        # Cost: 100 * 25 = 2500
        # Unrealized P&L: +1000
        assert data["total_current_value"] >= 3500.0
        assert data["total_invested"] >= 2500.0
        assert data["unrealized_pnl"] >= 1000.0

    def test_performance_with_price_loss(
        self, client: TestClient, auth_headers: dict, company: Company, db: Session
    ):
        """Performance shows unrealized loss when price decreases."""
        today = date.today()
        price_record = PriceHistory(
            company_id=company.id,
            price_date=today,
            close_price=Decimal("10.00"),
        )
        db.add(price_record)
        db.flush()

        portfolio = client.post(
            "/api/portfolio",
            json={"name": "Perf Loss Test"},
            headers=auth_headers,
        ).json()

        # Buy 100 @ 25
        client.post(
            f"/api/portfolio/{portfolio['id']}/transactions",
            json={
                "company_id": company.id,
                "transaction_type": "buy",
                "quantity": 100,
                "price_per_share": 25.00,
                "transaction_date": str(today - timedelta(days=30)),
            },
            headers=auth_headers,
        )

        resp = client.get(
            f"/api/portfolio/{portfolio['id']}/performance",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        # Current value: 100 * 10 = 1000
        # Cost: 100 * 25 = 2500
        # Unrealized P&L: -1500
        assert data["unrealized_pnl"] <= -1500.0

    def test_performance_empty_portfolio(
        self, client: TestClient, auth_headers: dict
    ):
        """Performance of empty portfolio returns zeroes."""
        portfolio = client.post(
            "/api/portfolio",
            json={"name": "Empty Perf Test"},
            headers=auth_headers,
        ).json()

        resp = client.get(
            f"/api/portfolio/{portfolio['id']}/performance",
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_invested"] == 0.0
        # Empty portfolio may return None or 0.0 for current value
        assert data["total_current_value"] in (0.0, None)


class TestDashboard:
    """Test dashboard summary endpoint."""

    def test_dashboard_returns_all_sections(self, client: TestClient, auth_headers: dict):
        """Dashboard response contains all expected sections."""
        resp = client.get("/api/dashboard", headers=auth_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "portfolio" in data
        assert "alerts" in data
        assert "watchlists" in data
        assert "top_undervalued" in data
        assert "market_stats" in data

    def test_dashboard_portfolio_summary(self, client: TestClient, auth_headers: dict):
        """Dashboard portfolio section reflects created portfolios."""
        # Create a portfolio
        client.post(
            "/api/portfolio",
            json={"name": "Dashboard Test Portfolio"},
            headers=auth_headers,
        )

        resp = client.get("/api/dashboard", headers=auth_headers)
        data = resp.json()
        assert data["portfolio"]["total_portfolios"] >= 1

    def test_dashboard_market_stats(self, client: TestClient, auth_headers: dict):
        """Dashboard market_stats contains expected fields."""
        resp = client.get("/api/dashboard", headers=auth_headers)
        data = resp.json()
        stats = data["market_stats"]
        assert "total_companies" in stats
        assert "total_price_records" in stats
        assert "companies_with_valuations" in stats

