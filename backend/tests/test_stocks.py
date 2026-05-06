"""Tests for the stocks API endpoints.

Tests cover:
- GET /api/stocks/markets
- GET /api/stocks/markets/{id}/companies
- GET /api/stocks/companies (with search & sector filter)
- GET /api/stocks/companies/sectors
- GET /api/stocks/companies/{id}
- GET /api/stocks/companies/{id}/prices (with date filters)
- GET /api/stocks/companies/{id}/financials
- POST /api/stocks/companies/{id}/financials (auth required)
- PUT /api/stocks/companies/{id}/financials/{fid} (auth required)
- DELETE /api/stocks/companies/{id}/financials/{fid} (auth required)
- GET /api/stocks/companies/{id}/valuations
- GET /api/stocks/companies/{id}/valuations/latest
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.company import Company
from app.models.market import Market
from app.models.price_history import PriceHistory
from app.models.financial_statement import FinancialStatement
from app.models.intrinsic_value import IntrinsicValue
from app.models.user import User


class TestMarketsEndpoints:
    """Tests for market-related endpoints."""

    def test_list_markets(self, client: TestClient):
        """Markets endpoint returns list (at least the seeded NSE)."""
        response = client.get("/api/stocks/markets")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) >= 1

    def test_list_markets_with_data(self, client: TestClient, market: Market, company: Company):
        """Markets endpoint returns market with company_count."""
        response = client.get("/api/stocks/markets")
        assert response.status_code == 200
        data = response.json()
        # Find our test market in the results (prod data may also be present)
        test_markets = [m for m in data if m["code"] == "TNSE"]
        assert len(test_markets) == 1
        assert test_markets[0]["company_count"] == 1

    def test_list_market_companies(self, client: TestClient, market: Market, company: Company):
        """Companies in a specific market are returned."""
        response = client.get(f"/api/stocks/markets/{market.id}/companies")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["ticker_symbol"] == "TTEL"

    def test_list_market_companies_not_found(self, client: TestClient):
        """Non-existent market returns 404."""
        response = client.get("/api/stocks/markets/9999/companies")
        assert response.status_code == 404


class TestCompaniesEndpoints:
    """Tests for company listing and detail endpoints."""

    def test_list_companies(self, client: TestClient, company: Company, company2: Company):
        """List all companies."""
        response = client.get("/api/stocks/companies")
        assert response.status_code == 200
        data = response.json()
        # Filter to just our test companies (prod data may also be present)
        test_tickers = {c["ticker_symbol"] for c in data if c["ticker_symbol"] in ("TTEL", "TBNK")}
        assert test_tickers == {"TTEL", "TBNK"}

    def test_list_companies_filter_by_sector(
        self, client: TestClient, company: Company, company2: Company
    ):
        """Filter companies by sector."""
        response = client.get("/api/stocks/companies?sector=Banking")
        assert response.status_code == 200
        data = response.json()
        test_items = [c for c in data if c["ticker_symbol"] == "TBNK"]
        assert len(test_items) == 1

    def test_list_companies_search_by_name(
        self, client: TestClient, company: Company, company2: Company
    ):
        """Search companies by name."""
        response = client.get("/api/stocks/companies?search=Test+Telco")
        assert response.status_code == 200
        data = response.json()
        assert len(data) >= 1
        assert any(c["ticker_symbol"] == "TTEL" for c in data)

    def test_list_companies_search_by_ticker(
        self, client: TestClient, company: Company, company2: Company
    ):
        """Search companies by ticker."""
        response = client.get("/api/stocks/companies?search=TBNK")
        assert response.status_code == 200
        data = response.json()
        assert len(data) >= 1
        assert any(c["name"] == "Test Bank Holdings" for c in data)

    def test_list_sectors(self, client: TestClient, company: Company, company2: Company):
        """List unique sectors."""
        response = client.get("/api/stocks/companies/sectors")
        assert response.status_code == 200
        data = response.json()
        assert "Telecommunications" in data
        assert "Banking" in data

    def test_get_company_detail(self, client: TestClient, company: Company, prices):
        """Get company detail with latest price."""
        response = client.get(f"/api/stocks/companies/{company.id}")
        assert response.status_code == 200
        data = response.json()
        assert data["ticker_symbol"] == "TTEL"
        assert data["name"] == "Test Telco PLC"
        assert data["sector"] == "Telecommunications"
        # Latest price should be present from prices fixture
        assert data["latest_price"] is not None

    def test_get_company_detail_with_valuation(
        self, client: TestClient, company: Company, prices, valuation
    ):
        """Company detail includes latest valuation when available."""
        response = client.get(f"/api/stocks/companies/{company.id}")
        assert response.status_code == 200
        data = response.json()
        assert data["latest_valuation"] is not None
        assert data["latest_valuation"]["recommendation"] == "Accumulate"

    def test_get_company_not_found(self, client: TestClient):
        """Non-existent company returns 404."""
        response = client.get("/api/stocks/companies/9999")
        assert response.status_code == 404


class TestPricesEndpoints:
    """Tests for price history endpoints."""

    def test_get_prices(self, client: TestClient, company: Company, prices):
        """Get prices for a company (default no date filter)."""
        response = client.get(f"/api/stocks/companies/{company.id}/prices")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 5
        # Should be ordered by date desc (newest first)
        assert data[0]["price_date"] >= data[-1]["price_date"]

    def test_get_prices_with_date_filter(self, client: TestClient, company: Company, prices):
        """Filter prices by start and end date."""
        response = client.get(
            f"/api/stocks/companies/{company.id}/prices?start=2026-04-29&end=2026-05-01"
        )
        assert response.status_code == 200
        data = response.json()
        # Should include Apr 29, Apr 30, May 1
        assert len(data) == 3

    def test_get_prices_with_limit(self, client: TestClient, company: Company, prices):
        """Limit the number of price records returned."""
        response = client.get(f"/api/stocks/companies/{company.id}/prices?limit=2")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2

    def test_get_prices_company_not_found(self, client: TestClient):
        """Prices for non-existent company returns 404."""
        response = client.get("/api/stocks/companies/9999/prices")
        assert response.status_code == 404

    def test_price_record_fields(self, client: TestClient, company: Company, prices):
        """Each price record has the expected fields."""
        response = client.get(f"/api/stocks/companies/{company.id}/prices?limit=1")
        assert response.status_code == 200
        record = response.json()[0]
        assert "id" in record
        assert "price_date" in record
        assert "close_price" in record
        assert "volume" in record
        assert "change_percent" in record
        assert "source" in record


class TestFinancialsEndpoints:
    """Tests for financial statement CRUD endpoints."""

    def test_list_financials_empty(self, client: TestClient, company: Company):
        """Empty financials list for company."""
        response = client.get(f"/api/stocks/companies/{company.id}/financials")
        assert response.status_code == 200
        assert response.json() == []

    def test_list_financials_with_data(
        self, client: TestClient, company: Company, financial: FinancialStatement
    ):
        """List financials for a company with data."""
        response = client.get(f"/api/stocks/companies/{company.id}/financials")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["fiscal_year"] == 2025
        assert data[0]["revenue"] == 300_000_000_000

    def test_create_financial_requires_auth(self, client: TestClient, company: Company):
        """Creating a financial without auth returns 401."""
        payload = {"fiscal_year": 2024, "period_type": "annual", "revenue": 100_000}
        response = client.post(
            f"/api/stocks/companies/{company.id}/financials", json=payload
        )
        assert response.status_code == 401

    def test_create_financial_success(
        self, client: TestClient, company: Company, auth_headers: dict
    ):
        """Create a new financial statement."""
        payload = {
            "fiscal_year": 2024,
            "period_type": "annual",
            "revenue": 250_000_000_000,
            "net_income": 60_000_000_000,
            "earnings_per_share": 1.50,
            "return_on_equity": 0.22,
        }
        response = client.post(
            f"/api/stocks/companies/{company.id}/financials",
            json=payload,
            headers=auth_headers,
        )
        assert response.status_code == 201
        data = response.json()
        assert data["fiscal_year"] == 2024
        assert data["revenue"] == 250_000_000_000
        assert data["company_id"] == company.id

    def test_create_financial_invalid_year(
        self, client: TestClient, company: Company, auth_headers: dict
    ):
        """Invalid fiscal year should fail validation."""
        payload = {"fiscal_year": 1800, "period_type": "annual"}
        response = client.post(
            f"/api/stocks/companies/{company.id}/financials",
            json=payload,
            headers=auth_headers,
        )
        assert response.status_code == 422

    def test_update_financial(
        self,
        client: TestClient,
        company: Company,
        financial: FinancialStatement,
        auth_headers: dict,
    ):
        """Update an existing financial statement."""
        payload = {"revenue": 320_000_000_000, "notes": "Updated after audit"}
        response = client.put(
            f"/api/stocks/companies/{company.id}/financials/{financial.id}",
            json=payload,
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["revenue"] == 320_000_000_000
        assert data["notes"] == "Updated after audit"

    def test_update_financial_not_found(
        self, client: TestClient, company: Company, auth_headers: dict
    ):
        """Updating non-existent financial returns 404."""
        payload = {"revenue": 100}
        response = client.put(
            f"/api/stocks/companies/{company.id}/financials/9999",
            json=payload,
            headers=auth_headers,
        )
        assert response.status_code == 404

    def test_delete_financial(
        self,
        client: TestClient,
        company: Company,
        financial: FinancialStatement,
        auth_headers: dict,
    ):
        """Delete a financial statement."""
        response = client.delete(
            f"/api/stocks/companies/{company.id}/financials/{financial.id}",
            headers=auth_headers,
        )
        assert response.status_code == 204

    def test_delete_financial_requires_auth(
        self, client: TestClient, company: Company, financial: FinancialStatement
    ):
        """Delete without auth returns 401."""
        response = client.delete(
            f"/api/stocks/companies/{company.id}/financials/{financial.id}"
        )
        assert response.status_code == 401


class TestValuationsEndpoints:
    """Tests for valuation endpoints."""

    def test_list_valuations_empty(self, client: TestClient, company: Company):
        """Empty valuations list for company."""
        response = client.get(f"/api/stocks/companies/{company.id}/valuations")
        assert response.status_code == 200
        assert response.json() == []

    def test_list_valuations_with_data(
        self, client: TestClient, company: Company, valuation: IntrinsicValue
    ):
        """List valuations for a company."""
        response = client.get(f"/api/stocks/companies/{company.id}/valuations")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["dcf_value"] == 55.0
        assert data[0]["margin_of_safety_pct"] == 12.6

    def test_get_latest_valuation(
        self, client: TestClient, company: Company, valuation: IntrinsicValue
    ):
        """Get the latest valuation for a company."""
        response = client.get(
            f"/api/stocks/companies/{company.id}/valuations/latest"
        )
        assert response.status_code == 200
        data = response.json()
        assert data["recommendation"] == "Accumulate"
        assert data["weighted_intrinsic_value"] == 49.5
        assert data["assumptions"]["discount_rate"] == 0.12

    def test_get_latest_valuation_none(self, client: TestClient, company: Company):
        """No valuation for company returns 404."""
        response = client.get(
            f"/api/stocks/companies/{company.id}/valuations/latest"
        )
        assert response.status_code == 404

    def test_valuations_company_not_found(self, client: TestClient):
        """Valuations for non-existent company returns 404."""
        response = client.get("/api/stocks/companies/9999/valuations")
        assert response.status_code == 404
