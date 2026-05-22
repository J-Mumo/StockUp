"""Company AI chat endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.dependencies import get_current_user
from app.models.user import User
from app.models.company_chat import CompanyChat
from app.config import get_settings
from app.schemas.company_chat import (
    CompanyChatRequest,
    CompanyChatResponse,
    ChatHistorySaveRequest,
    ChatHistoryResponse,
    ChatHistoryItem,
)
from app.services.company_chat_service import ask_company_chat
from app.utils.rate_limit import check_rate_limit

router = APIRouter(
    prefix="/api/stocks/companies",
    tags=["Company Chat"],
)

settings = get_settings()


@router.post("/{company_id}/chat", response_model=CompanyChatResponse)
def company_chat(
    company_id: int,
    payload: CompanyChatRequest,
    response: Response,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    limit_key = f"rate:company-chat:user:{current_user.id}"
    limit = check_rate_limit(
        key=limit_key,
        max_requests=settings.ai_chat_rate_limit_requests,
        window_seconds=settings.ai_chat_rate_limit_window_seconds,
    )
    if not limit.allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=(
                "AI chat rate limit exceeded. "
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
    response.headers["X-RateLimit-Window"] = str(settings.ai_chat_rate_limit_window_seconds)

    try:
        answer, ticker, validation, context_meta = ask_company_chat(
            db=db,
            company_id=company_id,
            user_id=current_user.id,
            question=payload.question,
            history=payload.history,
            verify_online=payload.verify_online,
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to generate AI response: {str(exc)}",
        ) from exc

    return CompanyChatResponse(
        answer=answer,
        company_ticker=ticker,
        online_validation=validation,
        context_meta=context_meta,
    )


@router.post("/{company_id}/chat-history", response_model=dict)
def save_chat_history(
    company_id: int,
    payload: ChatHistorySaveRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Save chat messages to history."""
    db.query(CompanyChat).filter(
        CompanyChat.user_id == current_user.id,
        CompanyChat.company_id == company_id,
    ).delete()

    for msg in payload.messages:
        chat_record = CompanyChat(
            user_id=current_user.id,
            company_id=company_id,
            role=msg.role,
            content=msg.content,
        )
        db.add(chat_record)

    db.commit()
    return {"status": "saved", "count": len(payload.messages)}


@router.get("/{company_id}/chat-history", response_model=ChatHistoryResponse)
def get_chat_history(
    company_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Retrieve chat history for a company."""
    messages = (
        db.query(CompanyChat)
        .filter(
            CompanyChat.user_id == current_user.id,
            CompanyChat.company_id == company_id,
        )
        .order_by(CompanyChat.created_at)
        .all()
    )

    return ChatHistoryResponse(
        company_id=company_id,
        user_id=current_user.id,
        messages=[
            ChatHistoryItem(
                id=msg.id,
                role=msg.role,
                content=msg.content,
                created_at=msg.created_at,
            )
            for msg in messages
        ],
    )

