"""Business logic for per-company AI chat."""

from __future__ import annotations

import json
import logging
from datetime import date

from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.data import nse_scraper, yfinance_adapter
from app.data.ai_enrichment import _call_llm
from app.models.company import Company
from app.models.company_note import CompanyNote
from app.models.financial_statement import FinancialStatement
from app.models.intrinsic_value import IntrinsicValue
from app.models.price_history import PriceHistory
from app.schemas.company_chat import CompanyChatMessage, OnlineValidationSummary
from app.schemas.company_chat import CompanyChatContextMeta

logger = logging.getLogger(__name__)


CHAT_SYSTEM_PROMPT = """You are StockUp Analyst Copilot, a financial research assistant for NSE stocks.

You must answer using the provided database context first, then use online validation metadata to highlight potential data freshness issues.

Rules:
- Be factual and concise.
- If data appears stale or mismatched, state that clearly.
- Distinguish facts from assumptions.
- Do not fabricate values or sources.
- Provide educational analysis, not guaranteed outcomes.
"""


def _to_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _build_online_validation(
    company: Company,
    latest_db_price: PriceHistory | None,
) -> OnlineValidationSummary:
    db_close = _to_float(getattr(latest_db_price, "close_price", None))
    db_date = getattr(latest_db_price, "price_date", None)

    try:
        scraper_rows = nse_scraper.scrape_company_history(company.ticker_symbol)
    except Exception:
        scraper_rows = []

    online_close: float | None = None
    online_date: date | None = None
    source = None

    if scraper_rows:
        source = "scraper"
        online_close = _to_float(scraper_rows[0].get("close_price"))
        online_date = scraper_rows[0].get("price_date")
    elif company.yfinance_ticker:
        daily = yfinance_adapter.fetch_daily(company.yfinance_ticker)
        if daily:
            source = "yfinance"
            online_close = _to_float(daily.get("close_price"))
            online_date = daily.get("price_date")

    if online_close is None or online_date is None:
        return OnlineValidationSummary(
            status="unavailable",
            source=source,
            db_price_date=db_date,
            db_close_price=db_close,
            note="Could not fetch a reliable online quote during this request.",
        )

    if db_close is None or db_date is None:
        return OnlineValidationSummary(
            status="partial",
            source=source,
            online_price_date=online_date,
            online_close_price=online_close,
            note="Online quote available, but no latest DB price exists for comparison.",
        )

    diff_pct = None
    if db_close != 0:
        diff_pct = ((online_close - db_close) / abs(db_close)) * 100

    status = "match"
    note = "DB and online price are reasonably aligned."
    if diff_pct is not None and abs(diff_pct) > 3.0:
        status = "mismatch"
        note = "Online quote differs materially from DB latest close; verify data freshness."

    return OnlineValidationSummary(
        status=status,
        source=source,
        db_price_date=db_date,
        db_close_price=db_close,
        online_price_date=online_date,
        online_close_price=online_close,
        price_diff_pct=diff_pct,
        note=note,
    )


def _serialize_company_context(
    company: Company,
    latest_db_price: PriceHistory | None,
    financials: list[FinancialStatement],
    valuation: IntrinsicValue | None,
    user_notes: list[CompanyNote],
    validation: OnlineValidationSummary,
) -> dict:
    return {
        "company": {
            "id": company.id,
            "name": company.name,
            "ticker": company.ticker_symbol,
            "sector": company.sector,
            "industry": company.industry,
            "shares_outstanding": company.shares_outstanding,
        },
        "latest_db_price": {
            "date": latest_db_price.price_date.isoformat() if latest_db_price else None,
            "close": _to_float(getattr(latest_db_price, "close_price", None)),
            "source": latest_db_price.source if latest_db_price else None,
        },
        "latest_valuation": {
            "valuation_date": valuation.valuation_date.isoformat() if valuation else None,
            "weighted_intrinsic_value": _to_float(getattr(valuation, "weighted_intrinsic_value", None)),
            "margin_of_safety_pct": _to_float(getattr(valuation, "margin_of_safety_pct", None)),
            "recommendation": valuation.recommendation if valuation else None,
            "recommendation_reason": valuation.recommendation_reason if valuation else None,
        },
        "financials_recent": [
            {
                "fiscal_year": fs.fiscal_year,
                "revenue": _to_float(fs.revenue),
                "net_income": _to_float(fs.net_income),
                "earnings_per_share": _to_float(fs.earnings_per_share),
                "free_cash_flow": _to_float(fs.free_cash_flow),
                "debt_to_equity": _to_float(fs.debt_to_equity),
                "return_on_equity": _to_float(fs.return_on_equity),
                "dividends_per_share": _to_float(fs.dividends_per_share),
            }
            for fs in financials
        ],
        "user_notes_recent": [
            {
                "tag": note.tag,
                "note_text": note.note_text,
                "updated_at": note.updated_at.isoformat(),
            }
            for note in user_notes
        ],
        "online_validation": validation.model_dump(mode="json"),
    }


def _build_fallback_answer(
    question: str,
    company: Company,
    validation: OnlineValidationSummary,
    latest_db_price: PriceHistory | None,
    valuation: IntrinsicValue | None,
    financials: list[FinancialStatement],
) -> str:
    db_close = _to_float(getattr(latest_db_price, "close_price", None))
    db_date = latest_db_price.price_date.isoformat() if latest_db_price else "n/a"
    online_close = validation.online_close_price
    online_date = validation.online_price_date.isoformat() if validation.online_price_date else "n/a"
    diff_pct = validation.price_diff_pct

    lines: list[str] = []
    lines.append(f"Quick data-grounded summary for {company.name} ({company.ticker_symbol}):")
    lines.append("")

    # If user asks about comparison, prioritize explicit comparison output.
    if "compare" in question.lower() or "online" in question.lower() or "db" in question.lower():
        lines.append("DB vs online quote check:")
        lines.append(f"- DB latest close: {db_close:.2f} on {db_date}" if db_close is not None else "- DB latest close: unavailable")
        lines.append(
            f"- Online latest close: {online_close:.2f} on {online_date} ({validation.source or 'unknown source'})"
            if online_close is not None else
            "- Online latest close: unavailable"
        )
        if diff_pct is not None:
            sign = "+" if diff_pct >= 0 else ""
            lines.append(f"- Difference: {sign}{diff_pct:.2f}%")
        lines.append(f"- Validation status: {validation.status}")
        if validation.note:
            lines.append(f"- Note: {validation.note}")
        lines.append("")

    if valuation and _to_float(valuation.weighted_intrinsic_value) is not None:
        iv = _to_float(valuation.weighted_intrinsic_value)
        mos = _to_float(valuation.margin_of_safety_pct)
        lines.append(f"Latest intrinsic value estimate: {iv:.2f} ({valuation.valuation_date.isoformat()})")
        if mos is not None:
            lines.append(f"Margin of safety: {mos * 100:.1f}%")
        if valuation.recommendation:
            lines.append(f"Model recommendation: {valuation.recommendation}")

    if financials:
        latest_fs = financials[0]
        lines.append(f"Latest financial year in DB: FY {latest_fs.fiscal_year}")
        if _to_float(latest_fs.earnings_per_share) is not None and db_close is not None and latest_fs.earnings_per_share != 0:
            pe = db_close / float(latest_fs.earnings_per_share)
            lines.append(f"Approx trailing P/E from DB: {pe:.2f}x")

    lines.append("")
    lines.append("AI model response is currently unavailable, so this answer is generated from database fields and live validation checks only.")
    return "\n".join(lines)


def ask_company_chat(
    db: Session,
    company_id: int,
    user_id: int,
    question: str,
    history: list[CompanyChatMessage],
    verify_online: bool,
) -> tuple[str, str, OnlineValidationSummary, CompanyChatContextMeta]:
    company = db.query(Company).filter(Company.id == company_id).first()
    if company is None:
        raise ValueError("Company not found")

    latest_db_price = (
        db.query(PriceHistory)
        .filter(PriceHistory.company_id == company_id)
        .order_by(desc(PriceHistory.price_date))
        .first()
    )

    financials = (
        db.query(FinancialStatement)
        .filter(FinancialStatement.company_id == company_id)
        .order_by(desc(FinancialStatement.fiscal_year))
        .limit(5)
        .all()
    )

    valuation = (
        db.query(IntrinsicValue)
        .filter(IntrinsicValue.company_id == company_id)
        .order_by(desc(IntrinsicValue.valuation_date))
        .first()
    )

    user_notes = (
        db.query(CompanyNote)
        .filter(CompanyNote.company_id == company_id, CompanyNote.user_id == user_id)
        .order_by(desc(CompanyNote.updated_at))
        .limit(5)
        .all()
    )

    validation = OnlineValidationSummary(status="unavailable", note="Online validation disabled.")
    if verify_online:
        validation = _build_online_validation(company, latest_db_price)

    context = _serialize_company_context(
        company,
        latest_db_price,
        financials,
        valuation,
        user_notes,
        validation,
    )

    history_lines = []
    for msg in history[-8:]:
        prefix = "User" if msg.role == "user" else "Assistant"
        history_lines.append(f"{prefix}: {msg.content}")

    user_prompt = (
        "Company context (JSON):\n"
        f"{json.dumps(context, ensure_ascii=True, default=str)}\n\n"
        "Conversation so far:\n"
        f"{chr(10).join(history_lines) if history_lines else 'No prior messages.'}\n\n"
        "User question:\n"
        f"{question}\n\n"
        "Answer with practical investment analysis using the given data. "
        "If online validation indicates mismatch/unavailable data, explicitly mention reliability caveats."
    )

    try:
        answer = _call_llm(user_prompt, CHAT_SYSTEM_PROMPT)
    except Exception as exc:
        logger.warning("LLM unavailable for company chat, using fallback answer: %s", exc)
        answer = _build_fallback_answer(
            question=question,
            company=company,
            validation=validation,
            latest_db_price=latest_db_price,
            valuation=valuation,
            financials=financials,
        )

    context_meta = CompanyChatContextMeta(
        latest_db_price_date=latest_db_price.price_date if latest_db_price else None,
        latest_valuation_date=valuation.valuation_date if valuation else None,
        latest_financial_year=financials[0].fiscal_year if financials else None,
    )
    return answer, company.ticker_symbol, validation, context_meta
