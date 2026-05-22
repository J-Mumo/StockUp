"""Annual-report goal extraction and progress assessment.

Two-pass LLM workflow:

* Pass A (``extract_goals_from_report``): read a single year's annual
  report PDF and return a list of forward-looking commitments —
  quantitative targets, strategic initiatives, ESG/operational
  promises. Stored in ``company_goals``.

* Pass B (``assess_goal_progress``): for each open goal set in year T,
  determine how it has fared in year T+k. Quantitative goals whose
  ``metric_name`` we already track in ``financial_statements`` are
  evaluated *mechanically* (no LLM call). Everything else falls back to
  an LLM call over the year T+k report.

The pipeline reuses the same cached PDFs that ``financial_statements_registry``
already downloads to ``data/annual_reports/<TICKER>/<YEAR>.pdf``.
"""

from __future__ import annotations

import json
import logging
import re
import time
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy.orm import Session

from app.config import get_settings
from app.models.company import Company
from app.models.company_goal import (
    ASSESSMENT_METHODS,
    GOAL_CATEGORIES,
    GOAL_CONFIDENCES,
    GOAL_STATUSES,
    CompanyGoal,
    CompanyGoalProgress,
)
from app.models.financial_statement import FinancialStatement

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Metrics the LLM may emit that map onto columns we already track in
# financial_statements. Keys = metric_name strings the prompt requests;
# values = (FinancialStatement attribute, optional derivation callable).
# Mechanical evaluation only works when target_unit matches the value
# semantics (absolute KES vs. percentage vs. ratio).
_DERIVED_METRICS: dict[str, str] = {
    "revenue": "revenue",
    "net_income": "net_income",
    "total_assets": "total_assets",
    "total_equity": "total_equity",
    "earnings_per_share": "earnings_per_share",
    "dividends_per_share": "dividends_per_share",
    "return_on_equity": "return_on_equity",
    "debt_to_equity": "debt_to_equity",
    "operating_cash_flow": "operating_cash_flow",
    "free_cash_flow": "free_cash_flow",
}

# Tolerance band for mechanical "achieved" classification.
_ACHIEVED_TOLERANCE = 0.02  # within 2% of target counts as achieved
_ON_TRACK_TOLERANCE = 0.10  # within 10% counts as on-track / partial


# ---------------------------------------------------------------------------
# Pass A — Goal Extraction Prompt
# ---------------------------------------------------------------------------

EXTRACTION_SYSTEM_PROMPT = """\
You are a financial-analyst assistant reading an AUDITED annual report PDF \
for a company listed on the Nairobi Securities Exchange (NSE), Kenya.

Your task is to extract FORWARD-LOOKING COMMITMENTS that management makes \
to shareholders in this report. These typically appear in:

- Chairman's Statement
- CEO's / Managing Director's Statement
- Strategy / "Looking Ahead" / "Future Outlook" sections
- Sustainability / ESG sections (commitments with target dates)
- Capital-allocation or dividend-policy statements

WHAT COUNTS AS A GOAL:
- A specific quantitative target ("grow revenue by 15% in FY2025"; \
"achieve ROE of 18%"; "reduce cost-to-income ratio to 45% by 2027").
- A specific strategic initiative with an implementation horizon \
("launch retail-banking arm in FY2024"; "complete core-banking-system migration \
by end of 2025"; "expand to Rwanda in 2026").
- A specific ESG / operational commitment with a metric or date \
("net-zero emissions by 2030"; "train 10,000 farmers by 2027"; "double women \
in senior management by 2028").

WHAT TO SKIP:
- Vague aspirations ("become East Africa's leading bank") — no metric, no date.
- Statements about the past or current year ("we grew revenue by 12%").
- Market forecasts about external conditions ("inflation is expected to ease").
- Management opinions ("we believe rates will normalise") — these are not commitments.

RULES:
- Return at most 20 goals; prioritise the most specific.
- ``goal_text`` is a clean, self-contained one-sentence summary you write.
- ``source_quote`` is the verbatim wording from the report (≤300 chars).
- ``goal_category``: one of "financial", "strategic", "esg", "operational".
- ``metric_name``: if a numeric target exists, pick a stable snake_case name. \
Use these when applicable so we can auto-evaluate later: \
revenue, net_income, total_assets, total_equity, earnings_per_share, \
dividends_per_share, return_on_equity, debt_to_equity, operating_cash_flow, \
free_cash_flow, cost_to_income_ratio, branch_count, customer_count, npl_ratio, \
carbon_emissions_tonnes, women_in_management_pct. Otherwise null.
- ``target_value``: numeric. If a target is "grow X by 15%", set target_value=15 \
and target_unit="percent_growth". If "achieve X of KES 100B", target_value=100000000000 \
and target_unit="KES". If "reach 1m customers", target_value=1000000 and target_unit="count".
- ``target_horizon_year``: the year by which the goal should be met. If \
"by 2027", set 2027. If "in FY24", set 2024. If unstated, null.
- ``source_section``: chairman_statement | ceo_statement | outlook | strategy | esg \
| capital_allocation | other.
"""

EXTRACTION_USER_PROMPT = """\
For {company_name} (NSE: {ticker}), extract the management commitments \
stated in this fiscal year {fiscal_year} annual report.

Return ONLY a JSON object (no markdown, no explanation) of the form:

{{
  "company": "{ticker}",
  "fiscal_year": {fiscal_year},
  "goals": [
    {{
      "goal_text": "...",
      "goal_category": "financial|strategic|esg|operational",
      "metric_name": "snake_case_metric_or_null",
      "target_value": null,
      "target_unit": "percent | percent_growth | KES | count | ratio | tonnes | null",
      "target_horizon_year": null,
      "source_section": "chairman_statement|ceo_statement|outlook|strategy|esg|capital_allocation|other",
      "source_quote": "verbatim quote, <=300 chars"
    }}
  ]
}}
"""


# ---------------------------------------------------------------------------
# Pass B — Progress Assessment Prompt
# ---------------------------------------------------------------------------

ASSESSMENT_SYSTEM_PROMPT = """\
You are a financial-analyst assistant. You will be given:

1. A forward-looking goal a company committed to in an earlier annual report.
2. The text of a LATER annual report (or its summary).

Decide whether the goal is being honoured, abandoned, achieved, or simply \
not mentioned anymore. Return ONLY a JSON object.

STATUS VALUES:
- "achieved" — the target has been hit or exceeded.
- "on_track" — explicit progress that puts the goal within reach by its horizon.
- "partially_achieved" — meaningful progress but unlikely to fully hit target.
- "missed" — the horizon has passed and the target was not met, or \
management explicitly acknowledges falling short.
- "abandoned" — management has explicitly dropped or restated the goal.
- "no_mention" — the later report makes no reference to this commitment.

RULES:
- Be strict: do not classify "on_track" without explicit forward evidence.
- ``evidence_quote`` must be a verbatim quote (≤300 chars) from the later report.
- ``confidence``: "high" if the report explicitly addresses the goal; \
"medium" if you inferred from neighbouring statements; "low" if mostly absent.
"""

ASSESSMENT_USER_PROMPT = """\
GOAL (set in fiscal year {set_year}):
  Text: {goal_text}
  Category: {category}
  {target_line}
  Horizon: {horizon}
  Original quote: "{source_quote}"

ASSESS THIS GOAL using the fiscal year {assess_year} annual report attached.

Return ONLY:
{{
  "status": "achieved|on_track|partially_achieved|missed|abandoned|no_mention",
  "actual_value": null,
  "narrative": "1-2 sentences",
  "evidence_quote": "verbatim, <=300 chars, or empty if no_mention",
  "confidence": "high|medium|low"
}}
"""


# ---------------------------------------------------------------------------
# Cached PDF path (mirrors financial_statements_registry layout)
# ---------------------------------------------------------------------------


def _pdf_path(ticker: str, fiscal_year: int) -> Path | None:
    settings = get_settings()
    base = Path(settings.pdf_cache_dir)
    if not base.is_absolute():
        base = Path(__file__).resolve().parent.parent.parent / base
    candidate = base / ticker.upper() / f"{fiscal_year}.pdf"
    return candidate if candidate.exists() else None


# ---------------------------------------------------------------------------
# Tolerant JSON loader (mirrors annual_report_parser)
# ---------------------------------------------------------------------------


def _tolerant_json(text: str) -> Any | None:
    raw = text or ""

    def _load(s: str):
        try:
            return json.loads(s)
        except json.JSONDecodeError:
            return None

    # Strip ```json``` fences.
    fence = re.search(r"```(?:json|JSON)?\s*\n?(.*?)```", raw, flags=re.DOTALL)
    candidate = fence.group(1) if fence else raw
    data = _load(candidate.strip())
    if data is not None:
        return data

    # Largest {...} blob.
    brace = re.search(r"\{.*\}", candidate, flags=re.DOTALL)
    if brace:
        cleaned = brace.group(0)
        cleaned = re.sub(r"//[^\n]*", "", cleaned)
        cleaned = re.sub(r",\s*([}\]])", r"\1", cleaned)
        data = _load(cleaned)
        if data is not None:
            return data
    return None


# ---------------------------------------------------------------------------
# OpenAI client helpers
# ---------------------------------------------------------------------------


def _openai_pdf_call(
    pdf_path: Path,
    system_prompt: str,
    user_prompt: str,
    *,
    max_tokens: int = 4000,
) -> str | None:
    """Run a single chat-completions call with the PDF uploaded.

    Returns the raw response text, or None on failure.
    """
    import openai

    settings = get_settings()
    if not settings.openai_api_key:
        logger.error("OPENAI_API_KEY not configured")
        return None

    client = openai.OpenAI(api_key=settings.openai_api_key)

    try:
        file_obj = client.files.create(
            file=pdf_path.open("rb"),
            purpose="assistants",
        )
        response = client.chat.completions.create(
            model=settings.ai_model or "gpt-4.1",
            messages=[
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": [
                        {"type": "file", "file": {"file_id": file_obj.id}},
                        {"type": "text", "text": user_prompt},
                    ],
                },
            ],
            temperature=0.0,
            max_tokens=max_tokens,
        )
        try:
            client.files.delete(file_obj.id)
        except Exception:
            pass
        return response.choices[0].message.content.strip()
    except Exception as e:
        logger.error("OpenAI call failed for %s: %s", pdf_path, e)
        return None


# ---------------------------------------------------------------------------
# Pass A — Extract Goals
# ---------------------------------------------------------------------------


def _coerce_goal(raw: dict) -> dict | None:
    text = (raw.get("goal_text") or "").strip()
    category = (raw.get("goal_category") or "").strip().lower()
    if not text or category not in GOAL_CATEGORIES:
        return None
    return {
        "goal_text": text[:500],
        "goal_category": category,
        "metric_name": (raw.get("metric_name") or None) or None,
        "target_value": raw.get("target_value"),
        "target_unit": (raw.get("target_unit") or None) or None,
        "target_horizon_year": raw.get("target_horizon_year"),
        "source_section": (raw.get("source_section") or None) or None,
        "source_quote": (raw.get("source_quote") or "")[:1000] or None,
    }


def extract_goals_from_report(
    db: Session,
    company: Company,
    fiscal_year: int,
    *,
    skip_if_exists: bool = True,
) -> dict[str, Any]:
    """Extract management goals from a single year's annual report.

    Upserts into ``company_goals``. Returns a summary dict.
    """
    ticker = company.ticker_symbol

    if skip_if_exists:
        existing_count = (
            db.query(CompanyGoal)
            .filter(
                CompanyGoal.company_id == company.id,
                CompanyGoal.fiscal_year_set == fiscal_year,
            )
            .count()
        )
        if existing_count:
            return {
                "ticker": ticker,
                "fiscal_year": fiscal_year,
                "status": "skipped_existing",
                "goals_existing": existing_count,
            }

    pdf = _pdf_path(ticker, fiscal_year)
    if pdf is None:
        return {
            "ticker": ticker,
            "fiscal_year": fiscal_year,
            "status": "no_pdf",
            "error": f"No cached PDF at data/annual_reports/{ticker}/{fiscal_year}.pdf",
        }

    user_prompt = EXTRACTION_USER_PROMPT.format(
        company_name=company.name,
        ticker=ticker,
        fiscal_year=fiscal_year,
    )

    logger.info("Extracting goals from %s for %s FY%d", pdf.name, ticker, fiscal_year)
    raw_text = _openai_pdf_call(pdf, EXTRACTION_SYSTEM_PROMPT, user_prompt)
    if raw_text is None:
        return {
            "ticker": ticker,
            "fiscal_year": fiscal_year,
            "status": "extraction_failed",
        }

    parsed = _tolerant_json(raw_text)
    if not isinstance(parsed, dict) or "goals" not in parsed:
        logger.warning("Could not parse goal response for %s FY%d", ticker, fiscal_year)
        return {
            "ticker": ticker,
            "fiscal_year": fiscal_year,
            "status": "parse_failed",
            "raw_excerpt": (raw_text or "")[:200],
        }

    inserted = 0
    skipped = 0
    for raw_goal in parsed.get("goals", []) or []:
        coerced = _coerce_goal(raw_goal)
        if coerced is None:
            skipped += 1
            continue
        goal = CompanyGoal(
            company_id=company.id,
            fiscal_year_set=fiscal_year,
            **coerced,
        )
        db.add(goal)
        inserted += 1

    db.commit()

    return {
        "ticker": ticker,
        "fiscal_year": fiscal_year,
        "status": "success",
        "goals_inserted": inserted,
        "goals_skipped_invalid": skipped,
    }


# ---------------------------------------------------------------------------
# Pass B — Mechanical evaluator
# ---------------------------------------------------------------------------


def _get_financial(db: Session, company_id: int, fiscal_year: int) -> FinancialStatement | None:
    return (
        db.query(FinancialStatement)
        .filter(
            FinancialStatement.company_id == company_id,
            FinancialStatement.fiscal_year == fiscal_year,
            FinancialStatement.period_type == "annual",
        )
        .first()
    )


def _mechanical_assessment(
    db: Session,
    goal: CompanyGoal,
    assess_year: int,
) -> dict[str, Any] | None:
    """Try to evaluate ``goal`` against stored financials for ``assess_year``.

    Returns an assessment dict (status, actual_value, narrative, confidence,
    method='mechanical') or ``None`` if mechanical evaluation isn't possible.
    """
    if goal.target_value is None or not goal.metric_name:
        return None

    attr = _DERIVED_METRICS.get(goal.metric_name)
    if attr is None:
        return None

    target = float(goal.target_value)
    unit = (goal.target_unit or "").lower()

    fs_assess = _get_financial(db, goal.company_id, assess_year)
    if fs_assess is None:
        return None
    actual_raw = getattr(fs_assess, attr, None)
    if actual_raw is None:
        return None
    actual = float(actual_raw)

    # Convert actual into the same semantic as ``target`` based on unit.
    if unit == "percent_growth":
        baseline_year = goal.fiscal_year_set
        fs_baseline = _get_financial(db, goal.company_id, baseline_year)
        if fs_baseline is None:
            return None
        baseline = getattr(fs_baseline, attr, None)
        if not baseline:
            return None
        actual_compare = (actual / float(baseline) - 1.0) * 100.0
    elif unit in {"percent", "%"}:
        # Stored value may already be a fraction (e.g. ROE=0.18). If so,
        # scale to percent for comparison.
        actual_compare = actual * 100.0 if abs(actual) <= 1.5 else actual
    elif unit in {"ratio", None, ""}:
        actual_compare = actual
    elif unit in {"kes", "ksh", "shillings"}:
        actual_compare = actual
    elif unit == "count":
        actual_compare = actual
    else:
        return None

    if target == 0:
        return None

    # "Achievement" semantics depend on whether higher or lower is better.
    # We treat: cost_to_income_ratio, debt_to_equity, npl_ratio, carbon_emissions_tonnes
    # as lower-is-better; everything else higher-is-better.
    lower_better = goal.metric_name in {
        "cost_to_income_ratio",
        "debt_to_equity",
        "npl_ratio",
        "carbon_emissions_tonnes",
    }

    if lower_better:
        ratio = actual_compare / target  # <1 = good
        if ratio <= 1.0 + _ACHIEVED_TOLERANCE:
            status = "achieved"
        elif ratio <= 1.0 + _ON_TRACK_TOLERANCE:
            status = "on_track"
        elif assess_year >= (goal.target_horizon_year or assess_year):
            status = "missed"
        else:
            status = "partially_achieved"
    else:
        ratio = actual_compare / target  # >1 = good
        if ratio >= 1.0 - _ACHIEVED_TOLERANCE:
            status = "achieved"
        elif ratio >= 1.0 - _ON_TRACK_TOLERANCE:
            status = "on_track"
        elif assess_year >= (goal.target_horizon_year or assess_year):
            status = "missed"
        else:
            status = "partially_achieved"

    narrative = (
        f"Mechanical: target {target} {unit or ''} vs actual {actual_compare:.4g} "
        f"({(ratio - 1.0) * 100:+.1f}% deviation)."
    )
    return {
        "status": status,
        "actual_value": float(actual_compare),
        "narrative": narrative,
        "evidence_quote": None,
        "confidence": "high",
        "assessment_method": "mechanical",
    }


# ---------------------------------------------------------------------------
# Pass B — LLM fallback
# ---------------------------------------------------------------------------


def _llm_assessment(
    company: Company,
    goal: CompanyGoal,
    assess_year: int,
) -> dict[str, Any] | None:
    pdf = _pdf_path(company.ticker_symbol, assess_year)
    if pdf is None:
        return None

    if goal.target_value is not None:
        target_line = (
            f"Target: {goal.target_value} {goal.target_unit or ''} "
            f"(metric: {goal.metric_name or 'unspecified'})"
        )
    else:
        target_line = "Target: qualitative / strategic"

    user_prompt = ASSESSMENT_USER_PROMPT.format(
        set_year=goal.fiscal_year_set,
        goal_text=goal.goal_text,
        category=goal.goal_category,
        target_line=target_line,
        horizon=goal.target_horizon_year or "unspecified",
        source_quote=(goal.source_quote or "")[:280],
        assess_year=assess_year,
    )

    raw_text = _openai_pdf_call(
        pdf, ASSESSMENT_SYSTEM_PROMPT, user_prompt, max_tokens=800
    )
    if raw_text is None:
        return None
    parsed = _tolerant_json(raw_text)
    if not isinstance(parsed, dict):
        return None

    status = (parsed.get("status") or "").strip().lower()
    if status not in GOAL_STATUSES:
        return None
    confidence = (parsed.get("confidence") or "medium").strip().lower()
    if confidence not in GOAL_CONFIDENCES:
        confidence = "medium"

    actual = parsed.get("actual_value")
    try:
        actual_val = float(actual) if actual is not None else None
    except (TypeError, ValueError):
        actual_val = None

    return {
        "status": status,
        "actual_value": actual_val,
        "narrative": (parsed.get("narrative") or "")[:1000] or None,
        "evidence_quote": (parsed.get("evidence_quote") or "")[:1000] or None,
        "confidence": confidence,
        "assessment_method": "llm",
    }


# ---------------------------------------------------------------------------
# Pass B — Orchestration
# ---------------------------------------------------------------------------


def assess_goal_progress(
    db: Session,
    company: Company,
    goal: CompanyGoal,
    assess_year: int,
    *,
    skip_if_exists: bool = True,
    allow_llm_fallback: bool = True,
) -> dict[str, Any]:
    """Assess one goal against one later fiscal year.

    Tries mechanical evaluation first (free + reproducible); falls back to
    LLM if requested and a cached PDF exists. Upserts into
    ``company_goal_progress``.
    """
    if assess_year <= goal.fiscal_year_set:
        return {
            "status": "skipped",
            "reason": "assess_year must be after fiscal_year_set",
        }

    if skip_if_exists:
        existing = (
            db.query(CompanyGoalProgress)
            .filter(
                CompanyGoalProgress.goal_id == goal.id,
                CompanyGoalProgress.assessed_in_fiscal_year == assess_year,
            )
            .first()
        )
        if existing is not None:
            return {
                "status": "skipped_existing",
                "goal_id": goal.id,
                "assess_year": assess_year,
            }

    assessment = _mechanical_assessment(db, goal, assess_year)
    if assessment is None and allow_llm_fallback:
        assessment = _llm_assessment(company, goal, assess_year)

    if assessment is None:
        return {
            "status": "no_assessment",
            "goal_id": goal.id,
            "assess_year": assess_year,
            "reason": "no mechanical path and LLM unavailable / disabled",
        }

    progress = CompanyGoalProgress(
        goal_id=goal.id,
        assessed_in_fiscal_year=assess_year,
        status=assessment["status"],
        actual_value=assessment.get("actual_value"),
        narrative=assessment.get("narrative"),
        evidence_quote=assessment.get("evidence_quote"),
        confidence=assessment["confidence"],
        assessment_method=assessment["assessment_method"],
    )
    db.add(progress)
    db.commit()

    return {
        "status": "success",
        "goal_id": goal.id,
        "assess_year": assess_year,
        "method": assessment["assessment_method"],
        "result_status": assessment["status"],
    }


def assess_all_goals_for_company(
    db: Session,
    company: Company,
    *,
    allow_llm_fallback: bool = True,
    pace_seconds: float = 60.0,
) -> dict[str, Any]:
    """For every stored goal of ``company``, run progress assessment for
    every fiscal year between (goal.fiscal_year_set + 1) and the latest
    fiscal year for which we have either a FinancialStatement row or a
    cached PDF.

    Mechanical assessments don't pace; only LLM calls trigger the sleep.
    """
    goals = (
        db.query(CompanyGoal)
        .filter(CompanyGoal.company_id == company.id)
        .order_by(CompanyGoal.fiscal_year_set, CompanyGoal.id)
        .all()
    )

    latest_fin = (
        db.query(FinancialStatement.fiscal_year)
        .filter(FinancialStatement.company_id == company.id)
        .order_by(FinancialStatement.fiscal_year.desc())
        .first()
    )
    latest_year = latest_fin[0] if latest_fin else None

    summary = {
        "ticker": company.ticker_symbol,
        "goals_total": len(goals),
        "assessments_inserted": 0,
        "assessments_skipped": 0,
        "llm_calls": 0,
        "mechanical_calls": 0,
        "errors": [],
    }

    for goal in goals:
        # Don't assess past the goal's horizon if known; otherwise stop at latest_year.
        end_year = goal.target_horizon_year or latest_year
        if end_year is None:
            continue

        for year in range(goal.fiscal_year_set + 1, end_year + 1):
            try:
                result = assess_goal_progress(
                    db,
                    company,
                    goal,
                    year,
                    skip_if_exists=True,
                    allow_llm_fallback=allow_llm_fallback,
                )
            except Exception as e:
                logger.error(
                    "Failed to assess goal %d for FY%d: %s", goal.id, year, e
                )
                summary["errors"].append(
                    {"goal_id": goal.id, "year": year, "error": str(e)}
                )
                continue

            if result.get("status") == "skipped_existing":
                summary["assessments_skipped"] += 1
                continue
            if result.get("status") != "success":
                continue

            summary["assessments_inserted"] += 1
            if result.get("method") == "llm":
                summary["llm_calls"] += 1
                # Pace LLM calls only.
                if pace_seconds > 0:
                    time.sleep(pace_seconds)
            else:
                summary["mechanical_calls"] += 1

    return summary
