from __future__ import annotations

from datetime import datetime

import anthropic
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.session import get_db
from app.models.database import Analysis, AppLogSession, ChatMessage
from app.services.app_ai_engine import AppAIEngine

router = APIRouter()


class ChatHistoryMessage(BaseModel):
    role: str = Field(..., pattern=r"^(user|assistant)$")
    content: str = Field(..., min_length=1)


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    history: list[ChatHistoryMessage] = []


class ChatResponse(BaseModel):
    reply: str
    message_id: int


class ChatHistoryResponse(BaseModel):
    id: int
    role: str
    content: str
    created_at: datetime | None = None


def _latest_analysis_for_session(db: Session, session_id: int) -> Analysis | None:
    return (
        db.query(Analysis)
        .filter(Analysis.app_log_session_id == session_id)
        .order_by(Analysis.created_at.desc())
        .first()
    )


def _analysis_summary(analysis: Analysis) -> str:
    lines: list[str] = []
    if analysis.root_cause:
        lines.append(f"Root cause: {analysis.root_cause}")
    suggestions = analysis.suggestions or []
    if suggestions:
        lines.append("Suggestions:")
        for s in suggestions[:5]:
            lines.append(
                f"- {s.title} (function={s.target_function or 'n/a'}, "
                f"saving~{s.estimated_saving_ms}ms)"
            )
    return "\n".join(lines)


def _extract_text_response(response) -> str:
    chunks: list[str] = []
    for item in response.content:
        text = getattr(item, "text", None)
        if text:
            chunks.append(text)
    return "\n".join(chunks).strip()


@router.post("/app-logs/sessions/{session_id}/chat", response_model=ChatResponse)
def chat_with_session(
    session_id: int,
    payload: ChatRequest,
    db: Session = Depends(get_db),
):
    session = db.get(AppLogSession, session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    settings = get_settings()
    if not settings.ANTHROPIC_API_KEY:
        raise HTTPException(status_code=503, detail="ANTHROPIC_API_KEY not configured")

    analysis = _latest_analysis_for_session(db, session_id)
    context_prompt = AppAIEngine(db)._build_prompt(session)
    if analysis:
        summary = _analysis_summary(analysis)
        if summary:
            context_prompt = f"{context_prompt}\n\n## Latest analysis summary\n{summary}"

    messages_list = [{"role": m.role, "content": m.content} for m in payload.history]
    messages_list.append({"role": "user", "content": payload.message})

    client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
    response = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1024,
        system=(
            "You are an expert performance engineer. You have full context of this "
            "application log analysis session:\n"
            f"{context_prompt}\n"
            "Answer questions about the performance data concisely and specifically. "
            "Reference actual function names and timings from the context. If asked for "
            "code fixes, give real code. This context is unique to this specific "
            "repository/session and must not be mixed with other sessions."
        ),
        messages=messages_list,
    )
    reply_text = _extract_text_response(response)
    if not reply_text:
        raise HTTPException(status_code=502, detail="AI returned an empty response")

    user_row = ChatMessage(
        session_id=session_id,
        role="user",
        content=payload.message,
    )
    assistant_row = ChatMessage(
        session_id=session_id,
        role="assistant",
        content=reply_text,
    )
    db.add(user_row)
    db.add(assistant_row)
    db.commit()
    db.refresh(assistant_row)

    return ChatResponse(reply=reply_text, message_id=assistant_row.id)


@router.get(
    "/app-logs/sessions/{session_id}/chat/history",
    response_model=list[ChatHistoryResponse],
)
def get_chat_history(session_id: int, db: Session = Depends(get_db)):
    session = db.get(AppLogSession, session_id)
    if not session:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")

    rows = (
        db.query(ChatMessage)
        .filter(ChatMessage.session_id == session_id)
        .order_by(ChatMessage.created_at.asc(), ChatMessage.id.asc())
        .all()
    )
    return [
        ChatHistoryResponse(
            id=row.id,
            role=row.role,
            content=row.content,
            created_at=row.created_at,
        )
        for row in rows
    ]
