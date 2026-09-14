"""Schemas for per-company AI analysis (auto-generated research narrative)."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class CompanyAIAnalysisResponse(BaseModel):
    """Full analysis payload returned to the frontend."""

    id: int
    company_id: int
    generated_at: datetime
    model_name: str
    prompt_version: str
    input_fingerprint: str
    sector_kind: str | None = None
    narrative_md: str
    structured_json: dict[str, Any] | None = None
    triggered_by: str
    # Whether this row was served from cache on this request (True) or
    # regenerated (False). Purely informational for the UI.
    from_cache: bool = False

    # ``model_name`` collides with Pydantic's protected ``model_`` namespace.
    # We keep the field name for API clarity and disable the protection.
    model_config = {"from_attributes": True, "protected_namespaces": ()}


class CompanyAIAnalysisRefreshRequest(BaseModel):
    """Body for the manual-refresh endpoint.

    ``force`` bypasses the fingerprint cache. Callers should use it
    sparingly — it always spends an LLM call.
    """

    force: bool = Field(
        default=False,
        description="Skip the fingerprint cache and always regenerate.",
    )
