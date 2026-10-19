"""Authenticated API for Vera, Certiva's read-only assistant."""
from __future__ import annotations

from datetime import datetime, timedelta
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from audit_set.db_models import get_db as get_audit_db
from auth.db_models import PlatformUser, VeraUsageEvent, get_db as get_auth_db
from auth.dependencies import get_current_user
from config.settings import get_settings
from vera.knowledge import page_description
from vera.service import (
    answer_with_vera,
    build_case_snapshot,
    build_portal_snapshot,
    direct_portal_answer,
    record_usage,
    resolve_case,
)


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/vera", tags=["vera"])


class VeraHistoryItem(BaseModel):
    role: str
    content: str = Field(min_length=1, max_length=2_000)

    @field_validator("role")
    @classmethod
    def valid_role(cls, value: str) -> str:
        if value not in {"user", "assistant"}:
            raise ValueError("history role must be user or assistant")
        return value


class VeraQuestion(BaseModel):
    question: str = Field(min_length=1, max_length=1_200)
    pathname: str = Field(default="/", max_length=500)
    audit_set_id: str | None = Field(default=None, max_length=100)
    history: list[VeraHistoryItem] = Field(default_factory=list, max_length=8)

    @field_validator("question")
    @classmethod
    def clean_question(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("question cannot be empty")
        return value


def _questions_today(db: Session, user_id: str) -> int:
    since = datetime.utcnow() - timedelta(hours=24)
    return db.query(VeraUsageEvent).filter(
        VeraUsageEvent.user_id == user_id,
        VeraUsageEvent.created_at >= since,
    ).count()


@router.get("/context")
def get_vera_context(
    pathname: str = "/",
    audit_set_id: str | None = None,
    audit_db: Session = Depends(get_audit_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    """Return safe context labels and suggested questions; never modifies state."""
    audit_set = resolve_case(audit_set_id, current_user, audit_db)
    snapshot = build_case_snapshot(audit_set, current_user, audit_db) if audit_set else None
    suggestions = [
        "What can I do on this page?",
        "What should I do next?",
        "Explain the current workflow.",
    ]
    if snapshot:
        suggestions = [
            "What stage is this certification in?",
            "What should happen next?",
            "Are any document signatures outstanding?",
        ]
    elif "/certivai" in pathname or "/reports" in pathname:
        suggestions = [
            "How do I generate an AI report?",
            "Which documents should I provide?",
            "How do I review the result?",
        ]
    elif "/training" in pathname or "/trainings" in pathname:
        suggestions = [
            "How does an exam attempt work?",
            "How can I see a person's exam history?",
            "When can a failed training be reassigned?",
        ]
    elif current_user.role in {
        "admin", "planner", "planner_us", "officer", "executive",
        "gm", "certification_manager", "crm",
    } and pathname in {"/", "/dashboard", "/applications", "/clients"}:
        suggestions = [
            "How many applications are waiting for review?",
            "How many active ISO 9001 certificates do we have?",
            "Who signs FR.220?",
        ]
    return {
        "name": "Vera",
        "description": "Certiva's read-only workflow guide",
        "page": page_description(pathname),
        "has_case_context": snapshot is not None,
        "case_status": snapshot.get("status_title") if snapshot else None,
        "suggestions": suggestions,
    }


@router.post("/ask")
def ask_vera(
    payload: VeraQuestion,
    audit_db: Session = Depends(get_audit_db),
    auth_db: Session = Depends(get_auth_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    """Answer one question using only authorised, read-only portal context."""
    settings = get_settings()
    audit_set = resolve_case(payload.audit_set_id, current_user, audit_db)
    snapshot = build_case_snapshot(audit_set, current_user, audit_db) if audit_set else None
    portal_snapshot = build_portal_snapshot(
        question=payload.question,
        pathname=payload.pathname,
        user=current_user,
        db=audit_db,
    )
    used = _questions_today(auth_db, current_user.id)
    direct_answer = direct_portal_answer(payload.question, portal_snapshot)
    if direct_answer:
        return {
            "answer": direct_answer,
            "read_only": True,
            "case_status": snapshot.get("status_title") if snapshot else None,
            "remaining_today": max(settings.vera_daily_question_limit - used, 0),
            "source": "live_database",
        }
    if used >= settings.vera_daily_question_limit:
        raise HTTPException(
            429,
            "Vera's daily question limit has been reached for this account. Please try again later.",
        )
    try:
        answer, usage, model = answer_with_vera(
            question=payload.question,
            history=[item.model_dump() for item in payload.history],
            user=current_user,
            pathname=payload.pathname,
            snapshot=snapshot,
            portal_snapshot=portal_snapshot,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Vera response failed for user %s: %s", current_user.id, exc)
        raise HTTPException(503, "Vera is temporarily unavailable. Please try again shortly.") from exc

    try:
        record_usage(auth_db, current_user.id, model, usage)
    except Exception as exc:
        auth_db.rollback()
        logger.warning("Could not record Vera usage for user %s: %s", current_user.id, exc)

    return {
        "answer": answer,
        "read_only": True,
        "case_status": snapshot.get("status_title") if snapshot else None,
        "remaining_today": max(settings.vera_daily_question_limit - used - 1, 0),
    }
