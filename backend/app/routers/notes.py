"""Notes router — CRUD for per-company user notes."""

from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user_id
from app.models.company_note import CompanyNote
from app.schemas.notes import NoteCreate, NoteUpdate, NoteResponse

router = APIRouter(prefix="/api/stocks/companies/{company_id}/notes", tags=["notes"])


@router.get("", response_model=list[NoteResponse])
def list_notes(
    company_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """List all notes for a company belonging to the current user."""
    return (
        db.query(CompanyNote)
        .filter(CompanyNote.company_id == company_id, CompanyNote.user_id == user_id)
        .order_by(CompanyNote.updated_at.desc())
        .all()
    )


@router.post("", response_model=NoteResponse, status_code=status.HTTP_201_CREATED)
def create_note(
    company_id: int,
    payload: NoteCreate,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """Create a new note for a company."""
    note = CompanyNote(
        company_id=company_id,
        user_id=user_id,
        note_text=payload.note_text,
        tag=payload.tag,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(note)
    db.commit()
    db.refresh(note)
    return note


@router.put("/{note_id}", response_model=NoteResponse)
def update_note(
    company_id: int,
    note_id: int,
    payload: NoteUpdate,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """Update an existing note."""
    note = _get_user_note(db, note_id, company_id, user_id)
    if payload.note_text is not None:
        note.note_text = payload.note_text
    if payload.tag is not None:
        note.tag = payload.tag
    note.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(note)
    return note


@router.delete("/{note_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_note(
    company_id: int,
    note_id: int,
    db: Session = Depends(get_db),
    user_id: int = Depends(get_current_user_id),
):
    """Delete a note."""
    note = _get_user_note(db, note_id, company_id, user_id)
    db.delete(note)
    db.commit()


def _get_user_note(db: Session, note_id: int, company_id: int, user_id: int) -> CompanyNote:
    note = (
        db.query(CompanyNote)
        .filter(
            CompanyNote.id == note_id,
            CompanyNote.company_id == company_id,
            CompanyNote.user_id == user_id,
        )
        .first()
    )
    if not note:
        raise HTTPException(status_code=404, detail="Note not found")
    return note
