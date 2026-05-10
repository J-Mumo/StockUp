"""Tests for the price fetcher orchestrator.

Tests cover:
- Idempotent upsert logic (insert, update, no duplicates)
- Daily price fetch with mock scraper/yfinance
- Backfill logic with fallback
- Error handling and retry behavior
"""

from datetime import date, datetime
from unittest.mock import patch, MagicMock

import pytest
from sqlalchemy.orm import Session

from app.data.price_fetcher import (
    upsert_price,
    fetch_daily_prices,
    backfill_company_prices,
    backfill_all_prices,
)
from app.models.company import Company
from app.models.price_history import PriceHistory


class TestUpsertPrice:
    """Test the idempotent upsert_price function."""

    def test_insert_new_price(self, db: Session, company: Company):
        """Inserting a new price record should succeed."""
        price_data = {
            "price_date": date(2026, 3, 15),
            "close_price": 45.50,
            "volume": 1_000_000,
            "change_pct": 2.5,
            "source": "test",
        }

        result = upsert_price(db, company.id, price_data)
        db.flush()

        assert result is True

        # Verify it was stored
        record = (
            db.query(PriceHistory)
            .filter_by(company_id=company.id, price_date=date(2026, 3, 15))
            .first()
        )
        assert record is not None
        assert record.close_price == 45.50
        assert record.volume == 1_000_000
        assert record.change_percent == 2.5
        assert record.source == "test"

    def test_upsert_updates_existing(self, db: Session, company: Company):
        """Upserting over an existing date should update the values."""
        price_data = {
            "price_date": date(2026, 3, 15),
            "close_price": 45.50,
            "volume": 1_000_000,
            "change_pct": 2.5,
            "source": "scraper",
        }

        # First insert
        upsert_price(db, company.id, price_data)
        db.flush()

        # Second insert with different values (correction)
        updated_data = {
            "price_date": date(2026, 3, 15),
            "close_price": 46.00,
            "volume": 1_200_000,
            "change_pct": 3.6,
            "source": "csv",
        }
        result = upsert_price(db, company.id, updated_data)
        db.flush()

        assert result is True

        # Verify the record was updated, not duplicated
        records = (
            db.query(PriceHistory)
            .filter_by(company_id=company.id, price_date=date(2026, 3, 15))
            .all()
        )
        assert len(records) == 1
        assert records[0].close_price == 46.00
        assert records[0].volume == 1_200_000
        assert records[0].source == "csv"

    def test_upsert_handles_none_optional_fields(self, db: Session, company: Company):
        """Optional fields (open, high, low) can be None."""
        price_data = {
            "price_date": date(2026, 3, 16),
            "close_price": 44.00,
            "source": "scraper",
        }

        result = upsert_price(db, company.id, price_data)
        db.flush()

        assert result is True
        record = (
            db.query(PriceHistory)
            .filter_by(company_id=company.id, price_date=date(2026, 3, 16))
            .first()
        )
        assert record.open_price is None
        assert record.high_price is None
        assert record.low_price is None
        assert record.close_price == 44.00

    def test_upsert_with_full_ohlcv(self, db: Session, company: Company):
        """Full OHLCV data should be stored correctly."""
        price_data = {
            "price_date": date(2026, 3, 17),
            "open_price": 44.00,
            "high_price": 45.50,
            "low_price": 43.50,
            "close_price": 45.00,
            "volume": 2_500_000,
            "change_pct": 1.12,
            "source": "yfinance",
        }

        upsert_price(db, company.id, price_data)
        db.flush()

        record = (
            db.query(PriceHistory)
            .filter_by(company_id=company.id, price_date=date(2026, 3, 17))
            .first()
        )
        assert record.open_price == 44.00
        assert record.high_price == 45.50
        assert record.low_price == 43.50
        assert record.close_price == 45.00


class TestFetchDailyPrices:
    """Test daily price fetch with mocked data sources."""

    @patch("app.data.price_fetcher.nse_scraper")
    def test_fetch_daily_scraper_success(
        self, mock_scraper, db: Session, company: Company
    ):
        """When scraper returns data, it should be upserted."""
        mock_scraper.scrape_current_prices.return_value = [
            {
                "ticker": "TTEL",
                "price_date": date(2026, 5, 6),
                "close_price": 44.50,
                "volume": 800_000,
                "change_pct": 1.0,
                "source": "scraper",
            }
        ]

        with patch("app.data.price_fetcher.settings") as mock_settings:
            mock_settings.scraper_enabled = True
            mock_settings.yfinance_enabled = False

            stats = fetch_daily_prices(db)

        assert stats["scraped"] == 1
        assert stats["upserted"] == 1
        assert stats["failed"] == 0

    @patch("app.data.price_fetcher.nse_scraper")
    @patch("app.data.price_fetcher.yfinance_adapter")
    def test_fetch_daily_scraper_fails_uses_yfinance(
        self, mock_yf, mock_scraper, db: Session, company: Company
    ):
        """When scraper raises exception, yfinance should be used as fallback."""
        mock_scraper.scrape_current_prices.side_effect = Exception("Connection timeout")
        mock_yf.fetch_daily.return_value = {
            "price_date": date(2026, 5, 6),
            "close_price": 44.50,
            "volume": 800_000,
            "change_pct": 1.0,
            "source": "yfinance",
        }

        with patch("app.data.price_fetcher.settings") as mock_settings:
            mock_settings.scraper_enabled = True
            mock_settings.yfinance_enabled = True

            stats = fetch_daily_prices(db)

        assert stats["scraped"] == 0
        # yfinance called for all companies with yfinance_ticker set
        assert stats["yfinance"] >= 1

    @patch("app.data.price_fetcher.nse_scraper")
    def test_fetch_daily_ignores_unknown_tickers(
        self, mock_scraper, db: Session, company: Company
    ):
        """Scraped data for tickers not in our DB should be ignored."""
        mock_scraper.scrape_current_prices.return_value = [
            {
                "ticker": "UNKNOWN",
                "price_date": date(2026, 5, 6),
                "close_price": 10.0,
                "source": "scraper",
            }
        ]

        with patch("app.data.price_fetcher.settings") as mock_settings:
            mock_settings.scraper_enabled = True
            mock_settings.yfinance_enabled = False

            stats = fetch_daily_prices(db)

        assert stats["scraped"] == 0
        assert stats["upserted"] == 0


class TestBackfillCompanyPrices:
    """Test backfill for a single company."""

    @patch("app.data.price_fetcher.nse_scraper")
    def test_backfill_scraper_success(
        self, mock_scraper, db: Session, company: Company
    ):
        """Scraper returns historical prices, they get upserted."""
        mock_scraper.scrape_company_history.return_value = [
            {
                "price_date": date(2026, 4, 25),
                "close_price": 42.0,
                "volume": 300_000,
                "change_pct": -0.5,
                "source": "scraper",
            },
            {
                "price_date": date(2026, 4, 24),
                "close_price": 42.25,
                "volume": 400_000,
                "change_pct": 0.6,
                "source": "scraper",
            },
        ]

        with patch("app.data.price_fetcher.settings") as mock_settings:
            mock_settings.scraper_enabled = True
            mock_settings.yfinance_enabled = False

            stats = backfill_company_prices(db, company, delay=0)

        assert stats["source"] == "scraper"
        assert stats["upserted"] == 2
        assert stats["total"] == 2

    @patch("app.data.price_fetcher.marketscreener_adapter")
    def test_backfill_marketscreener_success(
        self, mock_marketscreener, db: Session, company: Company
    ):
        """A verified Marketscreener URL should be used before other sources."""
        company.marketscreener_graphics_url = "https://example.com/kcb/graphics/"
        mock_marketscreener.fetch_history_sync.return_value = [
            {
                "date": "2026-04-25",
                "open": 41.5,
                "high": 42.5,
                "low": 41.25,
                "close": 42.0,
                "volume": 300_000,
            },
            {
                "date": "2026-04-24",
                "open": 41.25,
                "high": 42.0,
                "low": 41.0,
                "close": 41.75,
                "volume": 250_000,
            },
        ]
        mock_marketscreener.candles_to_price_rows.return_value = [
            {
                "price_date": date(2026, 4, 25),
                "close_price": 42.0,
                "volume": 300_000,
                "source": "marketscreener",
            },
            {
                "price_date": date(2026, 4, 24),
                "close_price": 41.75,
                "volume": 250_000,
                "source": "marketscreener",
            },
        ]

        with patch("app.data.price_fetcher.settings") as mock_settings:
            mock_settings.marketscreener_enabled = True
            mock_settings.scraper_enabled = False
            mock_settings.yfinance_enabled = False

            stats = backfill_company_prices(db, company, delay=0)

        assert stats["source"] == "marketscreener"
        assert stats["upserted"] == 2
        mock_marketscreener.fetch_history_sync.assert_called_once_with(
            "https://example.com/kcb/graphics/"
        )

    @patch("app.data.price_fetcher.nse_scraper")
    @patch("app.data.price_fetcher.yfinance_adapter")
    def test_backfill_scraper_empty_falls_to_yfinance(
        self, mock_yf, mock_scraper, db: Session, company: Company
    ):
        """If scraper returns empty list, yfinance is tried next."""
        mock_scraper.scrape_company_history.return_value = []
        mock_yf.fetch_history.return_value = [
            {
                "price_date": date(2026, 4, 20),
                "close_price": 41.0,
                "volume": 500_000,
                "change_pct": 0.5,
                "source": "yfinance",
            },
        ]

        with patch("app.data.price_fetcher.settings") as mock_settings:
            mock_settings.scraper_enabled = True
            mock_settings.yfinance_enabled = True

            stats = backfill_company_prices(db, company, delay=0)

        assert stats["source"] == "yfinance"
        assert stats["upserted"] == 1

    @patch("app.data.price_fetcher.nse_scraper")
    @patch("app.data.price_fetcher.yfinance_adapter")
    def test_backfill_both_fail(
        self, mock_yf, mock_scraper, db: Session, company: Company
    ):
        """If both sources fail, returns empty stats."""
        mock_scraper.scrape_company_history.side_effect = Exception("Network error")
        mock_yf.fetch_history.return_value = []

        with patch("app.data.price_fetcher.settings") as mock_settings:
            mock_settings.scraper_enabled = True
            mock_settings.yfinance_enabled = True

            stats = backfill_company_prices(db, company, delay=0)

        assert stats["source"] == "none"
        assert stats["upserted"] == 0


class TestBackfillAllPrices:
    """Test bulk backfill across all companies."""

    @patch("app.data.price_fetcher.marketscreener_adapter")
    @patch("app.data.price_fetcher.nse_scraper")
    def test_backfill_all_iterates_companies(
        self, mock_scraper, mock_marketscreener, db: Session, company: Company, company2: Company
    ):
        """Should iterate through all active companies."""
        mock_scraper.scrape_company_history.return_value = [
            {
                "price_date": date(2026, 4, 25),
                "close_price": 42.0,
                "volume": 300_000,
                "change_pct": -0.5,
                "source": "scraper",
            },
        ]
        mock_marketscreener.fetch_history_sync.return_value = [
            {
                "date": "2026-04-25",
                "open": 42.0,
                "high": 42.0,
                "low": 42.0,
                "close": 42.0,
                "volume": 300_000,
            }
        ]
        mock_marketscreener.candles_to_price_rows.side_effect = lambda candles: [
            {
                "price_date": date.fromisoformat(candle["date"]),
                "open_price": candle["open"],
                "high_price": candle["high"],
                "low_price": candle["low"],
                "close_price": candle["close"],
                "volume": candle["volume"],
                "source": "marketscreener",
            }
            for candle in candles
        ]

        with patch("app.data.price_fetcher.settings") as mock_settings:
            mock_settings.marketscreener_enabled = True
            mock_settings.scraper_enabled = True
            mock_settings.yfinance_enabled = False

            result = backfill_all_prices(db, delay=0)

        # Includes all active companies from the DB (prod + test fixtures)
        assert result["companies"] >= 2
        # Each company gets 1 price from the mock
        assert result["total_prices"] == result["companies"]
        assert len(result["failed"]) == 0
