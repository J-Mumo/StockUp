"""Financials fetcher — retrieves company financial statements from kenyanstocks.com.

Extracts annual financial data from the Nuxt 3 SSR payload at:
    https://kenyanstocks.com/stock/nse/{TICKER}/_payload.json

The payload contains 4 years of financial analysis data including:
- Income statement: revenue, net_profit
- Balance sheet: total_assets, total_liabilities, total_equity
- Cash flow: total_cashflow
- Ratios: ROE, debt_to_equity, book_value_per_share
- Metadata: shares_issued, end_date
"""

import logging
import time
from datetime import date
from typing import Optional

import requests
from sqlalchemy.orm import Session

from app.models.company import Company
from app.models.financial_statement import FinancialStatement

logger = logging.getLogger(__name__)

BASE_URL = "https://kenyanstocks.com/stock/nse/{ticker}/_payload.json"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "application/json",
}


def _resolve(data: list, index) -> any:
    """Resolve a Nuxt payload index reference to its actual value."""
    if isinstance(index, int) and 0 <= index < len(data):
        return data[index]
    return index


def _safe_float(value) -> Optional[float]:
    """Safely convert to float."""
    if value is None:
        return None
    try:
        result = float(value)
        return result
    except (TypeError, ValueError):
        return None


def fetch_financials(ticker: str) -> list[dict]:
    """Fetch annual financial data from kenyanstocks.com payload.

    Args:
        ticker: NSE ticker symbol (e.g., 'EQTY', 'SCOM')

    Returns:
        List of dicts, one per fiscal year, with fields matching FinancialStatement.
        Empty list if data unavailable.
    """
    url = BASE_URL.format(ticker=ticker.upper())
    logger.info(f"Fetching financials from kenyanstocks.com for {ticker}")

    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        data = resp.json()

        if not isinstance(data, list) or len(data) < 10:
            logger.warning(f"Unexpected payload format for {ticker}")
            return []

        # Nuxt 3 payload navigation:
        # data[0] = {'data': 1, ...}
        # data[1] = ['ShallowReactive', 2] (pointer to cache at index 2)
        # data[2] = {'/data/web/v1/symbols/{TICKER}/nse': idx, ...}
        # data[idx] = {'status': .., 'data': main_idx, ...}
        # data[main_idx] = {'symbol': .., 'financial_analysis': fa_idx, ...}

        # Find the API response object by searching for the data path key
        cache_dict = None
        for item in data[:5]:
            if isinstance(item, dict) and any(k.startswith("/data/") for k in item):
                cache_dict = item
                break
            if isinstance(item, list) and len(item) == 2:
                # ['ShallowReactive', idx] pattern
                candidate = data[item[1]] if isinstance(item[1], int) and item[1] < len(data) else None
                if isinstance(candidate, dict) and any(k.startswith("/data/") for k in candidate):
                    cache_dict = candidate
                    break

        if not cache_dict:
            logger.warning(f"Could not find cache dict for {ticker}")
            return []

        # Find the symbols path
        symbols_key = None
        for k in cache_dict:
            if f"/symbols/{ticker.upper()}/" in k or f"/symbols/{ticker}/" in k:
                symbols_key = k
                break

        if not symbols_key:
            logger.warning(f"No symbols path found for {ticker}")
            return []

        response_idx = cache_dict[symbols_key]
        response_wrapper = data[response_idx]

        # Navigate to response.data
        if not isinstance(response_wrapper, dict) or "data" not in response_wrapper:
            logger.warning(f"No response wrapper for {ticker}")
            return []

        main_data_idx = response_wrapper["data"]
        main_data = data[main_data_idx]

        if not isinstance(main_data, dict):
            logger.warning(f"Main data is not a dict for {ticker}")
            return []

        # Check for financial_analysis key
        if "financial_analysis" not in main_data:
            logger.warning(f"No financial_analysis key for {ticker}")
            return []

        fa_idx = main_data["financial_analysis"]
        fa_list = data[fa_idx]  # Array of indices to financial analysis records

        if not isinstance(fa_list, list) or len(fa_list) == 0:
            logger.warning(f"financial_analysis is empty for {ticker}")
            return []

        results = []
        for record_idx in fa_list:
            record_template = data[record_idx]
            if not isinstance(record_template, dict):
                continue

            # Resolve each field
            record = {}
            for key, val_idx in record_template.items():
                record[key] = _resolve(data, val_idx)

            # Parse end_date to extract fiscal year
            end_date_str = record.get("end_date")
            if not end_date_str:
                continue

            try:
                end_date = date.fromisoformat(str(end_date_str))
                fiscal_year = end_date.year
            except (ValueError, TypeError):
                continue

            # Map to FinancialStatement fields
            revenue = _safe_float(record.get("revenue"))
            net_income = _safe_float(record.get("net_profit"))
            total_assets = _safe_float(record.get("total_assets"))
            total_liabilities = _safe_float(record.get("total_liabilities"))
            total_equity = _safe_float(record.get("total_equity"))
            operating_cash_flow = _safe_float(record.get("total_cashflow"))
            roe = _safe_float(record.get("roe_pct"))
            debt_to_equity = _safe_float(record.get("debt_to_equity_ratio"))
            bvps = _safe_float(record.get("bvps"))
            shares_issued = _safe_float(record.get("shares_issued"))

            # Compute EPS if possible
            eps = None
            if net_income is not None and shares_issued and shares_issued > 0:
                eps = round(net_income / shares_issued, 4)

            # Convert ROE from percentage to decimal
            roe_decimal = round(roe / 100.0, 4) if roe is not None else None

            financial = {
                "fiscal_year": fiscal_year,
                "period_type": "annual",
                "report_date": end_date,
                "revenue": revenue,
                "net_income": net_income,
                "earnings_per_share": eps,
                "total_assets": total_assets,
                "total_liabilities": total_liabilities,
                "total_equity": total_equity,
                "shareholders_equity": total_equity,
                "book_value_per_share": round(bvps, 4) if bvps is not None else None,
                "operating_cash_flow": operating_cash_flow,
                "capital_expenditures": None,  # Not available
                "free_cash_flow": None,  # Not separately available
                "dividends_per_share": None,  # Not in this data
                "return_on_equity": roe_decimal,
                "debt_to_equity": round(debt_to_equity, 4) if debt_to_equity is not None else None,
                "current_ratio": None,  # Not available
                "shares_issued": shares_issued,  # Extra, for updating company
            }

            # Only include if at least revenue or net_income is present
            if revenue is not None or net_income is not None:
                results.append(financial)

        logger.info(f"Fetched {len(results)} annual financial records for {ticker}")
        return results

    except requests.exceptions.HTTPError as e:
        if e.response is not None and e.response.status_code == 404:
            logger.warning(f"Ticker {ticker} not found on kenyanstocks.com")
        else:
            logger.error(f"HTTP error for {ticker}: {e}")
        return []
    except Exception as e:
        logger.error(f"Error fetching financials for {ticker}: {e}")
        return []


def upsert_financial(db: Session, company_id: int, data: dict) -> bool:
    """Insert or update a financial statement record.

    Uses company_id + fiscal_year + period_type as the unique key.
    Updates existing records with new data if they already exist.

    Returns:
        True if inserted/updated, False if skipped.
    """
    fiscal_year = data["fiscal_year"]
    period_type = data.get("period_type", "annual")

    existing = (
        db.query(FinancialStatement)
        .filter(
            FinancialStatement.company_id == company_id,
            FinancialStatement.fiscal_year == fiscal_year,
            FinancialStatement.period_type == period_type,
        )
        .first()
    )

    # Fields to set
    field_keys = [
        "revenue", "net_income", "earnings_per_share",
        "total_assets", "total_liabilities", "total_equity", "shareholders_equity",
        "book_value_per_share", "operating_cash_flow", "capital_expenditures",
        "free_cash_flow", "dividends_per_share", "return_on_equity",
        "debt_to_equity", "current_ratio", "report_date",
    ]

    if existing:
        # Update only fields that are None in existing but present in new data
        updated = False
        for key in field_keys:
            new_val = data.get(key)
            if new_val is not None and getattr(existing, key, None) is None:
                setattr(existing, key, new_val)
                updated = True
        if existing.notes is None:
            existing.notes = "Auto-imported from kenyanstocks.com"
            updated = True
        return updated
    else:
        # Create new record
        record = FinancialStatement(
            company_id=company_id,
            fiscal_year=fiscal_year,
            period_type=period_type,
            notes="Auto-imported from kenyanstocks.com",
        )
        for key in field_keys:
            val = data.get(key)
            if val is not None:
                setattr(record, key, val)

        db.add(record)
        return True


def backfill_company_financials(db: Session, company: Company) -> dict:
    """Fetch and upsert financial statements for a single company.

    Args:
        db: Database session.
        company: Company model instance.

    Returns:
        Dict with keys: ticker, records_fetched, records_upserted, shares_updated, error
    """
    result = {
        "ticker": company.ticker_symbol,
        "records_fetched": 0,
        "records_upserted": 0,
        "shares_updated": False,
        "error": None,
    }

    try:
        financials = fetch_financials(company.ticker_symbol)
        result["records_fetched"] = len(financials)

        if not financials:
            result["error"] = "no_data_returned"
            return result

        upserted = 0
        for record in financials:
            # Update shares_outstanding on company if not set
            shares = record.pop("shares_issued", None)
            if shares and (not company.shares_outstanding or company.shares_outstanding == 0):
                company.shares_outstanding = int(shares)
                result["shares_updated"] = True

            if upsert_financial(db, company.id, record):
                upserted += 1

        db.commit()
        result["records_upserted"] = upserted
        return result

    except Exception as e:
        db.rollback()
        result["error"] = str(e)
        logger.error(f"Failed to backfill financials for {company.ticker_symbol}: {e}")
        return result


def backfill_all_financials(db: Session, delay: float = 1.5) -> dict:
    """Fetch and upsert financial statements for all active companies.

    Args:
        db: Database session.
        delay: Seconds to wait between API calls (rate limiting).

    Returns:
        Summary dict with total stats.
    """
    companies = (
        db.query(Company)
        .filter(Company.is_active == True)
        .order_by(Company.ticker_symbol)
        .all()
    )

    summary = {
        "total_companies": len(companies),
        "success_count": 0,
        "failed_count": 0,
        "total_records_upserted": 0,
        "shares_updated_count": 0,
        "failures": [],
    }

    for i, company in enumerate(companies, 1):
        logger.info(f"[{i}/{len(companies)}] Fetching financials for {company.ticker_symbol}")

        result = backfill_company_financials(db, company)

        if result["error"]:
            summary["failed_count"] += 1
            summary["failures"].append(f"{company.ticker_symbol}: {result['error']}")
        else:
            summary["success_count"] += 1
            summary["total_records_upserted"] += result["records_upserted"]
            if result["shares_updated"]:
                summary["shares_updated_count"] += 1

        if i < len(companies):
            time.sleep(delay)

    return summary
