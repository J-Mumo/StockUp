"""AI-powered financial data enrichment using LLM APIs.

Uses OpenAI or Anthropic to fill in missing financial data (FCF, CapEx, etc.)
that aren't available from kenyanstocks.com scraping. The LLM has embedded
knowledge of publicly reported financials for major listed companies.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.company import Company
from app.models.financial_statement import FinancialStatement

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Prompt Template
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are a financial data analyst specializing in Nairobi Securities Exchange (NSE) listed companies in Kenya. You have deep knowledge of publicly reported financials from annual reports, investor relations pages, and regulatory filings.

Your task is to provide accurate, structured financial data for the requested company. All monetary values must be in KES (Kenya Shillings) as raw numbers (not in millions/billions - use full amounts like 44500000000 for 44.5 billion).

IMPORTANT:
- Only provide data you are confident about from public sources
- If you're uncertain about a value, set it to null
- Revenue, net income, cash flow values should be full absolute KES amounts
- Ratios (ROE, D/E) should be decimals (e.g., 0.25 for 25%)
- EPS and BVPS should be per-share values in KES
- Capital expenditures should be reported as a positive number (absolute value of cash spent)
- Free cash flow = Operating cash flow - Capital expenditures"""

USER_PROMPT_TEMPLATE = """Provide the annual financial data for {company_name} (NSE ticker: {ticker}) listed on the Nairobi Securities Exchange for fiscal years {years}.

Return ONLY a JSON object with this exact structure (no markdown, no explanation):
{{
  "company": "{ticker}",
  "financials": [
    {{
      "fiscal_year": 2025,
      "revenue": <number or null>,
      "net_income": <number or null>,
      "earnings_per_share": <number or null>,
      "total_assets": <number or null>,
      "total_liabilities": <number or null>,
      "total_equity": <number or null>,
      "operating_cash_flow": <number or null>,
      "capital_expenditures": <number or null>,
      "free_cash_flow": <number or null>,
      "dividends_per_share": <number or null>,
      "return_on_equity": <number or null>,
      "debt_to_equity": <number or null>,
      "shares_outstanding": <number or null>
    }}
  ]
}}

Provide data for each year from {year_start} to {year_end}. Use null for any values you're not confident about."""


# ---------------------------------------------------------------------------
# LLM API Callers
# ---------------------------------------------------------------------------

def _call_openai(prompt: str, system: str, model: str | None = None) -> str:
    """Call OpenAI API and return the text response."""
    import openai

    settings = get_settings()
    client = openai.OpenAI(api_key=settings.openai_api_key)

    model_name = model or settings.ai_model or "gpt-4o"

    response = client.chat.completions.create(
        model=model_name,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        temperature=0.1,  # Low temperature for factual data
        max_tokens=4000,
    )
    return response.choices[0].message.content.strip()


def _call_anthropic(prompt: str, system: str, model: str | None = None) -> str:
    """Call Anthropic API and return the text response."""
    import anthropic

    settings = get_settings()
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    model_name = model or settings.ai_model or "claude-sonnet-4-20250514"

    response = client.messages.create(
        model=model_name,
        max_tokens=4000,
        system=system,
        messages=[
            {"role": "user", "content": prompt},
        ],
        temperature=0.1,
    )
    return response.content[0].text.strip()


def _call_llm(prompt: str, system: str) -> str:
    """Call the configured LLM provider."""
    settings = get_settings()
    provider = settings.ai_provider.lower()

    if provider == "openai":
        if not settings.openai_api_key:
            raise ValueError("OPENAI_API_KEY not configured in .env")
        return _call_openai(prompt, system)
    elif provider == "anthropic":
        if not settings.anthropic_api_key:
            raise ValueError("ANTHROPIC_API_KEY not configured in .env")
        return _call_anthropic(prompt, system)
    else:
        raise ValueError(f"Unknown AI provider: {provider}. Use 'openai' or 'anthropic'.")


# ---------------------------------------------------------------------------
# Response Parsing
# ---------------------------------------------------------------------------

def _parse_response(response_text: str) -> dict[str, Any] | None:
    """Parse the LLM response into structured data."""
    # Strip potential markdown code fences
    text = response_text.strip()
    if text.startswith("```"):
        # Remove first line (```json) and last line (```)
        lines = text.split("\n")
        text = "\n".join(lines[1:-1])

    try:
        data = json.loads(text)
        return data
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse LLM response as JSON: {e}")
        logger.debug(f"Raw response: {response_text[:500]}")
        return None


# ---------------------------------------------------------------------------
# Enrichment Logic
# ---------------------------------------------------------------------------

def enrich_company_financials(
    db: Session,
    company: Company,
    year_start: int = 2020,
    year_end: int = 2025,
) -> dict[str, Any]:
    """Enrich a company's financial data using AI.

    Calls the LLM to get missing financial fields (FCF, CapEx, etc.),
    validates against existing data, and upserts into the database.

    Returns:
        Summary dict with counts of updated/inserted records.
    """
    ticker = company.ticker_symbol
    name = company.name

    years_str = f"{year_start}-{year_end}"
    prompt = USER_PROMPT_TEMPLATE.format(
        company_name=name,
        ticker=ticker,
        years=years_str,
        year_start=year_start,
        year_end=year_end,
    )

    logger.info(f"Requesting AI financials for {ticker} ({years_str})...")

    try:
        response_text = _call_llm(prompt, SYSTEM_PROMPT)
    except Exception as e:
        logger.error(f"LLM API call failed for {ticker}: {e}")
        return {"ticker": ticker, "status": "error", "error": str(e)}

    data = _parse_response(response_text)
    if not data or "financials" not in data:
        return {"ticker": ticker, "status": "error", "error": "Failed to parse LLM response"}

    financials_list = data["financials"]
    updated = 0
    inserted = 0
    shares_updated = False

    for record in financials_list:
        fiscal_year = record.get("fiscal_year")
        if not fiscal_year:
            continue

        # Check if we already have a record for this year
        existing = (
            db.query(FinancialStatement)
            .filter(
                FinancialStatement.company_id == company.id,
                FinancialStatement.fiscal_year == fiscal_year,
            )
            .first()
        )

        if existing:
            # Only fill in null fields — don't overwrite existing scraped data
            fields_to_enrich = [
                "free_cash_flow", "capital_expenditures", "operating_cash_flow",
                "total_assets", "total_liabilities", "dividends_per_share",
                "return_on_equity", "debt_to_equity", "earnings_per_share",
                "revenue", "net_income", "total_equity",
            ]
            changed = False
            for field in fields_to_enrich:
                ai_value = record.get(field)
                current_value = getattr(existing, field, None)
                if current_value is None and ai_value is not None:
                    setattr(existing, field, ai_value)
                    changed = True

            if changed:
                existing.notes = (existing.notes or "") + " [AI enriched]"
                updated += 1
        else:
            # Create new record from AI data
            fs = FinancialStatement(
                company_id=company.id,
                fiscal_year=fiscal_year,
                period_type="annual",
                revenue=record.get("revenue"),
                net_income=record.get("net_income"),
                earnings_per_share=record.get("earnings_per_share"),
                total_assets=record.get("total_assets"),
                total_liabilities=record.get("total_liabilities"),
                total_equity=record.get("total_equity"),
                operating_cash_flow=record.get("operating_cash_flow"),
                capital_expenditures=record.get("capital_expenditures"),
                free_cash_flow=record.get("free_cash_flow"),
                dividends_per_share=record.get("dividends_per_share"),
                return_on_equity=record.get("return_on_equity"),
                debt_to_equity=record.get("debt_to_equity"),
                notes="[AI sourced]",
            )
            db.add(fs)
            inserted += 1

        # Update shares_outstanding if provided and company doesn't have it
        shares = record.get("shares_outstanding")
        if shares and not company.shares_outstanding:
            company.shares_outstanding = int(shares)
            shares_updated = True

    db.commit()

    return {
        "ticker": ticker,
        "status": "success",
        "updated": updated,
        "inserted": inserted,
        "shares_updated": shares_updated,
    }


def enrich_all_companies(
    db: Session,
    delay: float = 2.0,
    year_start: int = 2020,
    year_end: int = 2025,
) -> dict[str, Any]:
    """Enrich financial data for all active companies using AI.

    Args:
        db: Database session.
        delay: Seconds to wait between API calls (rate limiting).
        year_start: First fiscal year to request.
        year_end: Last fiscal year to request.

    Returns:
        Summary dict with overall statistics.
    """
    companies = (
        db.query(Company)
        .filter(Company.is_active == True)
        .order_by(Company.ticker_symbol)
        .all()
    )

    results = []
    success_count = 0
    error_count = 0

    for i, company in enumerate(companies, 1):
        logger.info(f"[{i}/{len(companies)}] Enriching {company.ticker_symbol}...")
        print(f"  [{i}/{len(companies)}] {company.ticker_symbol}...", end=" ", flush=True)

        result = enrich_company_financials(
            db, company, year_start=year_start, year_end=year_end
        )
        results.append(result)

        if result["status"] == "success":
            success_count += 1
            print(f"OK (updated={result['updated']}, inserted={result['inserted']})")
        else:
            error_count += 1
            print(f"ERROR: {result.get('error', 'unknown')}")

        # Rate limiting between calls
        if i < len(companies):
            time.sleep(delay)

    return {
        "total": len(companies),
        "success": success_count,
        "errors": error_count,
        "results": results,
    }
