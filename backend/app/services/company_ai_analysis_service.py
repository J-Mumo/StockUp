"""AI-generated per-company research narrative.

Produces a grounded, sector-aware critique of the current valuation output.
Designed to sit *alongside* the quantitative valuation, not replace it:

* The LLM is given the actual financials, latest price, and computed
  valuation as context. It's instructed to only cite figures present in
  that context — no invented numbers.
* Fingerprint-based caching prevents redundant LLM calls when nothing has
  materially changed.
* Structured output (verdict, bull/bear points, key risks, IV range) is
  stored alongside the markdown narrative so the UI can render both.

The service exposes two public entry points:

* :func:`get_or_generate_analysis` — main workhorse. Returns the current
  analysis if the fingerprint matches; otherwise generates a fresh one.
* :func:`should_regenerate` — pure decision function for background triggers
  (Celery task deciding whether to spend an LLM call).
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.config import get_settings
from app.data.ai_enrichment import _call_llm
from app.models.company import Company
from app.models.company_ai_analysis import CompanyAIAnalysis
from app.models.financial_statement import FinancialStatement
from app.models.intrinsic_value import IntrinsicValue
from app.models.price_history import PriceHistory
from app.services.valuation.sector_norms import norms_for_sector
from app.services.valuation.sectors import SectorKind, classify_sector

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

#: Bump this when the system prompt or expected structured output shape
#: changes materially — old rows with a different prompt_version won't be
#: mixed with new ones in the UI (they'll be regenerated on next open).
PROMPT_VERSION = "v1.0"

#: Analyses older than this become "stale" and are eligible for background
#: regeneration even if inputs haven't changed. Keeps narrative dates fresh.
STALENESS_DAYS = 60

#: Price movement (absolute percent since last analysis) that triggers a
#: regeneration even when financials haven't changed.
PRICE_MOVE_THRESHOLD_PCT = 20.0

#: Number of prior years' financials fed to the LLM as context.
FINANCIALS_LOOKBACK_YEARS = 5


# ---------------------------------------------------------------------------
# Prompt content
# ---------------------------------------------------------------------------

_BASE_SYSTEM_PROMPT = """You are StockUp Analyst Copilot, a research assistant \
for Nairobi Securities Exchange (NSE) listed companies.

Your job is to critically review the quantitative valuation output produced \
by StockUp's DCF/EPV/Book-Value engine, and produce a grounded, balanced \
analysis for a Kenyan retail investor.

Absolute rules — violating any of these breaks the tool:

1. Use only figures present in the supplied JSON context. Never invent a \
number, a PPA counterparty, a regulatory event, or a news item. If a fact \
would help but isn't in the context, say "not disclosed in the supplied \
data" instead of guessing.
2. Do not use words like "Buy", "Sell", or "Strong Buy" as your verdict. \
Prefer "Consider", "Watch", "Caution", "Wait", or "Avoid". You are helping \
the user reason, not giving investment advice.
3. Explicitly critique the DCF number when appropriate. If the DCF anchors \
on a peak year, or the terminal-growth assumption is inappropriate for the \
sector, say so.
4. Distinguish accounting-quality issues (unrealised FX losses on \
concessional debt, revaluation reserves, one-off receivable settlements) \
from underlying business quality.
5. Reply with a single JSON object — no markdown fences, no prose before or \
after the JSON. Schema:

    {
      "narrative_md": "<markdown, 400-800 words>",
      "verdict": "<Consider|Watch|Caution|Wait|Avoid>",
      "iv_low_kes": <number or null>,
      "iv_high_kes": <number or null>,
      "bull_points": ["...", "..."],
      "bear_points": ["...", "..."],
      "key_risks": ["...", "..."],
      "caveats": ["...", "..."],
      "sector_specific_notes": ["...", "..."]
    }

The narrative_md may use headings and bullet points. Include a short \
"Valuation disagreement" section that reconciles market price, book value, \
DCF, and EPV.
"""

# Sector-specific guidance appended to the base prompt. Kept minimal —
# these are prompts, not policy documents.
_SECTOR_GUIDANCE: dict[str, str] = {
    "energy/utility": """This company is an electricity generator or \
regulated utility. Extra considerations you must weigh in the narrative:

* ROE below 15% is not automatically a quality failure — utility ROE \
globally sits at 8–12%.
* Large concessional foreign-currency debt (World Bank / AFD / JICA / KfW) \
creates unrealised FX losses that hit net income but not operating cash \
flow. If OCF growth diverges from NI growth, mention it.
* Counterparty concentration — most Kenyan generators sell to Kenya Power \
under PPAs. Receivable balances from off-takers are a major risk.
* Maintenance vs growth capex should be distinguished when possible. If \
the data doesn't disclose the split, say so.
* Book value often includes revaluation reserves on physical assets; a P/B \
below 1.0 is not necessarily an irrational discount.""",
    "energy/downstream": """This company is a downstream oil marketer. \
Extra considerations:

* Thin margins, high working-capital turnover — small tariff/regulation \
changes matter more than for asset-heavy names.
* Debt is largely trade finance; leverage ratios read differently than for \
an industrial.
* FX exposure on inventory and USD-denominated fuel imports is a material \
risk.""",
    "real_estate": """This company operates in real estate. Extra \
considerations:

* NAV and FFO (funds from operations) matter more than headline earnings.
* Loan-to-value on investment properties, occupancy rate, and tenant \
concentration are the primary risk lenses.""",
    "telecom": """This is a telecommunications operator. Extra \
considerations:

* Capex intensity is structural; free cash flow after maintenance capex is \
the right lens, not headline FCF in isolation.
* Regulatory decisions (spectrum, interconnect, mobile-money oversight) \
are a material risk.""",
    "industrial": "",
}


# ---------------------------------------------------------------------------
# Fingerprinting
# ---------------------------------------------------------------------------

def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def compute_input_fingerprint(
    company: Company,
    financials: list[FinancialStatement],
    valuation: IntrinsicValue | None,
    latest_price: PriceHistory | None,  # noqa: ARG001 — kept for API symmetry
) -> str:
    """Stable SHA-256 hash of the *structural* inputs that drive the analysis.

    The hash captures anything the LLM would materially react to besides
    day-to-day price moves:

    * Company id + sector (sector changes flip the whole prompt)
    * Each financial year's revenue/NI/FCF/OCF/equity/liabilities
    * The current valuation's DCF/EPV/BV/weighted IV/MOS

    Price is deliberately excluded: small intraday ticks would otherwise
    invalidate the cache on every request. Real price moves are handled
    separately by the ``PRICE_MOVE_THRESHOLD_PCT`` trigger in
    :func:`should_regenerate`, which compares the current price against the
    price snapshotted into the last analysis's ``structured_json``.
    """
    payload: dict[str, Any] = {
        "company_id": company.id,
        "sector": (company.sector or "").strip().lower(),
        "shares_outstanding": company.shares_outstanding,
        "financials": sorted(
            (
                {
                    "y": fs.fiscal_year,
                    "rev": _safe_float(fs.revenue),
                    "ni": _safe_float(fs.net_income),
                    "eps": _safe_float(fs.earnings_per_share),
                    "fcf": _safe_float(fs.free_cash_flow),
                    "ocf": _safe_float(fs.operating_cash_flow),
                    "eq": _safe_float(fs.total_equity)
                    or _safe_float(fs.shareholders_equity),
                    "lia": _safe_float(fs.total_liabilities),
                    "roe": _safe_float(fs.return_on_equity),
                    "de": _safe_float(fs.debt_to_equity),
                    "dps": _safe_float(fs.dividends_per_share),
                }
                for fs in financials
            ),
            key=lambda r: r["y"],
        ),
        "valuation": None
        if valuation is None
        else {
            "dcf": _safe_float(valuation.dcf_value),
            "epv": _safe_float(valuation.epv_value),
            "bv": _safe_float(valuation.book_value_estimate),
            "weighted": _safe_float(valuation.weighted_intrinsic_value),
            "mos": _safe_float(valuation.margin_of_safety_pct),
            "model": valuation.model_used,
        },
    }
    blob = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()


# ---------------------------------------------------------------------------
# Regeneration decision
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RegenDecision:
    """Result of :func:`should_regenerate`.

    ``regenerate`` says whether to spend an LLM call; ``reason`` says why
    (or why not) so the Celery task can log it usefully.
    """

    regenerate: bool
    reason: str


def should_regenerate(
    current: CompanyAIAnalysis | None,
    new_fingerprint: str,
    latest_price: PriceHistory | None,
    max_age_days: int = STALENESS_DAYS,
    price_move_threshold_pct: float = PRICE_MOVE_THRESHOLD_PCT,
) -> RegenDecision:
    """Decide whether to (re)generate the analysis.

    Regenerates when:
    * There is no prior analysis, or the prompt version has changed.
    * The input fingerprint has changed (financials/valuation moved).
    * The latest price has moved more than ``price_move_threshold_pct`` vs
      the price at the last analysis's fingerprint.
    * The analysis is older than ``max_age_days``.

    Otherwise returns ``regenerate=False`` (serve cached).
    """
    if current is None:
        return RegenDecision(True, "no_prior_analysis")
    if current.prompt_version != PROMPT_VERSION:
        return RegenDecision(True, "prompt_version_changed")
    if current.input_fingerprint != new_fingerprint:
        return RegenDecision(True, "input_fingerprint_changed")

    age = datetime.utcnow() - current.generated_at
    if age > timedelta(days=max_age_days):
        return RegenDecision(True, f"stale_after_{max_age_days}d")

    # Price-move check — best-effort; if we can't recover the old price we
    # just don't trigger on this axis.
    if latest_price is not None and current.structured_json is not None:
        old_price = _safe_float(
            (current.structured_json.get("_context_price") or {}).get("close")
        )
        new_price = _safe_float(latest_price.close_price)
        if old_price and new_price and old_price > 0:
            move_pct = abs(new_price - old_price) / old_price * 100
            if move_pct >= price_move_threshold_pct:
                return RegenDecision(True, f"price_moved_{move_pct:.1f}%")

    return RegenDecision(False, "cache_valid")


# ---------------------------------------------------------------------------
# Context assembly & prompt building
# ---------------------------------------------------------------------------

def _build_context(
    company: Company,
    financials: list[FinancialStatement],
    valuation: IntrinsicValue | None,
    latest_price: PriceHistory | None,
) -> dict[str, Any]:
    """Serialise the ground-truth inputs for the LLM.

    Deliberately compact: the LLM should be able to hold the whole thing in
    its head. We include the sector norms actually applied by the quality
    engine so the LLM can explain the "why" behind the thresholds.
    """
    norms = norms_for_sector(company.sector)
    sector_kind = classify_sector(company.sector)

    fs_rows = [
        {
            "fiscal_year": fs.fiscal_year,
            "revenue": _safe_float(fs.revenue),
            "net_income": _safe_float(fs.net_income),
            "earnings_per_share": _safe_float(fs.earnings_per_share),
            "operating_cash_flow": _safe_float(fs.operating_cash_flow),
            "capital_expenditures": _safe_float(fs.capital_expenditures),
            "free_cash_flow": _safe_float(fs.free_cash_flow),
            "total_assets": _safe_float(fs.total_assets),
            "total_liabilities": _safe_float(fs.total_liabilities),
            "total_equity": _safe_float(fs.total_equity)
            or _safe_float(fs.shareholders_equity),
            "return_on_equity": _safe_float(fs.return_on_equity),
            "debt_to_equity": _safe_float(fs.debt_to_equity),
            "dividends_per_share": _safe_float(fs.dividends_per_share),
        }
        for fs in sorted(financials, key=lambda f: f.fiscal_year, reverse=True)[
            :FINANCIALS_LOOKBACK_YEARS
        ]
    ]

    valuation_dict = None
    if valuation is not None:
        valuation_dict = {
            "valuation_date": valuation.valuation_date.isoformat(),
            "dcf_value_kes": _safe_float(valuation.dcf_value),
            "epv_value_kes": _safe_float(valuation.epv_value),
            "book_value_kes": _safe_float(valuation.book_value_estimate),
            "weighted_intrinsic_value_kes": _safe_float(
                valuation.weighted_intrinsic_value
            ),
            "current_market_price_kes": _safe_float(valuation.current_market_price),
            "margin_of_safety_pct": _safe_float(valuation.margin_of_safety_pct),
            "recommendation": valuation.recommendation,
            "recommendation_reason": valuation.recommendation_reason,
            "model_used": valuation.model_used,
            "scenario_values": valuation.scenario_values,
        }

    price_dict = None
    if latest_price is not None:
        price_dict = {
            "date": latest_price.price_date.isoformat(),
            "close": _safe_float(latest_price.close_price),
            "source": latest_price.source,
        }

    return {
        "company": {
            "id": company.id,
            "name": company.name,
            "ticker": company.ticker_symbol,
            "sector": company.sector,
            "industry": company.industry,
            "shares_outstanding": company.shares_outstanding,
        },
        "sector_classification": {
            "kind": sector_kind.value,
            "quality_norms_applied": {
                "label": norms.label,
                "roe_min": norms.roe_min,
                "de_max": norms.de_max,
                "liab_to_ni_max": norms.liab_to_ni_max,
                "liab_to_ocf_max": norms.liab_to_ocf_max,
                "prefer_ocf_debt_metric": norms.prefer_ocf_debt_metric,
            },
        },
        "latest_price": price_dict,
        "financials": fs_rows,
        "valuation": valuation_dict,
    }


def _select_sector_key(company: Company) -> str:
    """Return the ``_SECTOR_GUIDANCE`` key for this company's sector."""
    return norms_for_sector(company.sector).label


def _build_system_prompt(sector_key: str) -> str:
    guidance = _SECTOR_GUIDANCE.get(sector_key, "")
    if not guidance:
        return _BASE_SYSTEM_PROMPT
    return f"{_BASE_SYSTEM_PROMPT}\n\nSector-specific guidance:\n{guidance}"


def _build_user_prompt(context: dict[str, Any]) -> str:
    return (
        "Here is the ground-truth context for the company. Every figure in "
        "your response must be traceable to this JSON.\n\n"
        f"{json.dumps(context, ensure_ascii=True, default=str, indent=2)}\n\n"
        "Now produce the single JSON response as specified in the system "
        "prompt."
    )


# ---------------------------------------------------------------------------
# Response parsing
# ---------------------------------------------------------------------------

_STRUCTURED_KEYS = (
    "verdict",
    "iv_low_kes",
    "iv_high_kes",
    "bull_points",
    "bear_points",
    "key_risks",
    "caveats",
    "sector_specific_notes",
)


def _extract_json_blob(text: str) -> str:
    """Pull the JSON object out of the LLM response.

    Handles the common failure mode of the model wrapping its answer in a
    ```json fence despite instructions.
    """
    text = text.strip()
    # Strip leading ```json / ``` fences if present.
    fence_match = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL)
    if fence_match:
        return fence_match.group(1).strip()
    # Otherwise, take from first '{' to last '}'.
    start = text.find("{")
    end = text.rfind("}")
    if start != -1 and end != -1 and end > start:
        return text[start : end + 1]
    return text


def _parse_response(raw: str, price_dict: dict[str, Any] | None) -> tuple[str, dict[str, Any]]:
    """Return (narrative_md, structured_json) from a raw LLM response.

    Falls back to a minimal structured shape if the model returned invalid
    JSON — we still store the raw text as the narrative so the user gets
    *something*.
    """
    blob = _extract_json_blob(raw)
    try:
        parsed = json.loads(blob)
    except json.JSONDecodeError:
        logger.warning("LLM analysis response was not valid JSON, storing raw text")
        return raw, {
            "verdict": "Watch",
            "bull_points": [],
            "bear_points": [],
            "key_risks": [],
            "caveats": ["LLM response was not valid JSON — raw text stored."],
            "sector_specific_notes": [],
            "_context_price": price_dict,
        }

    narrative = str(parsed.get("narrative_md") or "").strip()
    if not narrative:
        narrative = "_No narrative returned._"

    structured: dict[str, Any] = {k: parsed.get(k) for k in _STRUCTURED_KEYS}
    # Snapshot the price at generation time so the price-move trigger can
    # compare against it later.
    structured["_context_price"] = price_dict
    return narrative, structured


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def get_latest_analysis(
    db: Session, company_id: int
) -> CompanyAIAnalysis | None:
    """Latest analysis row for a company (any status), or None."""
    return (
        db.query(CompanyAIAnalysis)
        .filter(CompanyAIAnalysis.company_id == company_id)
        .order_by(desc(CompanyAIAnalysis.generated_at))
        .first()
    )


def _load_company_inputs(
    db: Session, company_id: int
) -> tuple[
    Company,
    list[FinancialStatement],
    IntrinsicValue | None,
    PriceHistory | None,
]:
    """Fetch everything the analysis needs. Raises ValueError if company missing."""
    company = db.query(Company).filter(Company.id == company_id).first()
    if company is None:
        raise ValueError(f"Company {company_id} not found")

    financials = (
        db.query(FinancialStatement)
        .filter(FinancialStatement.company_id == company_id)
        .order_by(desc(FinancialStatement.fiscal_year))
        .limit(FINANCIALS_LOOKBACK_YEARS)
        .all()
    )
    valuation = (
        db.query(IntrinsicValue)
        .filter(IntrinsicValue.company_id == company_id)
        .order_by(desc(IntrinsicValue.valuation_date), desc(IntrinsicValue.id))
        .first()
    )
    latest_price = (
        db.query(PriceHistory)
        .filter(PriceHistory.company_id == company_id)
        .order_by(desc(PriceHistory.price_date))
        .first()
    )
    return company, financials, valuation, latest_price


def generate_analysis(
    db: Session,
    company_id: int,
    triggered_by: str,
) -> CompanyAIAnalysis:
    """Force-generate a fresh analysis and persist it.

    Callers should usually go through :func:`get_or_generate_analysis`
    instead, which honours the fingerprint cache. This entry is used by
    the manual-refresh endpoint and by the Celery task once it's decided
    a regeneration is warranted.

    Raises ``ValueError`` if the company doesn't exist. Bubbles any LLM
    provider errors — the caller decides retry policy.
    """
    company, financials, valuation, latest_price = _load_company_inputs(
        db, company_id
    )

    context = _build_context(company, financials, valuation, latest_price)
    system_prompt = _build_system_prompt(_select_sector_key(company))
    user_prompt = _build_user_prompt(context)

    logger.info(
        "generating AI analysis: company=%s trigger=%s",
        company.ticker_symbol,
        triggered_by,
    )
    raw = _call_llm(user_prompt, system_prompt)
    narrative, structured = _parse_response(raw, context.get("latest_price"))

    fingerprint = compute_input_fingerprint(
        company, financials, valuation, latest_price
    )
    settings = get_settings()
    model_name = settings.ai_model or "unknown"

    row = CompanyAIAnalysis(
        company_id=company.id,
        generated_at=datetime.utcnow(),
        model_name=model_name,
        prompt_version=PROMPT_VERSION,
        input_fingerprint=fingerprint,
        sector_kind=classify_sector(company.sector).value,
        narrative_md=narrative,
        structured_json=structured,
        triggered_by=triggered_by,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def get_or_generate_analysis(
    db: Session,
    company_id: int,
    triggered_by: str,
    force: bool = False,
) -> tuple[CompanyAIAnalysis, RegenDecision]:
    """Serve cached or generate a fresh analysis.

    Returns the analysis row plus the decision that produced it. Callers
    can use the decision to distinguish "cached hit" from "just generated"
    for logging or UI hints.

    ``force=True`` skips the cache decision and always generates a new row
    (used by the manual-refresh endpoint).
    """
    company, financials, valuation, latest_price = _load_company_inputs(
        db, company_id
    )
    current = get_latest_analysis(db, company_id)
    fingerprint = compute_input_fingerprint(
        company, financials, valuation, latest_price
    )
    decision = (
        RegenDecision(True, "forced")
        if force
        else should_regenerate(current, fingerprint, latest_price)
    )
    if not decision.regenerate and current is not None:
        return current, decision

    row = generate_analysis(db, company_id, triggered_by=triggered_by)
    return row, decision
