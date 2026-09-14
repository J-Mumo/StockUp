"""AI-generated per-company research narrative endpoints.

Endpoints:

* ``GET  /api/stocks/companies/{company_id}/ai-analysis`` — return the
  latest analysis, generating one on-demand if none exists (or if the
  input fingerprint has changed). This is the endpoint the company detail
  page hits on open.
* ``POST /api/stocks/companies/{company_id}/ai-analysis/refresh`` — force a
  regeneration. Rate-limited per user because it always spends an LLM call.
* ``GET  /api/stocks/companies/{company_id}/ai-analysis/history`` — recent
  historical analyses so the UI can show how the AI's view evolved.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import desc
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_db
from app.dependencies import get_current_user
from app.models.company_ai_analysis import CompanyAIAnalysis
from app.models.user import User
from app.schemas.company_ai_analysis import (
    CompanyAIAnalysisRefreshRequest,
    CompanyAIAnalysisResponse,
)
from app.services import company_ai_analysis_service
from app.utils.rate_limit import check_rate_limit

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/stocks/companies",
    tags=["Company AI Analysis"],
)

settings = get_settings()


def _to_response(
    row: CompanyAIAnalysis, from_cache: bool
) -> CompanyAIAnalysisResponse:
    return CompanyAIAnalysisResponse(
        id=row.id,
        company_id=row.company_id,
        generated_at=row.generated_at,
        model_name=row.model_name,
        prompt_version=row.prompt_version,
        input_fingerprint=row.input_fingerprint,
        sector_kind=row.sector_kind,
        narrative_md=row.narrative_md,
        structured_json=row.structured_json,
        triggered_by=row.triggered_by,
        from_cache=from_cache,
    )


@router.get(
    "/{company_id}/ai-analysis",
    response_model=CompanyAIAnalysisResponse,
)
def get_ai_analysis(
    company_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return the latest AI analysis, generating on-demand if needed.

    Serves cached analyses when the input fingerprint is unchanged — the
    common case for a page reload. Generates a fresh analysis when
    financials, valuation, sector, or the cached price bucket have moved.
    """
    try:
        row, decision = company_ai_analysis_service.get_or_generate_analysis(
            db=db,
            company_id=company_id,
            triggered_by="user_open",
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except Exception as exc:
        logger.exception("Failed to load/generate AI analysis for %s", company_id)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"AI analysis failed: {exc}",
        ) from exc

    return _to_response(row, from_cache=not decision.regenerate)


@router.post(
    "/{company_id}/ai-analysis/refresh",
    response_model=CompanyAIAnalysisResponse,
    status_code=status.HTTP_201_CREATED,
)
def refresh_ai_analysis(
    company_id: int,
    payload: CompanyAIAnalysisRefreshRequest,
    response: Response,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Force a regeneration. Rate-limited per user.

    Uses the same AI chat rate-limit bucket because both endpoints share
    the underlying LLM budget.
    """
    limit_key = f"rate:ai-analysis-refresh:user:{current_user.id}"
    limit = check_rate_limit(
        key=limit_key,
        max_requests=settings.ai_chat_rate_limit_requests,
        window_seconds=settings.ai_chat_rate_limit_window_seconds,
    )
    if not limit.allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                "AI analysis refresh rate limit exceeded. "
                f"Try again in about {limit.retry_after_seconds} seconds."
            ),
            headers={
                "Retry-After": str(limit.retry_after_seconds),
                "X-RateLimit-Limit": str(settings.ai_chat_rate_limit_requests),
                "X-RateLimit-Remaining": "0",
            },
        )

    response.headers["X-RateLimit-Limit"] = str(settings.ai_chat_rate_limit_requests)
    response.headers["X-RateLimit-Remaining"] = str(limit.remaining)

    try:
        row = company_ai_analysis_service.generate_analysis(
            db=db,
            company_id=company_id,
            triggered_by="manual",
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc
    except Exception as exc:
        logger.exception(
            "Failed to force-regenerate AI analysis for %s", company_id
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"AI analysis refresh failed: {exc}",
        ) from exc

    return _to_response(row, from_cache=False)


@router.get(
    "/{company_id}/ai-analysis/history",
    response_model=list[CompanyAIAnalysisResponse],
)
def list_ai_analysis_history(
    company_id: int,
    limit: int = Query(default=10, ge=1, le=50),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Recent historical analyses for this company (newest first)."""
    rows = (
        db.query(CompanyAIAnalysis)
        .filter(CompanyAIAnalysis.company_id == company_id)
        .order_by(desc(CompanyAIAnalysis.generated_at))
        .limit(limit)
        .all()
    )
    return [_to_response(r, from_cache=True) for r in rows]
