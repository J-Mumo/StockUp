"""Annual Report PDF Parser — extracts financial data from audited annual reports.

Uses OpenAI GPT-4.1 to read uploaded PDF annual reports and extract structured
financial statement data (income statement, balance sheet, cash flow statement).
Includes post-extraction validation and database upsert logic.

This is the highest-fidelity data source in StockUp, as it reads actual audited
reports rather than relying on scraped websites or LLM memory.
"""

from __future__ import annotations

import base64
import json
import logging
import time
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.config import get_settings
from app.data.ai_enrichment import _validate_financial_record, _safe_num
from app.data.pdf_downloader import download_annual_report, list_cached_reports
from app.models.company import Company
from app.models.financial_statement import FinancialStatement

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Extraction Prompt
# ---------------------------------------------------------------------------

EXTRACTION_SYSTEM_PROMPT = """\
You are a financial data extraction system. You are reading an AUDITED annual \
report PDF for a company listed on the Nairobi Securities Exchange (NSE), Kenya.

Your task is to extract EXACT figures from the AUDITED consolidated financial \
statements (not management commentary, not estimates, not projections).

RULES:
- Extract ONLY from the audited financial statements sections
- All monetary values in KES (Kenya Shillings) as FULL numbers \
  (e.g., 298500000000 for KES 298.5 billion)
- EPS and DPS in KES per share
- Ratios as decimals (ROE 0.25 = 25%)
- Capital expenditures as POSITIVE number
- Free cash flow = Operating cash flow - Capital expenditures
- If a figure is genuinely not present in the PDF, return null
- Do NOT estimate or approximate — only report exact figures you can see
- Report the fiscal year as shown in the report header
"""

EXTRACTION_USER_PROMPT = """\
Extract the following financial data for {company_name} (NSE: {ticker}) \
from this annual report for fiscal year {fiscal_year}.

FROM THE CONSOLIDATED STATEMENT OF COMPREHENSIVE INCOME / INCOME STATEMENT:
- Total revenue (or "Total interest and similar income" for banks)
- Profit for the year attributable to shareholders (net income)
- Basic earnings per share

FROM THE CONSOLIDATED STATEMENT OF FINANCIAL POSITION / BALANCE SHEET:
- Total assets
- Total liabilities
- Total equity attributable to shareholders
- Number of shares outstanding (from notes or face of balance sheet)

FROM THE CONSOLIDATED STATEMENT OF CASH FLOWS:
- Net cash from / (used in) operating activities
- Purchase of property, plant and equipment (as POSITIVE number)
- Free cash flow = operating cash flow minus capital expenditures

FROM NOTES OR SUPPLEMENTARY DATA:
- Dividends per share declared or paid during the year
- Return on equity (compute: net income / total equity if not stated)
- Debt to equity ratio (compute: total liabilities / total equity if not stated)

Return ONLY a JSON object (no markdown, no explanation):
{{
  "company": "{ticker}",
  "fiscal_year": {fiscal_year},
  "revenue": null,
  "net_income": null,
  "earnings_per_share": null,
  "total_assets": null,
  "total_liabilities": null,
  "total_equity": null,
  "operating_cash_flow": null,
  "capital_expenditures": null,
  "free_cash_flow": null,
  "dividends_per_share": null,
  "return_on_equity": null,
  "debt_to_equity": null,
  "shares_outstanding": null,
  "source_pages": "e.g., Income Statement p.45, Cash Flow p.48"
}}
"""


# ---------------------------------------------------------------------------
# OpenAI PDF Extraction
# ---------------------------------------------------------------------------

def _extract_financials_from_pdf(
    pdf_path: str,
    ticker: str,
    company_name: str,
    fiscal_year: int,
) -> dict[str, Any] | None:
    """Upload a PDF to OpenAI and extract financial data.

    Uses the chat completions API with the PDF encoded as base64 in an
    image_url-style content block (OpenAI supports PDFs this way in
    gpt-4.1 and later models).

    Returns parsed dict or None on failure.
    """
    import openai

    settings = get_settings()
    if not settings.openai_api_key:
        logger.error("OPENAI_API_KEY not configured")
        return None

    client = openai.OpenAI(api_key=settings.openai_api_key)

    # Read and encode PDF as base64
    pdf_file = Path(pdf_path)
    if not pdf_file.exists():
        logger.error("PDF file not found: %s", pdf_path)
        return None

    file_size_mb = pdf_file.stat().st_size / (1024 * 1024)
    if file_size_mb > settings.pdf_max_size_mb:
        logger.error(
            "PDF too large (%.1fMB > %dMB limit): %s",
            file_size_mb,
            settings.pdf_max_size_mb,
            pdf_path,
        )
        return None

    logger.info(
        "Extracting financials from PDF: %s (%.1fMB) for %s FY%d",
        pdf_path,
        file_size_mb,
        ticker,
        fiscal_year,
    )

    # Encode PDF as base64 for the API
    pdf_bytes = pdf_file.read_bytes()
    pdf_b64 = base64.standard_b64encode(pdf_bytes).decode("utf-8")

    prompt = EXTRACTION_USER_PROMPT.format(
        company_name=company_name,
        ticker=ticker,
        fiscal_year=fiscal_year,
    )

    try:
        # Use file upload approach
        file_obj = client.files.create(
            file=pdf_file.open("rb"),
            purpose="assistants",
        )

        response = client.chat.completions.create(
            model=settings.ai_model or "gpt-4.1",
            messages=[
                {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "file",
                            "file": {"file_id": file_obj.id},
                        },
                        {
                            "type": "text",
                            "text": prompt,
                        },
                    ],
                },
            ],
            temperature=0.0,
            max_tokens=2000,
        )

        # Clean up uploaded file
        try:
            client.files.delete(file_obj.id)
        except Exception:
            pass  # Non-critical

        result_text = response.choices[0].message.content.strip()
        return _parse_extraction_response(result_text, ticker, fiscal_year)

    except openai.BadRequestError:
        # Fallback: try with base64 inline if file upload isn't supported
        logger.info("File upload not supported, trying base64 inline approach")
        try:
            response = client.chat.completions.create(
                model=settings.ai_model or "gpt-4.1",
                messages=[
                    {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:application/pdf;base64,{pdf_b64}",
                                },
                            },
                            {
                                "type": "text",
                                "text": prompt,
                            },
                        ],
                    },
                ],
                temperature=0.0,
                max_tokens=2000,
            )

            result_text = response.choices[0].message.content.strip()
            return _parse_extraction_response(result_text, ticker, fiscal_year)

        except Exception as e2:
            logger.error(
                "Both PDF upload methods failed for %s FY%d: %s",
                ticker,
                fiscal_year,
                e2,
            )
            return None

    except Exception as e:
        logger.error(
            "OpenAI extraction failed for %s FY%d: %s", ticker, fiscal_year, e
        )
        return None


def _parse_extraction_response(
    text: str,
    ticker: str,
    fiscal_year: int,
) -> dict[str, Any] | None:
    """Parse the LLM extraction response into structured data.

    The model occasionally wraps JSON in markdown fences, adds JS-style
    comments, or leaves trailing commas. Be tolerant of these so a single
    formatting glitch doesn't drop an otherwise good extraction.
    """
    import re as _re

    raw = text or ""

    def _try_load(s: str) -> dict[str, Any] | None:
        try:
            return json.loads(s)
        except json.JSONDecodeError:
            return None

    # 1) Strip ```json ... ``` fences (anywhere in the string, not just at start).
    fence_match = _re.search(r"```(?:json|JSON)?\s*\n?(.*?)```", raw, flags=_re.DOTALL)
    candidate = fence_match.group(1) if fence_match else raw

    data = _try_load(candidate.strip())

    # 2) Extract the largest {...} object from the candidate.
    if data is None:
        brace_match = _re.search(r"\{.*\}", candidate, flags=_re.DOTALL)
        if brace_match:
            data = _try_load(brace_match.group(0))

    # 3) Remove JS-style line comments and trailing commas.
    if data is None and brace_match:
        cleaned = brace_match.group(0)
        cleaned = _re.sub(r"//[^\n]*", "", cleaned)
        cleaned = _re.sub(r"/\*.*?\*/", "", cleaned, flags=_re.DOTALL)
        cleaned = _re.sub(r",(\s*[}\]])", r"\1", cleaned)
        data = _try_load(cleaned)

    # 4) Evaluate trivial integer/float arithmetic that the model sometimes
    #    emits in place of a single number, e.g. ``"total_liabilities":
    #    2943683000 + 7182905000``. We only handle plus/minus between
    #    plain numeric literals to avoid arbitrary code execution.
    if data is None and brace_match:
        cleaned = brace_match.group(0)
        cleaned = _re.sub(r"//[^\n]*", "", cleaned)
        cleaned = _re.sub(r"/\*.*?\*/", "", cleaned, flags=_re.DOTALL)
        cleaned = _re.sub(r",(\s*[}\]])", r"\1", cleaned)

        def _eval_sum(m: _re.Match[str]) -> str:
            expr = m.group(0)
            try:
                total = 0.0
                # Tokenise as alternating signs and numbers.
                tokens = _re.findall(r"[+-]?\s*\d+(?:\.\d+)?", expr)
                for t in tokens:
                    total += float(t.replace(" ", ""))
                # Preserve int formatting when possible.
                if total == int(total):
                    return str(int(total))
                return repr(total)
            except Exception:
                return expr

        cleaned = _re.sub(
            r"(?<=[:\[,\s])-?\d+(?:\.\d+)?(?:\s*[+\-]\s*-?\d+(?:\.\d+)?)+",
            _eval_sum,
            cleaned,
        )
        data = _try_load(cleaned)

    if data is None:
        logger.error(
            "Failed to parse extraction response for %s FY%d after tolerant attempts",
            ticker,
            fiscal_year,
        )
        logger.warning("Raw response (first 800 chars): %s", raw[:800])
        return None

    # Ensure fiscal_year matches
    reported_year = data.get("fiscal_year")
    if reported_year and reported_year != fiscal_year:
        logger.warning(
            "Extracted year (%s) doesn't match requested year (%d) for %s",
            reported_year,
            fiscal_year,
            ticker,
        )
        data["fiscal_year"] = fiscal_year

    return data


# ---------------------------------------------------------------------------
# Validation (extends ai_enrichment validation)
# ---------------------------------------------------------------------------

def _validate_pdf_extraction(
    record: dict[str, Any],
    ticker: str,
) -> tuple[dict[str, Any], list[str]]:
    """Validate extracted financial data from PDF.

    Applies the standard AI enrichment validation plus PDF-specific checks.
    Returns (validated_record, list_of_issues).
    """
    issues: list[str] = []

    # Apply standard validation from ai_enrichment
    record = _validate_financial_record(record, ticker)

    # Additional PDF-specific checks

    # Check balance sheet equation: Assets ≈ Liabilities + Equity
    assets = _safe_num(record.get("total_assets"))
    liabilities = _safe_num(record.get("total_liabilities"))
    equity = _safe_num(record.get("total_equity"))

    if assets and liabilities and equity:
        expected_assets = liabilities + equity
        if expected_assets > 0:
            drift = abs(assets - expected_assets) / expected_assets
            if drift > 0.05:  # More than 5% off
                issues.append(
                    f"Balance sheet doesn't balance: "
                    f"Assets ({assets:,.0f}) != "
                    f"Liabilities ({liabilities:,.0f}) + "
                    f"Equity ({equity:,.0f}) = {expected_assets:,.0f} "
                    f"(drift: {drift:.1%})"
                )

    # Check FCF = OCF - CapEx exactly
    ocf = _safe_num(record.get("operating_cash_flow"))
    capex = _safe_num(record.get("capital_expenditures"))
    fcf = _safe_num(record.get("free_cash_flow"))

    if ocf is not None and capex is not None and fcf is not None:
        expected_fcf = ocf - capex
        if expected_fcf != 0:
            drift = abs(fcf - expected_fcf) / abs(expected_fcf)
            if drift > 0.02:  # More than 2% off
                issues.append(
                    f"FCF ({fcf:,.0f}) != OCF ({ocf:,.0f}) - "
                    f"CapEx ({capex:,.0f}) = {expected_fcf:,.0f}. Correcting."
                )
                record["free_cash_flow"] = expected_fcf

    # Check that we got at least some meaningful data
    key_fields = ["revenue", "net_income", "total_assets", "total_equity"]
    non_null = sum(1 for f in key_fields if record.get(f) is not None)
    if non_null < 2:
        issues.append(
            f"Too few fields extracted ({non_null}/4 key fields). "
            "PDF may not contain the financial statements."
        )

    if issues:
        for issue in issues:
            logger.warning("PDF validation [%s]: %s", ticker, issue)

    return record, issues


def _normalize_record_magnitude(
    db: Session,
    company: Company,
    record: dict[str, Any],
) -> tuple[dict[str, Any], str | None]:
    """Normalize likely unit-scale mismatches against neighbouring history.

    Some reports present values in thousands/millions and the extractor may
    miss one order-of-magnitude conversion. This helper applies a conservative
    multiplier when current monetary fields are implausibly tiny vs the
    nearest available year (preferring prior, falling back to next year so
    that ingestion order does not affect correctness).
    """
    year = record.get("fiscal_year")
    if not year:
        return record, None

    def _baseline_for(offset: int) -> FinancialStatement | None:
        return (
            db.query(FinancialStatement)
            .filter(
                FinancialStatement.company_id == company.id,
                FinancialStatement.fiscal_year == int(year) + offset,
            )
            .first()
        )

    baseline: FinancialStatement | None = None
    for offset in (-1, 1, -2, 2):
        candidate = _baseline_for(offset)
        if candidate is not None:
            baseline = candidate
            break

    if baseline is None:
        return record, None

    # Vote on a multiplier across several large monetary fields. A single
    # field can mislead (e.g., revenue line missing), but if multiple
    # large-magnitude fields all agree on the same scale gap, that is a
    # strong signal of a unit mismatch.
    comparison_fields = [
        "revenue",
        "net_income",
        "total_assets",
        "total_liabilities",
        "total_equity",
        "operating_cash_flow",
    ]

    votes: dict[int, int] = {1000: 0, 1000000: 0}
    samples = 0
    for field in comparison_fields:
        curr = _safe_num(record.get(field))
        prev = _safe_num(getattr(baseline, field, None))
        if curr is None or prev is None or prev <= 0 or curr <= 0:
            continue
        samples += 1
        ratio = prev / curr
        if 300 <= ratio <= 3000:
            votes[1000] += 1
        elif 300_000 <= ratio <= 3_000_000:
            votes[1000000] += 1

    multiplier: int | None = None
    # Require at least 2 agreeing fields (or 1 if only 1 comparable sample)
    threshold = 2 if samples >= 2 else 1
    if votes[1000000] >= threshold and votes[1000000] >= votes[1000]:
        multiplier = 1000000
    elif votes[1000] >= threshold:
        multiplier = 1000

    if not multiplier:
        return record, None

    # Apply the multiplier only to fields whose current/baseline ratio
    # individually matches the voted scale. Some LLM extractions return
    # mixed scales within a single record (e.g., revenue in millions but
    # assets already in shillings); blindly multiplying every monetary
    # field would then inflate the already-correct ones.
    monetary_fields = [
        "revenue",
        "net_income",
        "total_assets",
        "total_liabilities",
        "total_equity",
        "operating_cash_flow",
        "capital_expenditures",
        "free_cash_flow",
    ]

    if multiplier == 1000:
        lo, hi = 30, 30_000
    else:
        lo, hi = 30_000, 30_000_000

    scaled_fields: list[str] = []
    for field in monetary_fields:
        curr = _safe_num(record.get(field))
        if curr is None:
            continue
        prev = _safe_num(getattr(baseline, field, None))
        # Only scale a field when its own current/baseline ratio matches
        # the voted scale. If the baseline value for this specific field
        # is missing, leave the value alone — over-scaling an
        # already-correct field (e.g., free_cash_flow) is worse than
        # leaving one field at the wrong unit.
        if prev is None or prev <= 0:
            continue
        ratio = prev / curr if curr > 0 else (-prev / curr if curr < 0 else 0)
        if lo <= ratio <= hi:
            record[field] = curr * multiplier
            scaled_fields.append(field)

    if not scaled_fields:
        return record, None

    note = (
        f"scaled {','.join(scaled_fields)} by x{multiplier} vs "
        f"FY{baseline.fiscal_year} baseline "
        f"({votes[1000]}x1k votes, {votes[1000000]}x1M votes)"
    )
    logger.warning(
        "PDF normalization [%s FY%s]: %s",
        company.ticker_symbol,
        year,
        note,
    )
    return record, note


# ---------------------------------------------------------------------------
# Database Upsert
# ---------------------------------------------------------------------------

def _upsert_pdf_financials(
    db: Session,
    company: Company,
    record: dict[str, Any],
) -> str:
    """Write validated PDF-extracted data to the database.

    Priority rules:
    - PDF data overwrites AI-sourced data and kenyanstocks data
    - PDF data does NOT overwrite manually entered data (entered_by_user_id set)
    - Tags records with [PDF extracted] in notes

    Returns: "inserted", "updated", or "skipped"
    """
    fiscal_year = record.get("fiscal_year")
    if not fiscal_year:
        return "skipped"

    # Refuse to write rows that contain no meaningful financial data — this
    # happens when the PDF turned out to be an AGM notice, calendar, or other
    # non-annual-report document and the LLM returned all-null fields.
    key_fields = (
        "revenue", "net_income", "total_assets", "total_equity",
        "operating_cash_flow",
    )
    if not any(_safe_num(record.get(f)) for f in key_fields):
        logger.warning(
            "Skipping %s FY%d upsert: no key financial fields extracted",
            company.ticker_symbol,
            fiscal_year,
        )
        return "skipped"

    existing = (
        db.query(FinancialStatement)
        .filter(
            FinancialStatement.company_id == company.id,
            FinancialStatement.fiscal_year == fiscal_year,
        )
        .first()
    )

    fields = [
        "revenue", "net_income", "earnings_per_share",
        "total_assets", "total_liabilities", "total_equity",
        "operating_cash_flow", "capital_expenditures", "free_cash_flow",
        "dividends_per_share", "return_on_equity", "debt_to_equity",
    ]

    if existing:
        # Don't overwrite manually entered data
        if existing.entered_by_user_id:
            logger.info(
                "Skipping %s FY%d — manually entered by user %d",
                company.ticker_symbol,
                fiscal_year,
                existing.entered_by_user_id,
            )
            return "skipped"

        # Overwrite all fields with PDF data (highest quality)
        changed = False
        for field in fields:
            pdf_value = record.get(field)
            if pdf_value is not None:
                setattr(existing, field, pdf_value)
                changed = True

        if changed:
            existing.notes = f"[PDF extracted FY{fiscal_year}]"
            return "updated"
        return "skipped"

    else:
        # Check we have meaningful data before inserting
        has_data = any(record.get(f) is not None for f in fields)
        if not has_data:
            return "skipped"

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
            notes=f"[PDF extracted FY{fiscal_year}]",
        )
        db.add(fs)
        return "inserted"


# ---------------------------------------------------------------------------
# High-Level API
# ---------------------------------------------------------------------------

def parse_annual_report(
    db: Session,
    company: Company,
    fiscal_year: int,
    *,
    force_redownload: bool = False,
    skip_if_exists: bool = False,
) -> dict[str, Any]:
    """Parse a single annual report PDF and upsert financial data.

    Full pipeline: download -> extract -> validate -> upsert.

    When ``skip_if_exists`` is True, an existing FinancialStatement row
    with substantive data (any of revenue/net_income/total_assets/
    total_equity already populated) short-circuits the pipeline before
    the OpenAI call, saving an API request.

    Returns summary dict with status and details.
    """
    ticker = company.ticker_symbol
    name = company.name

    # Step 0 (optional): skip if we already have substantive data for
    # this fiscal year. Saves an OpenAI extraction call.
    if skip_if_exists:
        from app.models.financial_statement import FinancialStatement

        existing = (
            db.query(FinancialStatement)
            .filter(
                FinancialStatement.company_id == company.id,
                FinancialStatement.fiscal_year == fiscal_year,
                FinancialStatement.period_type == "annual",
            )
            .first()
        )
        if existing and any(
            getattr(existing, f, None) is not None
            for f in ("revenue", "net_income", "total_assets", "total_equity")
        ):
            return {
                "ticker": ticker,
                "fiscal_year": fiscal_year,
                "status": "skipped_existing",
            }

    # Step 1: Download PDF
    pdf_path = download_annual_report(
        ticker,
        fiscal_year,
        company_name=name,
        force_redownload=force_redownload,
    )

    if not pdf_path:
        return {
            "ticker": ticker,
            "fiscal_year": fiscal_year,
            "status": "no_pdf",
            "error": "Could not download annual report PDF",
        }

    # Step 2: Extract data from PDF via OpenAI
    extracted = _extract_financials_from_pdf(
        pdf_path, ticker, name, fiscal_year
    )

    if not extracted:
        return {
            "ticker": ticker,
            "fiscal_year": fiscal_year,
            "status": "extraction_failed",
            "error": "OpenAI could not extract data from PDF",
        }

    # Step 3: Validate
    validated, issues = _validate_pdf_extraction(extracted, ticker)

    # Step 3b: Normalize unit scale against prior-year history
    validated, scale_note = _normalize_record_magnitude(db, company, validated)
    if scale_note:
        issues.append(scale_note)

    # Step 4: Upsert to database
    action = _upsert_pdf_financials(db, company, validated)

    # Update shares_outstanding if provided
    shares = validated.get("shares_outstanding")
    if shares and not company.shares_outstanding:
        company.shares_outstanding = int(shares)

    db.commit()

    return {
        "ticker": ticker,
        "fiscal_year": fiscal_year,
        "status": "success",
        "action": action,
        "issues": issues,
        "source_pages": validated.get("source_pages", ""),
    }


def parse_company_reports(
    db: Session,
    company: Company,
    years: range = range(2020, 2026),
    *,
    delay: float = 5.0,
    force_redownload: bool = False,
) -> list[dict[str, Any]]:
    """Parse all available annual reports for a single company.

    Downloads and processes reports for each year in the range.

    Returns list of result dicts, one per year.
    """
    results = []
    for i, year in enumerate(years):
        result = parse_annual_report(
            db, company, year, force_redownload=force_redownload
        )
        results.append(result)

        status = result["status"]
        action = result.get("action", "")
        n_issues = len(result.get("issues", []))

        logger.info(
            "%s FY%d: status=%s action=%s issues=%d",
            company.ticker_symbol,
            year,
            status,
            action,
            n_issues,
        )

        # Rate limiting between API calls
        if i < len(list(years)) - 1 and status == "success":
            time.sleep(delay)

    return results


def parse_all_companies(
    db: Session,
    tickers: list[str] | None = None,
    years: range = range(2020, 2026),
    *,
    delay: float = 5.0,
    force_redownload: bool = False,
) -> dict[str, Any]:
    """Parse annual reports for all (or specified) companies.

    Args:
        db: Database session.
        tickers: Optional list of tickers to process. None = all active.
        years: Range of fiscal years to process.
        delay: Seconds between API calls (rate limiting).
        force_redownload: Redownload PDFs even if cached.

    Returns:
        Summary dict with statistics.
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

    all_results = []
    total_extracted = 0
    total_failed = 0
    total_no_pdf = 0

    for i, company in enumerate(companies, 1):
        print(
            f"  [{i}/{len(companies)}] {company.ticker_symbol} "
            f"({company.name})...",
            flush=True,
        )

        results = parse_company_reports(
            db,
            company,
            years=years,
            delay=delay,
            force_redownload=force_redownload,
        )

        for r in results:
            all_results.append(r)
            if r["status"] == "success":
                total_extracted += 1
            elif r["status"] == "no_pdf":
                total_no_pdf += 1
            else:
                total_failed += 1

        success_count = sum(1 for r in results if r["status"] == "success")
        print(
            f"    → {success_count}/{len(list(years))} years extracted",
        )

        # Small delay between companies
        if i < len(companies):
            time.sleep(1)

    return {
        "companies_processed": len(companies),
        "total_years": len(list(years)) * len(companies),
        "extracted": total_extracted,
        "no_pdf": total_no_pdf,
        "failed": total_failed,
        "results": all_results,
    }
