"""Pydantic schemas for company notes API."""

from datetime import datetime
from pydantic import BaseModel, Field


class NoteCreate(BaseModel):
    """Payload for creating a company note."""
    note_text: str = Field(..., min_length=1, max_length=5000)
    tag: str | None = Field(None, max_length=50)


class NoteUpdate(BaseModel):
    """Payload for updating a company note."""
    note_text: str | None = Field(None, min_length=1, max_length=5000)
    tag: str | None = None


class NoteResponse(BaseModel):
    """Company note response."""
    id: int
    company_id: int
    user_id: int
    note_text: str
    tag: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
