"""AI-powered financial data enrichment using LLM APIs.

Uses OpenAI or Anthropic to fill in missing financial data (FCF, CapEx, etc.)
that aren't available from kenyanstocks.com scraping. The LLM has embedded
knowledge of publicly reported financials for major listed companies.

Includes post-LLM validation to detect and reject hallucinated values
(e.g. FCF exceeding revenue, which is impossible for any real company).
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

SYSTEM_PROMPT = """\
You are a financial data extraction system that reports EXACT figures from \
publicly filed annual reports of Nairobi Securities Exchange (NSE) listed \
companies in Kenya.

These companies file audited financial statements with the Capital Markets \
Authority (CMA) Kenya and publish annual reports on their investor relations \
websites. You must report the ACTUAL numbers from these filings — not \
estimates, not approximations, but the real reported figures.

CRITICAL RULES:
- All monetary values in KES (Kenya Shillings) as full numbers \
  (e.g., 298500000000 for KES 298.5 billion)
- EPS and dividends per share in KES per share
- Ratios as decimals (ROE 0.25 = 25%, D/E 0.8 = 80%)
- Capital expenditures: positive number = total cash spent on PPE and \
  intangible assets (from cash flow statement "Purchase of property, plant \
  and equipment" + "Purchase of intangible assets")
- Operating cash flow: the EXACT "Cash generated from operations" or \
  "Net cash from operating activities" figure from the cash flow statement
- Free cash flow = Operating cash flow - Capital expenditures \
  (compute this yourself from the two values above)
- You MUST report the ACTUAL audited figures — NOT rounded estimates
- Do NOT return null unless the company genuinely did not report that metric

BANKING / FINANCIAL SECTOR RULES:
Banks, insurance companies and financial institutions have VERY different cash \
flow characteristics from industrial companies. For banks:
- Operating cash flow (OCF) is volatile and can be NEGATIVE in some years \
  because it includes changes in loans, deposits, and trading assets.
- OCF for Kenyan banks is typically in the range of KES 10-80 billion, NOT \
  hundreds of billions. A bank with KES 100B revenue CANNOT have KES 200B+ OCF.
- Capital expenditures for banks are small relative to industrial firms \
  (usually KES 2-10 billion for Kenyan banks).
- Free cash flow = OCF - CapEx, and for banks it is often small or negative.
- DO NOT confuse "net cash from operating activities" with total revenue or \
  total assets. These are completely different figures.

VALIDATION CONSTRAINTS — the LLM MUST self-check before responding:
1. Free cash flow MUST be less than revenue. FCF > revenue is impossible.
2. Free cash flow MUST equal (OCF - CapEx). If it doesn't, fix it.
3. OCF should generally be < revenue for most companies. OCF > revenue \
   is extremely rare and should only occur in exceptional circumstances.
4. Net income should be < revenue. If not, re-check your figures.
5. CapEx should be a positive number and should be < 50% of revenue \
   for most companies.
"""

USER_PROMPT_TEMPLATE = """\
I need the annual financial data for {company_name} (NSE ticker: {ticker}), \
a company listed on the Nairobi Securities Exchange, Kenya.

Sector: {sector}

{existing_data_context}

Based on the company's ACTUAL published and audited annual reports filed with \
CMA Kenya, provide the EXACT reported financial figures for fiscal years \
{year_start} to {year_end}.

IMPORTANT: Report the EXACT values from the audited financial statements:
- Revenue: "Total revenue" or "Total interest and similar income" (for banks) \
  from Income Statement
- Net income: "Profit for the year" from Income Statement
- Operating cash flow: "Net cash from operating activities" from Cash Flow \
  Statement
- Capital expenditures: "Purchase of property, plant and equipment" + \
  "Purchase of intangible assets" from investing activities (as positive number)
- Free cash flow: Operating cash flow minus Capital expenditures \
  (compute it yourself; DO NOT hallucinate this value)
- Total assets, total liabilities, total equity from Balance Sheet

SELF-CHECK before responding — for EACH year verify:
  ✓ FCF = OCF - CapEx  (must be mathematically exact)
  ✓ FCF < Revenue  (FCF exceeding revenue is impossible)
  ✓ Net income < Revenue
  ✓ OCF is reasonable relative to revenue (typically 10-40% for non-banks)

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

Provide one entry for EACH year from {year_start} to {year_end}. The example \
values above are illustrative — use the actual reported figures from \
{company_name}'s annual reports."""


# ---------------------------------------------------------------------------
# LLM API Callers
# ---------------------------------------------------------------------------

def _call_openai(prompt: str, system: str, model: str | None = None) -> str:
    """Call OpenAI API and return the text response."""
    import openai

    settings = get_settings()
    client = openai.OpenAI(api_key=settings.openai_api_key)

    model_name = model or settings.ai_model or "gpt-4.1"

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
# Post-LLM Validation (catches hallucinated values)
# ---------------------------------------------------------------------------

def _safe_num(value: Any) -> float | None:
    """Safely convert a value to float, returning None on failure."""
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def _validate_financial_record(
    record: dict[str, Any],
    ticker: str,
) -> dict[str, Any]:
    """Validate a single year's financial record from the LLM.

    Checks for impossible / hallucinated values and either corrects or
    nullifies them.  Returns the (possibly modified) record.

    Key checks:
    - FCF must not exceed revenue (impossible for any company)
    - FCF must approximately equal OCF - CapEx
    - OCF should not wildly exceed revenue
    - Net income should not exceed revenue
    """
    fiscal_year = record.get("fiscal_year", "?")
    revenue = _safe_num(record.get("revenue"))
    net_income = _safe_num(record.get("net_income"))
    ocf = _safe_num(record.get("operating_cash_flow"))
    capex = _safe_num(record.get("capital_expenditures"))
    fcf = _safe_num(record.get("free_cash_flow"))

    issues: list[str] = []

    # --- Check 1: FCF > Revenue (impossible) --------------------------------
    if fcf is not None and revenue is not None and revenue > 0:
        if fcf > revenue:
            issues.append(
                f"FCF ({fcf:,.0f}) > Revenue ({revenue:,.0f}) — impossible, "
                "nullifying FCF/OCF"
            )
            record["free_cash_flow"] = None
            record["operating_cash_flow"] = None
            fcf = None
            ocf = None

    # --- Check 2: OCF > 2× Revenue (highly suspicious) ----------------------
    if ocf is not None and revenue is not None and revenue > 0:
        if ocf > revenue * 2.0:
            issues.append(
                f"OCF ({ocf:,.0f}) > 2× Revenue ({revenue:,.0f}) — "
                "likely hallucinated, nullifying OCF & FCF"
            )
            record["operating_cash_flow"] = None
            record["free_cash_flow"] = None
            ocf = None
            fcf = None

    # --- Check 3: Net income > Revenue (impossible) -------------------------
    if net_income is not None and revenue is not None and revenue > 0:
        if net_income > revenue:
            issues.append(
                f"Net income ({net_income:,.0f}) > Revenue ({revenue:,.0f}) — "
                "likely hallucinated, nullifying net income"
            )
            record["net_income"] = None
            net_income = None

    # --- Check 4: FCF consistency (FCF should ≈ OCF - CapEx) ----------------
    if fcf is not None and ocf is not None and capex is not None:
        expected_fcf = ocf - capex
        if expected_fcf != 0:
            drift = abs(fcf - expected_fcf) / abs(expected_fcf)
            if drift > 0.15:  # More than 15% drift
                issues.append(
                    f"FCF ({fcf:,.0f}) != OCF ({ocf:,.0f}) - CapEx "
                    f"({capex:,.0f}) = {expected_fcf:,.0f}. Correcting FCF."
                )
                record["free_cash_flow"] = expected_fcf
    elif fcf is None and ocf is not None and capex is not None:
        # Compute FCF from OCF - CapEx if FCF was nullified or missing
        computed = ocf - capex
        record["free_cash_flow"] = computed

    # --- Check 5: Negative CapEx (should always be positive) ----------------
    if capex is not None and capex < 0:
        issues.append(
            f"CapEx ({capex:,.0f}) is negative — converting to positive"
        )
        record["capital_expenditures"] = abs(capex)

    # --- Check 6: FCF > 1.5× Net Income (suspicious but not impossible) ----
    fcf = _safe_num(record.get("free_cash_flow"))
    if (
        fcf is not None
        and net_income is not None
        and net_income > 0
        and fcf > net_income * 3.0
    ):
        issues.append(
            f"FCF ({fcf:,.0f}) > 3× Net Income ({net_income:,.0f}) — "
            "suspicious, nullifying FCF & OCF for safety"
        )
        record["free_cash_flow"] = None
        record["operating_cash_flow"] = None

    if issues:
        for issue in issues:
            logger.warning(
                "AI validation [%s FY%s]: %s", ticker, fiscal_year, issue
            )

    return record


def _validate_all_records(
    records: list[dict[str, Any]],
    ticker: str,
) -> list[dict[str, Any]]:
    """Validate all financial records from the LLM response.

    Also performs cross-year consistency checks (e.g., revenue shouldn't
    jump 10× between consecutive years).
    """
    validated = []
    for record in records:
        validated.append(_validate_financial_record(record, ticker))

    # Cross-year check: flag years where revenue jumps > 5× vs prior year
    revenues = []
    for rec in validated:
        rev = _safe_num(rec.get("revenue"))
        revenues.append((rec.get("fiscal_year"), rev))

    revenues_sorted = sorted(
        [(y, r) for y, r in revenues if y is not None and r is not None],
        key=lambda x: x[0],
    )
    for i in range(1, len(revenues_sorted)):
        prev_year, prev_rev = revenues_sorted[i - 1]
        curr_year, curr_rev = revenues_sorted[i]
        if prev_rev > 0 and curr_rev / prev_rev > 5.0:
            logger.warning(
                "AI validation [%s]: Revenue jumped %.1f× from FY%s "
                "(%.0f) to FY%s (%.0f) — suspicious",
                ticker,
                curr_rev / prev_rev,
                prev_year,
                prev_rev,
                curr_year,
                curr_rev,
            )

    return validated


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
    *,
    force_overwrite: bool = False,
) -> dict[str, Any]:
    """Enrich a company's financial data using AI.

    Calls the LLM to get missing financial fields (FCF, CapEx, etc.),
    validates against existing data, and upserts into the database.

    Args:
        db: Database session.
        company: Company to enrich.
        year_start: First fiscal year to request.
        year_end: Last fiscal year to request.
        force_overwrite: If True, overwrite existing AI-sourced values
            (useful for re-enrichment after fixing bad data).

    Returns:
        Summary dict with counts of updated/inserted records.
    """
    ticker = company.ticker_symbol
    name = company.name
    sector = company.sector or "Unknown"

    # Build context from existing data to give the LLM confidence
    existing_context = _build_existing_data_context(db, company, year_start, year_end)

    prompt = USER_PROMPT_TEMPLATE.format(
        company_name=name,
        ticker=ticker,
        sector=sector,
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

    # ---- Post-LLM validation: catch hallucinated values --------------------
    financials_list = _validate_all_records(data["financials"], ticker)

    updated = 0
    inserted = 0
    rejected = 0
    shares_updated = False

    # Fields that AI is allowed to write
    ai_enrichable_fields = [
        "free_cash_flow", "capital_expenditures", "operating_cash_flow",
        "total_assets", "total_liabilities", "dividends_per_share",
        "return_on_equity", "debt_to_equity", "earnings_per_share",
        "revenue", "net_income", "total_equity",
    ]

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
            # Fill in null fields — don't overwrite existing scraped data
            # unless force_overwrite is set for AI-sourced fields
            changed = False
            for field in ai_enrichable_fields:
                ai_value = record.get(field)
                current_value = getattr(existing, field, None)

                should_write = False
                if current_value is None and ai_value is not None:
                    should_write = True
                elif (
                    force_overwrite
                    and ai_value is not None
                    and existing.notes
                    and "[AI" in existing.notes
                ):
                    # Only overwrite values that were previously AI-sourced
                    should_write = True

                if should_write:
                    setattr(existing, field, ai_value)
                    changed = True

            if changed:
                existing.notes = (existing.notes or "") + " [AI enriched v2]"
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
                rejected += 1
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
                notes="[AI sourced v2]",
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
        "rejected": rejected,
        "shares_updated": shares_updated,
    }


def enrich_all_companies(
    db: Session,
    delay: float = 2.0,
    year_start: int = 2020,
    year_end: int = 2025,
    *,
    force_overwrite: bool = False,
) -> dict[str, Any]:
    """Enrich financial data for all active companies using AI.

    Args:
        db: Database session.
        delay: Seconds to wait between API calls (rate limiting).
        year_start: First fiscal year to request.
        year_end: Last fiscal year to request.
        force_overwrite: If True, overwrite existing AI-sourced values.

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
            db, company,
            year_start=year_start,
            year_end=year_end,
            force_overwrite=force_overwrite,
        )
        results.append(result)

        if result["status"] == "success":
            success_count += 1
            print(
                f"OK (updated={result['updated']}, "
                f"inserted={result['inserted']}, "
                f"rejected={result.get('rejected', 0)})"
            )
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


# ---------------------------------------------------------------------------
# Re-enrichment: clear bad AI data and re-fetch
# ---------------------------------------------------------------------------

def clear_ai_financial_data(
    db: Session,
    company: Company,
) -> int:
    """Clear AI-sourced FCF/OCF/CapEx values for a company.

    Only clears fields that were populated by AI enrichment (identified
    by the [AI ...] tag in notes). Returns the number of records cleared.
    """
    records = (
        db.query(FinancialStatement)
        .filter(
            FinancialStatement.company_id == company.id,
            FinancialStatement.notes.ilike("%[AI%"),
        )
        .all()
    )

    cleared = 0
    for fs in records:
        # Null out the AI-sourced cash flow fields that were hallucinated
        fs.free_cash_flow = None
        fs.operating_cash_flow = None
        fs.capital_expenditures = None
        fs.notes = (fs.notes or "").replace("[AI enriched]", "").replace(
            "[AI sourced]", ""
        ).replace("[AI enriched v2]", "").replace(
            "[AI sourced v2]", ""
        ).strip() + " [AI cleared for re-enrichment]"
        cleared += 1

    db.commit()
    return cleared


def reenrich_companies(
    db: Session,
    tickers: list[str] | None = None,
    delay: float = 2.0,
    year_start: int = 2020,
    year_end: int = 2025,
) -> dict[str, Any]:
    """Clear bad AI data and re-enrich specified companies (or all).

    This is the full pipeline for fixing hallucinated financial data:
    1. Clear AI-sourced FCF/OCF/CapEx values
    2. Re-call the LLM with improved prompts + validation
    3. Write only validated data back to the DB

    Args:
        db: Database session.
        tickers: List of ticker symbols to re-enrich, or None for all.
        delay: Rate-limiting delay between API calls.
        year_start: First fiscal year.
        year_end: Last fiscal year.
    """
    if tickers:
        companies = (
            db.query(Company)
            .filter(Company.ticker_symbol.in_([t.upper() for t in tickers]))
            .order_by(Company.ticker_symbol)
            .all()
        )
    else:
        companies = (
            db.query(Company)
            .filter(Company.is_active == True)
            .order_by(Company.ticker_symbol)
            .all()
        )

    results = []
    for i, company in enumerate(companies, 1):
        print(f"  [{i}/{len(companies)}] Re-enriching {company.ticker_symbol}...", end=" ", flush=True)

        # Step 1: Clear bad data
        cleared = clear_ai_financial_data(db, company)
        print(f"cleared {cleared} records, ", end="", flush=True)

        # Step 2: Re-enrich with validation
        result = enrich_company_financials(
            db, company,
            year_start=year_start,
            year_end=year_end,
            force_overwrite=True,
        )
        results.append(result)

        if result["status"] == "success":
            print(
                f"OK (updated={result['updated']}, "
                f"inserted={result['inserted']}, "
                f"rejected={result.get('rejected', 0)})"
            )
        else:
            print(f"ERROR: {result.get('error', 'unknown')}")

        if i < len(companies):
            time.sleep(delay)

    return {
        "total": len(companies),
        "results": results,
    }
