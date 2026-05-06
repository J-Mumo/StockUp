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

SYSTEM_PROMPT = """You are a financial data extraction system that reports EXACT figures from publicly filed annual reports of Nairobi Securities Exchange (NSE) listed companies in Kenya.

These companies file audited financial statements with the Capital Markets Authority (CMA) Kenya and publish annual reports on their investor relations websites. You must report the ACTUAL numbers from these filings — not estimates, not approximations, but the real reported figures.

CRITICAL RULES:
- All monetary values in KES (Kenya Shillings) as full numbers (e.g., 298500000000 for KES 298.5 billion)
- EPS and dividends per share in KES per share
- Ratios as decimals (ROE 0.25 = 25%, D/E 0.8 = 80%)
- Capital expenditures: positive number = total cash spent on PPE and intangible assets (from cash flow statement "Purchase of property, plant and equipment" + "Purchase of intangible assets")
- Operating cash flow: the EXACT "Cash generated from operations" or "Net cash from operating activities" figure from the cash flow statement
- Free cash flow = Operating cash flow - Capital expenditures (compute this yourself from the two values above)
- You MUST report the ACTUAL audited figures — NOT rounded estimates
- For Safaricom: FY2024 operating cash flow was approximately KES 97-115 billion range, CapEx approximately KES 40-50 billion. Use the exact figures you know from the annual report.
- Do NOT return null unless the company genuinely did not report that metric"""

USER_PROMPT_TEMPLATE = """I need the annual financial data for {company_name} (NSE ticker: {ticker}), a company listed on the Nairobi Securities Exchange, Kenya.

{existing_data_context}

Based on the company's ACTUAL published and audited annual reports filed with CMA Kenya, provide the EXACT reported financial figures for fiscal years {year_start} to {year_end}.

IMPORTANT: Report the EXACT values from the audited financial statements — specifically:
- Revenue: "Total revenue" or "Service revenue" from Income Statement
- Net income: "Profit for the year" from Income Statement
- Operating cash flow: "Net cash from operating activities" from Cash Flow Statement (this is typically the LARGEST cash flow figure)
- Capital expenditures: "Purchase of property, plant and equipment" + "Purchase of intangible assets" from investing activities (as positive number)
- Free cash flow: Operating cash flow minus Capital expenditures
- Total assets, total liabilities, total equity from Balance Sheet

Do NOT approximate or round. Use the actual reported numbers. For large companies like Safaricom, KCB, Equity Group — their OCF figures are typically in the KES 80-120 billion range, not KES 20-30 billion.

Return ONLY a JSON object (no markdown fences, no explanation text):
{{
  "company": "{ticker}",
  "financials": [
    {{
      "fiscal_year": 2024,
      "revenue": 354000000000,
      "net_income": 57000000000,
      "earnings_per_share": 1.42,
      "total_assets": 450000000000,
      "total_liabilities": 280000000000,
      "total_equity": 170000000000,
      "operating_cash_flow": 95000000000,
      "capital_expenditures": 35000000000,
      "free_cash_flow": 60000000000,
      "dividends_per_share": 0.65,
      "return_on_equity": 0.34,
      "debt_to_equity": 1.65,
      "shares_outstanding": 40065428000
    }}
  ]
}}

Provide one entry for EACH year from {year_start} to {year_end}. The example values above are illustrative — use the actual reported figures from {company_name}'s annual reports."""


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

def _build_existing_data_context(db: Session, company: Company, year_start: int, year_end: int) -> str:
    """Build context string showing what data we already have for the company."""
    existing = (
        db.query(FinancialStatement)
        .filter(
            FinancialStatement.company_id == company.id,
            FinancialStatement.fiscal_year >= year_start,
            FinancialStatement.fiscal_year <= year_end,
        )
        .order_by(FinancialStatement.fiscal_year.desc())
        .all()
    )

    if not existing:
        return f"We have no existing financial data for {company.name}. Please provide all available data from public annual reports."

    lines = [f"We already have some data for {company.name} from other sources. Here is what we know (fields marked null need to be filled):"]
    for fs in existing:
        parts = [f"  FY{fs.fiscal_year}:"]
        if fs.revenue:
            parts.append(f"Revenue=KES {fs.revenue:,.0f}")
        if fs.net_income:
            parts.append(f"Net Income=KES {fs.net_income:,.0f}")
        if fs.earnings_per_share:
            parts.append(f"EPS=KES {fs.earnings_per_share}")
        if fs.operating_cash_flow:
            parts.append(f"OCF=KES {fs.operating_cash_flow:,.0f}")
        if fs.free_cash_flow:
            parts.append(f"FCF=KES {fs.free_cash_flow:,.0f}")
        else:
            parts.append("FCF=MISSING")
        if fs.capital_expenditures:
            parts.append(f"CapEx=KES {fs.capital_expenditures:,.0f}")
        else:
            parts.append("CapEx=MISSING")
        if fs.total_equity:
            parts.append(f"Equity=KES {fs.total_equity:,.0f}")
        lines.append(" | ".join(parts))

    missing_years = set(range(year_start, year_end + 1)) - {fs.fiscal_year for fs in existing}
    if missing_years:
        lines.append(f"\n  Missing years entirely: {sorted(missing_years)}")

    lines.append("\nPlease provide COMPLETE data for ALL years, including the ones we already have (we will validate). Focus especially on filling in FCF, CapEx, and operating cash flow which we are missing.")
    return "\n".join(lines)


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

    # Build context from existing data to give the LLM confidence
    existing_context = _build_existing_data_context(db, company, year_start, year_end)

    prompt = USER_PROMPT_TEMPLATE.format(
        company_name=name,
        ticker=ticker,
        existing_data_context=existing_context,
        year_start=year_start,
        year_end=year_end,
    )

    logger.info(f"Requesting AI financials for {ticker} ({year_start}-{year_end})...")

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
            # Create new record from AI data — but only if it has actual values
            value_fields = [
                "revenue", "net_income", "earnings_per_share", "total_assets",
                "total_liabilities", "total_equity", "operating_cash_flow",
                "capital_expenditures", "free_cash_flow",
            ]
            has_data = any(record.get(f) is not None for f in value_fields)
            if not has_data:
                logger.debug(f"Skipping FY{fiscal_year} - AI returned all nulls")
                continue

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
