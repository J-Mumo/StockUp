"""Cash Flow Enrichment — extracts OCF, CapEx, and calculates FCF from financial statements.

Processes downloaded PDFs to extract operating cash flow and capital expenditures,
then calculates Free Cash Flow = OCF - CapEx for quality scoring.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Optional

from sqlalchemy.orm import Session
import pdfplumber
import openai

from app.models.company import Company
from app.models.financial_statement import FinancialStatement
from app.config import get_settings

logger = logging.getLogger(__name__)


def _extract_cash_flow_from_pdf_content(pdf_path: str) -> dict:
    """Extract cash flow metrics from PDF using OpenAI.
    
    Reads PDF, extracts text focusing on Cash Flow Statement, sends to OpenAI
    for structured extraction of operating_cash_flow and capital_expenditures.
    
    Args:
        pdf_path: Path to PDF file
    
    Returns:
        Dict with keys: operating_cash_flow, capital_expenditures, source_text
    """
    result = {
        "operating_cash_flow": None,
        "capital_expenditures": None,
        "source_text": None,
        "error": None,
    }
    
    try:
        settings = get_settings()
        
        if not settings.openai_api_key:
            result["error"] = "OpenAI API key not configured"
            return result
        
        # Extract text from PDF
        with pdfplumber.open(pdf_path) as pdf:
            # Try first 10 pages for cash flow statement
            text_parts = []
            for page_num, page in enumerate(pdf.pages[:10]):
                text = page.extract_text() or ""
                if "cash flow" in text.lower() or "operating activities" in text.lower():
                    text_parts.append(text)
            
            combined_text = "\n".join(text_parts) if text_parts else pdf.pages[0].extract_text() or ""
            
            if not combined_text:
                result["error"] = "Could not extract text from PDF"
                return result
            
            result["source_text"] = combined_text[:2000]  # Store sample for debugging
            
            # Use OpenAI to extract cash flow metrics
            client = openai.OpenAI(api_key=settings.openai_api_key)
            response = client.chat.completions.create(
                model=settings.ai_model or "gpt-4.1",
                messages=[
                    {
                        "role": "system",
                        "content": """You are a financial data extraction expert. Extract cash flow metrics from annual reports.
                        
Rules:
- Extract EXACT numbers from the Cash Flow Statement section
- Operating Cash Flow (OCF): Also called "Cash flow from operations" or "Operating activities"
- Capital Expenditures: Also called "Capex" or "Purchase of property, plant and equipment"
- Return values as full numbers (e.g., 1000000 not 1M)
- All amounts in KES (Kenya Shillings)
- If a value is in millions/thousands in the document, multiply to get full number
- Return JSON with keys: operating_cash_flow, capital_expenditures, confidence (0-100), notes
- Return null for values you cannot find
- Only extract from AUDITED financial statements
                        """,
                    },
                    {
                        "role": "user",
                        "content": f"""Extract cash flow metrics from this financial statement:

{combined_text}

Return ONLY valid JSON with no additional text:
{{"operating_cash_flow": <number or null>, "capital_expenditures": <number or null>, "confidence": <0-100>, "notes": "<extraction_notes>"}}""",
                    },
                ],
                temperature=0,
            )
            
            response_text = response.choices[0].message.content
            
            # Parse JSON response
            try:
                # Try to find JSON in response
                start_idx = response_text.find("{")
                end_idx = response_text.rfind("}") + 1
                if start_idx >= 0 and end_idx > start_idx:
                    json_str = response_text[start_idx:end_idx]
                    data = json.loads(json_str)
                    
                    result["operating_cash_flow"] = data.get("operating_cash_flow")
                    result["capital_expenditures"] = data.get("capital_expenditures")
                    
                    logger.info(
                        "Extracted from PDF: OCF=%s, CapEx=%s (confidence=%s%%)",
                        result["operating_cash_flow"],
                        result["capital_expenditures"],
                        data.get("confidence", "?"),
                    )
                else:
                    result["error"] = f"Invalid JSON in response: {response_text[:200]}"
            except json.JSONDecodeError as e:
                result["error"] = f"JSON parse error: {str(e)}"
    
    except Exception as e:
        result["error"] = str(e)
        logger.error("Error extracting from PDF: %s", e)
    
    return result


def extract_cash_flow_from_cached_pdf(
    company: Company,
    fiscal_year: int,
    db: Session,
) -> dict:
    """Extract OCF and CapEx from a company's cached PDF.
    
    Looks for cached PDF at data/annual_reports/{TICKER}/{YEAR}.pdf,
    extracts via OpenAI, and updates FinancialStatement record.
    
    Args:
        company: Company model instance
        fiscal_year: Fiscal year to extract for
        db: Database session
    
    Returns:
        Dict with keys: status, ocf, capex, fcf, errors
    """
    result = {
        "status": "pending",
        "fiscal_year": fiscal_year,
        "company": company.ticker_symbol,
        "ocf": None,
        "capex": None,
        "fcf": None,
        "errors": [],
    }
    
    try:
        # Look for cached PDF
        pdf_dir = Path("data/annual_reports") / company.ticker_symbol.upper()
        pdf_path = pdf_dir / f"{fiscal_year}.pdf"
        
        if not pdf_path.exists():
            result["status"] = "pdf_not_found"
            result["errors"].append(f"PDF not found at {pdf_path}")
            return result
        
        logger.info("Extracting cash flow from %s", pdf_path)
        
        # Extract cash flow from PDF
        extraction = _extract_cash_flow_from_pdf_content(str(pdf_path))
        
        if extraction.get("error"):
            result["status"] = "extraction_error"
            result["errors"].append(extraction["error"])
            return result
        
        ocf = extraction.get("operating_cash_flow")
        capex = extraction.get("capital_expenditures")
        
        result["ocf"] = ocf
        result["capex"] = capex
        
        # Fetch or create financial statement record
        stmt = db.query(FinancialStatement).filter(
            FinancialStatement.company_id == company.id,
            FinancialStatement.fiscal_year == fiscal_year,
        ).first()
        
        if not stmt:
            result["status"] = "not_found"
            result["errors"].append("Financial statement not found in database")
            return result
        
        # Update with extracted values
        if ocf is not None:
            stmt.operating_cash_flow = ocf
        if capex is not None:
            stmt.capital_expenditures = capex
        
        # Calculate FCF if both values are available
        if ocf is not None and capex is not None:
            fcf = float(ocf) - float(capex)
            stmt.free_cash_flow = fcf
            result["fcf"] = fcf
            result["status"] = "ok"
            logger.info(
                "Extracted cash flow for %s FY%d: OCF=%.0f, CapEx=%.0f, FCF=%.0f",
                company.ticker_symbol,
                fiscal_year,
                ocf,
                capex,
                fcf,
            )
        elif ocf is not None:
            result["status"] = "partial"
            result["errors"].append("CapEx not found in PDF")
            logger.info(
                "Partial extraction for %s FY%d: OCF=%.0f (CapEx missing)",
                company.ticker_symbol,
                fiscal_year,
                ocf,
            )
        elif capex is not None:
            result["status"] = "partial"
            result["errors"].append("OCF not found in PDF")
            logger.info(
                "Partial extraction for %s FY%d: CapEx=%.0f (OCF missing)",
                company.ticker_symbol,
                fiscal_year,
                capex,
            )
        else:
            result["status"] = "no_data"
            result["errors"].append("Neither OCF nor CapEx found in PDF")
        
        # Save to database
        db.add(stmt)
        db.commit()
            
    except Exception as e:
        result["status"] = "error"
        result["errors"].append(str(e))
        logger.error(
            "Error extracting cash flow for %s FY%d: %s",
            company.ticker_symbol,
            fiscal_year,
            e,
        )
    
    return result


def enrich_cash_flow_for_company(
    company: Company,
    year_start: int = 2020,
    year_end: int = 2026,
    db: Session = None,
) -> dict:
    """Enrich cash flow data for a company across multiple fiscal years.
    
    Processes cached PDFs to extract OCF and CapEx, then calculates FCF.
    
    Args:
        company: Company model instance
        year_start: Start fiscal year (inclusive)
        year_end: End fiscal year (inclusive)
        db: Database session
    
    Returns:
        Dict with summary of extraction results
    """
    summary = {
        "company": company.ticker_symbol,
        "years_attempted": 0,
        "years_successful": 0,
        "years_partial": 0,
        "years_failed": 0,
        "results": [],
    }
    
    for fiscal_year in range(year_start, year_end + 1):
        result = extract_cash_flow_from_cached_pdf(company, fiscal_year, db)
        summary["results"].append(result)
        summary["years_attempted"] += 1
        
        if result["status"] == "ok":
            summary["years_successful"] += 1
        elif result["status"] == "partial":
            summary["years_partial"] += 1
        else:
            summary["years_failed"] += 1
    
    return summary
