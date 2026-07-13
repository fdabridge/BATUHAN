"""
BATUHAN — Trainings Module: FastAPI Router.

Routes (all relative to /trainings):
  POST /courses                              — create a training course
  GET  /courses                              — list all courses
  PUT  /courses/{course_id}                  — update a course
  POST /courses/{course_id}/upload-material  — upload training PDF
  POST /courses/{course_id}/upload-exam-file — upload exam display PDF
  POST /courses/{course_id}/questions        — create/replace answer key
  POST /courses/{course_id}/assign           — assign training to users
  GET  /courses/{course_id}/assignments      — view assignments/results
  GET  /courses/{course_id}/questions        — get exam questions
  GET  /courses/{course_id}/material         — download training material
  GET  /courses/{course_id}/exam-file        — download exam display file
  GET  /my                                   — list my assigned trainings
  POST /assignments/{id}/complete-training   — mark training completed
  POST /assignments/{id}/submit-exam         — submit exam answers
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from secrets import token_hex
from typing import Optional

import io

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from auth.dependencies import get_current_user, require_role
from auth.db_models import PlatformUser, get_db as get_auth_db
from storage.document_store import upload as store_upload, ensure_local
from trainings.models import (
    TrainingCourse,
    TrainingExamQuestion,
    TrainingAssignment,
    get_db,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/trainings", tags=["trainings"])

# Convenience dependency
require_training_officer = require_role("admin", "training_officer")


# ---------------------------------------------------------------------------
# Pydantic schemas
# ---------------------------------------------------------------------------

class CourseCreateRequest(BaseModel):
    title: str
    description: Optional[str] = None


class CourseUpdateRequest(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    passing_grade: Optional[int] = None
    is_active: Optional[bool] = None


class QuestionIn(BaseModel):
    question_number: int
    question_text: str
    options: list[str]
    correct_option_index: int


class QuestionsReplaceRequest(BaseModel):
    questions: list[QuestionIn]


class AssignRequest(BaseModel):
    user_ids: list[str]


class ExamAnswerIn(BaseModel):
    question_number: int
    selected_option_index: int


class ExamSubmitRequest(BaseModel):
    answers: list[ExamAnswerIn]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_course_or_404(db: Session, course_id: str) -> TrainingCourse:
    course = db.query(TrainingCourse).filter(TrainingCourse.id == course_id).first()
    if not course:
        raise HTTPException(status_code=404, detail="Course not found")
    return course


def _require_course_access(
    course_id: str, current_user: PlatformUser, db: Session,
) -> None:
    """Allow admin, training_officer, or a user assigned to this course."""
    if current_user.role in ("admin", "training_officer"):
        return
    assigned = (
        db.query(TrainingAssignment)
        .filter(
            TrainingAssignment.course_id == course_id,
            TrainingAssignment.user_id == current_user.id,
        )
        .first()
    )
    if not assigned:
        raise HTTPException(status_code=403, detail="Access denied — you are not assigned to this course")


# ---------------------------------------------------------------------------
# File-type helpers
# ---------------------------------------------------------------------------

MATERIAL_ALLOWED_EXTS = {".pdf", ".mp4", ".mov", ".webm", ".ppt", ".pptx", ".doc", ".docx"}
EXAM_ALLOWED_EXTS = {".pdf", ".doc", ".docx"}

def _classify_material(filename: str) -> str:
    ext = os.path.splitext(filename)[1].lower()
    if ext == ".pdf":
        return "pdf"
    if ext in (".mp4", ".mov", ".webm"):
        return "video"
    if ext in (".ppt", ".pptx", ".doc", ".docx"):
        return "office"
    return "other"

def _classify_exam(filename: str) -> str:
    ext = os.path.splitext(filename)[1].lower()
    if ext == ".pdf":
        return "pdf"
    if ext in (".doc", ".docx"):
        return "office"
    return "other"

def _validate_ext(filename: str, allowed: set[str], label: str) -> None:
    ext = os.path.splitext(filename)[1].lower()
    if ext not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported {label} file type '{ext}'. Allowed: {', '.join(sorted(allowed))}",
        )


def _get_usage(db: Session, course_id: str) -> dict:
    """Return usage counts for a course."""
    assignments = db.query(TrainingAssignment).filter(TrainingAssignment.course_id == course_id).all()
    return {
        "assigned_count": len(assignments),
        "training_completed_count": sum(1 for a in assignments if a.training_completed),
        "exam_completed_count": sum(1 for a in assignments if a.exam_completed),
    }


def _check_readiness(course: TrainingCourse, question_count: int) -> list[str]:
    """Return list of missing requirements. Empty list means course is ready."""
    missing: list[str] = []
    if not course.file_path:
        missing.append("Training material not uploaded")
    if not course.exam_file_path:
        missing.append("Exam file not uploaded")
    if question_count < 1:
        missing.append("No exam questions")
    pg = course.passing_grade
    if pg is None or pg < 0 or pg > 100:
        missing.append("Passing grade must be 0–100")
    if not course.is_active:
        missing.append("Course is inactive")
    return missing


def _course_to_dict(
    course: TrainingCourse,
    question_count: int = 0,
    usage: dict | None = None,
) -> dict:
    missing = _check_readiness(course, question_count)
    u = usage or {"assigned_count": 0, "training_completed_count": 0, "exam_completed_count": 0}
    return {
        "id": course.id,
        "title": course.title,
        "description": course.description,
        "file_path": course.file_path,
        "material_file_name": course.material_file_name,
        "material_content_type": course.material_content_type,
        "material_kind": course.material_kind,
        "exam_file_path": course.exam_file_path,
        "exam_file_name": course.exam_file_name,
        "exam_content_type": course.exam_content_type,
        "exam_kind": course.exam_kind,
        "passing_grade": course.passing_grade,
        "is_active": course.is_active,
        "is_ready": len(missing) == 0,
        "missing_requirements": missing,
        "created_by": course.created_by,
        "created_at": course.created_at.isoformat() if course.created_at else None,
        "updated_at": course.updated_at.isoformat() if course.updated_at else None,
        "question_count": question_count,
        "assigned_count": u["assigned_count"],
        "training_completed_count": u["training_completed_count"],
        "exam_completed_count": u["exam_completed_count"],
    }


# ---------------------------------------------------------------------------
# Training Officer endpoints
# ---------------------------------------------------------------------------

@router.post("/courses")
def create_course(
    payload: CourseCreateRequest,
    current_user: PlatformUser = Depends(require_training_officer),
    db: Session = Depends(get_db),
):
    course = TrainingCourse(
        title=payload.title,
        description=payload.description,
        created_by=current_user.id,
    )
    db.add(course)
    db.commit()
    db.refresh(course)
    logger.info("[Trainings] Course created id=%s title='%s' by=%s", course.id, course.title, current_user.id)
    return _course_to_dict(course)


@router.get("/courses")
def list_courses(
    current_user: PlatformUser = Depends(require_training_officer),
    db: Session = Depends(get_db),
):
    courses = db.query(TrainingCourse).order_by(TrainingCourse.created_at.desc()).all()
    # Batch-load assignment stats per course (single query, no N+1)
    all_assignments = db.query(TrainingAssignment).all()
    stats: dict[str, dict] = {}
    for a in all_assignments:
        s = stats.setdefault(a.course_id, {
            "assigned_count": 0, "training_completed_count": 0,
            "exam_completed_count": 0, "passed": 0, "failed": 0,
        })
        s["assigned_count"] += 1
        if a.training_completed:
            s["training_completed_count"] += 1
        if a.exam_completed:
            s["exam_completed_count"] += 1
        if a.exam_passed is True:
            s["passed"] += 1
        elif a.exam_passed is False:
            s["failed"] += 1
    _empty_stats = {
        "assigned_count": 0, "training_completed_count": 0,
        "exam_completed_count": 0, "passed": 0, "failed": 0,
    }
    result = []
    for c in courses:
        q_count = db.query(TrainingExamQuestion).filter(TrainingExamQuestion.course_id == c.id).count()
        cs = stats.get(c.id, _empty_stats)
        usage = {
            "assigned_count": cs["assigned_count"],
            "training_completed_count": cs["training_completed_count"],
            "exam_completed_count": cs["exam_completed_count"],
        }
        d = _course_to_dict(c, question_count=q_count, usage=usage)
        d["assignment_count"] = cs["assigned_count"]
        d["passed_count"] = cs["passed"]
        d["failed_count"] = cs["failed"]
        result.append(d)
    return result


@router.get("/summary")
def training_summary(
    current_user: PlatformUser = Depends(require_training_officer),
    db: Session = Depends(get_db),
):
    """Aggregate stats for the training officer dashboard."""
    total_courses = db.query(TrainingCourse).count()
    active_courses = db.query(TrainingCourse).filter(TrainingCourse.is_active.is_(True)).count()
    all_assignments = db.query(TrainingAssignment).all()
    total_assignments = len(all_assignments)
    pending_training = sum(1 for a in all_assignments if not a.training_completed)
    training_done_exam_pending = sum(
        1 for a in all_assignments if a.training_completed and not a.exam_completed
    )
    passed_count = sum(1 for a in all_assignments if a.exam_passed is True)
    failed_count = sum(1 for a in all_assignments if a.exam_passed is False)
    return {
        "total_courses": total_courses,
        "active_courses": active_courses,
        "total_assignments": total_assignments,
        "pending_training": pending_training,
        "training_completed_exam_pending": training_done_exam_pending,
        "passed_count": passed_count,
        "failed_count": failed_count,
    }


@router.get("/users/{user_id}/history")
def user_training_history(
    user_id: str,
    current_user: PlatformUser = Depends(require_training_officer),
    db: Session = Depends(get_db),
):
    """Return all training assignments for a given user, with course details."""
    assignments = (
        db.query(TrainingAssignment)
        .filter(TrainingAssignment.user_id == user_id)
        .order_by(TrainingAssignment.assigned_at.desc())
        .all()
    )
    course_ids = list({a.course_id for a in assignments})
    courses_map: dict[str, TrainingCourse] = {}
    if course_ids:
        courses = db.query(TrainingCourse).filter(TrainingCourse.id.in_(course_ids)).all()
        courses_map = {c.id: c for c in courses}
    result = []
    for a in assignments:
        course = courses_map.get(a.course_id)
        result.append({
            "id": a.id,
            "course_id": a.course_id,
            "course_title": course.title if course else "Unknown",
            "assigned_at": a.assigned_at.isoformat() if a.assigned_at else None,
            "training_completed": a.training_completed,
            "training_completed_at": a.training_completed_at.isoformat() if a.training_completed_at else None,
            "exam_completed": a.exam_completed,
            "exam_score": a.exam_score,
            "exam_passed": a.exam_passed,
            "exam_completed_at": a.exam_completed_at.isoformat() if a.exam_completed_at else None,
        })
    return result


@router.get("/assignable-users")
def assignable_users(
    current_user: PlatformUser = Depends(require_training_officer),
    auth_db: Session = Depends(get_auth_db),
):
    """Return active non-client users that can be assigned trainings."""
    excluded_roles = {"client"}
    users = (
        auth_db.query(PlatformUser)
        .filter(PlatformUser.is_active.is_(True))
        .order_by(PlatformUser.full_name)
        .all()
    )
    return [
        {"id": u.id, "full_name": u.full_name, "email": u.email, "role": u.role}
        for u in users
        if u.role not in excluded_roles
    ]


@router.get("/courses/{course_id}")
def get_course(
    course_id: str,
    current_user: PlatformUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    course = _get_course_or_404(db, course_id)
    _require_course_access(course_id, current_user, db)
    q_count = db.query(TrainingExamQuestion).filter(TrainingExamQuestion.course_id == course_id).count()
    usage = _get_usage(db, course_id)
    return _course_to_dict(course, question_count=q_count, usage=usage)


@router.put("/courses/{course_id}")
def update_course(
    course_id: str,
    payload: CourseUpdateRequest,
    current_user: PlatformUser = Depends(require_training_officer),
    db: Session = Depends(get_db),
):
    course = _get_course_or_404(db, course_id)
    usage = _get_usage(db, course_id)
    if payload.title is not None:
        course.title = payload.title
    if payload.description is not None:
        course.description = payload.description
    if payload.passing_grade is not None and payload.passing_grade != course.passing_grade:
        if usage["exam_completed_count"] > 0:
            raise HTTPException(
                status_code=400,
                detail="Passing grade cannot be changed after users have completed the exam.",
            )
        course.passing_grade = payload.passing_grade
    if payload.is_active is not None:
        course.is_active = payload.is_active
    db.commit()
    db.refresh(course)
    logger.info("[Trainings] Course updated id=%s by=%s", course.id, current_user.id)
    return _course_to_dict(course)


@router.post("/courses/{course_id}/upload-material")
async def upload_material(
    course_id: str,
    file: UploadFile = File(...),
    current_user: PlatformUser = Depends(require_training_officer),
    db: Session = Depends(get_db),
):
    course = _get_course_or_404(db, course_id)
    usage = _get_usage(db, course_id)
    if usage["training_completed_count"] > 0:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot replace training material — {usage['training_completed_count']} user(s) have already completed training",
        )
    filename = file.filename or "material.bin"
    _validate_ext(filename, MATERIAL_ALLOWED_EXTS, "training material")
    content = await file.read()
    ct = file.content_type or "application/octet-stream"
    kind = _classify_material(filename)
    rel_path = f"training_materials/{course_id}/{token_hex(8)}_{filename}"
    ref = store_upload(rel_path, content, content_type=ct)
    course.file_path = ref
    course.material_file_name = filename
    course.material_content_type = ct
    course.material_kind = kind
    db.commit()
    db.refresh(course)
    logger.info("[Trainings] Material uploaded (%s) for course=%s by=%s", kind, course_id, current_user.id)
    return {"file_path": ref, "material_kind": kind, "material_file_name": filename}


@router.post("/courses/{course_id}/upload-exam-file")
async def upload_exam_file(
    course_id: str,
    file: UploadFile = File(...),
    current_user: PlatformUser = Depends(require_training_officer),
    db: Session = Depends(get_db),
):
    course = _get_course_or_404(db, course_id)
    usage = _get_usage(db, course_id)
    if usage["exam_completed_count"] > 0:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot replace exam file — {usage['exam_completed_count']} user(s) have already completed the exam",
        )
    filename = file.filename or "exam.bin"
    _validate_ext(filename, EXAM_ALLOWED_EXTS, "exam")
    content = await file.read()
    ct = file.content_type or "application/octet-stream"
    kind = _classify_exam(filename)
    rel_path = f"training_exams/{course_id}/{token_hex(8)}_{filename}"
    ref = store_upload(rel_path, content, content_type=ct)
    course.exam_file_path = ref
    course.exam_file_name = filename
    course.exam_content_type = ct
    course.exam_kind = kind
    db.commit()
    db.refresh(course)
    logger.info("[Trainings] Exam file uploaded (%s) for course=%s by=%s", kind, course_id, current_user.id)
    return {"exam_file_path": ref, "exam_kind": kind, "exam_file_name": filename}


@router.post("/courses/{course_id}/questions")
def replace_questions(
    course_id: str,
    payload: QuestionsReplaceRequest,
    current_user: PlatformUser = Depends(require_training_officer),
    db: Session = Depends(get_db),
):
    _get_course_or_404(db, course_id)
    usage = _get_usage(db, course_id)
    if usage["exam_completed_count"] > 0:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot change answer key — {usage['exam_completed_count']} user(s) have already completed the exam",
        )

    # Validate questions before persisting
    errors: list[str] = []
    seen_numbers: set[int] = set()
    for i, q in enumerate(payload.questions, 1):
        label = f"Q{i}"
        if not q.question_text.strip():
            errors.append(f"{label}: question text is blank")
        non_empty = [o for o in q.options if o.strip()]
        if len(non_empty) < 2:
            errors.append(f"{label}: at least 2 non-empty options required (got {len(non_empty)})")
        if q.correct_option_index < 0 or q.correct_option_index >= len(q.options):
            errors.append(f"{label}: correct_option_index {q.correct_option_index} out of range")
        elif not q.options[q.correct_option_index].strip():
            errors.append(f"{label}: correct answer option is blank")
        if q.question_number in seen_numbers:
            errors.append(f"{label}: duplicate question_number {q.question_number}")
        seen_numbers.add(q.question_number)
    if errors:
        raise HTTPException(status_code=400, detail=f"Invalid questions: {'; '.join(errors)}")

    # Normalize question numbers to sequential 1..N
    for idx, q in enumerate(payload.questions):
        q.question_number = idx + 1

    # Delete existing questions for this course
    db.query(TrainingExamQuestion).filter(TrainingExamQuestion.course_id == course_id).delete()
    # Insert new questions — recompute correct index after trimming blanks
    for q in payload.questions:
        slots = [(i, o.strip()) for i, o in enumerate(q.options)]
        filtered = [(i, t) for i, t in slots if t]
        # Map original correct_option_index to position in filtered list
        new_idx = next(
            (pos for pos, (orig_i, _) in enumerate(filtered) if orig_i == q.correct_option_index),
            None,
        )
        if new_idx is None:
            raise HTTPException(
                status_code=400,
                detail=f"Q{q.question_number}: correct option (index {q.correct_option_index}) is blank after trimming",
            )
        question = TrainingExamQuestion(
            course_id=course_id,
            question_number=q.question_number,
            question_text=q.question_text.strip(),
            options=json.dumps([t for _, t in filtered]),
            correct_option_index=new_idx,
        )
        db.add(question)
    db.commit()
    logger.info(
        "[Trainings] Questions replaced for course=%s count=%d by=%s",
        course_id, len(payload.questions), current_user.id,
    )
    return {"course_id": course_id, "question_count": len(payload.questions)}


@router.post("/courses/{course_id}/assign")
def assign_training(
    course_id: str,
    payload: AssignRequest,
    current_user: PlatformUser = Depends(require_training_officer),
    db: Session = Depends(get_db),
):
    course = _get_course_or_404(db, course_id)
    q_count = db.query(TrainingExamQuestion).filter(TrainingExamQuestion.course_id == course_id).count()
    missing = _check_readiness(course, q_count)
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"Course is not ready for assignment. Missing: {'; '.join(missing)}",
        )
    new_count = 0
    for uid in payload.user_ids:
        existing = (
            db.query(TrainingAssignment)
            .filter(
                TrainingAssignment.course_id == course_id,
                TrainingAssignment.user_id == uid,
            )
            .first()
        )
        if existing:
            continue
        assignment = TrainingAssignment(
            course_id=course_id,
            user_id=uid,
            assigned_by=current_user.id,
        )
        db.add(assignment)
        new_count += 1
    db.commit()
    logger.info(
        "[Trainings] Assigned course=%s to %d new users by=%s",
        course_id, new_count, current_user.id,
    )
    return {"course_id": course_id, "new_assignments": new_count}


@router.get("/courses/{course_id}/assignments")
def get_course_assignments(
    course_id: str,
    current_user: PlatformUser = Depends(require_training_officer),
    db: Session = Depends(get_db),
    auth_db: Session = Depends(get_auth_db),
):
    _get_course_or_404(db, course_id)
    assignments = (
        db.query(TrainingAssignment)
        .filter(TrainingAssignment.course_id == course_id)
        .order_by(TrainingAssignment.assigned_at.desc())
        .all()
    )
    # Collect user IDs and look up names/email/role from auth DB
    user_ids = list({a.user_id for a in assignments})
    users_map: dict[str, PlatformUser] = {}
    if user_ids:
        users = auth_db.query(PlatformUser).filter(PlatformUser.id.in_(user_ids)).all()
        users_map = {u.id: u for u in users}

    result = []
    for a in assignments:
        u = users_map.get(a.user_id)
        result.append({
            "id": a.id,
            "course_id": a.course_id,
            "user_id": a.user_id,
            "user_full_name": u.full_name if u else "Unknown",
            "user_email": u.email if u else None,
            "user_role": u.role if u else None,
            "assigned_by": a.assigned_by,
            "training_completed": a.training_completed,
            "training_completed_at": a.training_completed_at.isoformat() if a.training_completed_at else None,
            "exam_completed": a.exam_completed,
            "exam_score": a.exam_score,
            "exam_passed": a.exam_passed,
            "exam_completed_at": a.exam_completed_at.isoformat() if a.exam_completed_at else None,
            "assigned_at": a.assigned_at.isoformat() if a.assigned_at else None,
        })
    return result


@router.get("/assignments/{assignment_id}/answers")
def get_exam_answers(
    assignment_id: str,
    current_user: PlatformUser = Depends(require_training_officer),
    db: Session = Depends(get_db),
):
    """Return the submitted answers for a completed exam, with correct answers for comparison."""
    assignment = db.query(TrainingAssignment).filter(TrainingAssignment.id == assignment_id).first()
    if not assignment:
        raise HTTPException(status_code=404, detail="Assignment not found")
    if not assignment.exam_completed:
        raise HTTPException(status_code=400, detail="Exam has not been completed for this assignment")

    submitted: list[dict] = json.loads(assignment.exam_answers) if assignment.exam_answers else []
    submitted_map = {a["question_number"]: a["selected_option_index"] for a in submitted}

    questions = (
        db.query(TrainingExamQuestion)
        .filter(TrainingExamQuestion.course_id == assignment.course_id)
        .order_by(TrainingExamQuestion.question_number)
        .all()
    )

    result = []
    for q in questions:
        opts = json.loads(q.options)
        selected = submitted_map.get(q.question_number)
        result.append({
            "question_number": q.question_number,
            "question_text": q.question_text,
            "options": opts,
            "correct_option_index": q.correct_option_index,
            "selected_option_index": selected,
            "is_correct": selected == q.correct_option_index if selected is not None else False,
        })
    return {
        "assignment_id": assignment_id,
        "exam_score": assignment.exam_score,
        "exam_passed": assignment.exam_passed,
        "questions": result,
    }


@router.get("/courses/{course_id}/assignments/export")
def export_assignments_csv(
    course_id: str,
    current_user: PlatformUser = Depends(require_training_officer),
    db: Session = Depends(get_db),
    auth_db: Session = Depends(get_auth_db),
):
    """Export course assignment results as CSV."""
    course = _get_course_or_404(db, course_id)
    assignments = (
        db.query(TrainingAssignment)
        .filter(TrainingAssignment.course_id == course_id)
        .order_by(TrainingAssignment.assigned_at.desc())
        .all()
    )
    user_ids = list({a.user_id for a in assignments})
    users_map: dict[str, PlatformUser] = {}
    if user_ids:
        users = auth_db.query(PlatformUser).filter(PlatformUser.id.in_(user_ids)).all()
        users_map = {u.id: u for u in users}

    import csv
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow([
        "User Name", "Email", "Role",
        "Training Status", "Training Completed Date",
        "Exam Status", "Score", "Pass/Fail", "Exam Completed Date",
    ])
    for a in assignments:
        u = users_map.get(a.user_id)
        writer.writerow([
            u.full_name if u else "Unknown",
            u.email if u else "",
            u.role if u else "",
            "Completed" if a.training_completed else "Pending",
            a.training_completed_at.isoformat() if a.training_completed_at else "",
            "Completed" if a.exam_completed else "Pending",
            f"{a.exam_score}" if a.exam_score is not None else "",
            "Passed" if a.exam_passed is True else ("Failed" if a.exam_passed is False else ""),
            a.exam_completed_at.isoformat() if a.exam_completed_at else "",
        ])
    buf.seek(0)
    safe_title = course.title.replace(" ", "_")[:30]
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="training_{safe_title}_results.csv"'},
    )


@router.delete("/assignments/{assignment_id}")
def unassign_user(
    assignment_id: str,
    current_user: PlatformUser = Depends(require_training_officer),
    db: Session = Depends(get_db),
):
    """Remove assignment only if user has not started training or exam."""
    assignment = db.query(TrainingAssignment).filter(TrainingAssignment.id == assignment_id).first()
    if not assignment:
        raise HTTPException(status_code=404, detail="Assignment not found")
    if assignment.training_completed or assignment.exam_completed:
        raise HTTPException(
            status_code=400,
            detail="Cannot unassign — user has already completed training or exam. Results are preserved.",
        )
    db.delete(assignment)
    db.commit()
    logger.info("[Trainings] Assignment removed id=%s by=%s", assignment_id, current_user.id)
    return {"status": "removed", "assignment_id": assignment_id}


# ---------------------------------------------------------------------------
# User / Auditor endpoints (any authenticated user)
# ---------------------------------------------------------------------------

@router.get("/my/counts")
def my_training_counts(
    current_user: PlatformUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Lightweight counts for sidebar badges."""
    assignments = (
        db.query(TrainingAssignment)
        .filter(TrainingAssignment.user_id == current_user.id)
        .all()
    )
    pending = sum(1 for a in assignments if not a.training_completed)
    exam_ready = sum(1 for a in assignments if a.training_completed and not a.exam_completed)
    return {"pending_training": pending, "exam_ready": exam_ready, "total": pending + exam_ready}


@router.get("/my")
def my_trainings(
    current_user: PlatformUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    assignments = (
        db.query(TrainingAssignment)
        .filter(TrainingAssignment.user_id == current_user.id)
        .order_by(TrainingAssignment.assigned_at.desc())
        .all()
    )
    # Join with course info
    course_ids = list({a.course_id for a in assignments})
    courses_map: dict[str, TrainingCourse] = {}
    if course_ids:
        courses = db.query(TrainingCourse).filter(TrainingCourse.id.in_(course_ids)).all()
        courses_map = {c.id: c for c in courses}

    result = []
    for a in assignments:
        course = courses_map.get(a.course_id)
        result.append({
            "id": a.id,
            "course_id": a.course_id,
            "course_title": course.title if course else "Unknown",
            "course_description": course.description if course else None,
            "training_completed": a.training_completed,
            "training_completed_at": a.training_completed_at.isoformat() if a.training_completed_at else None,
            "exam_completed": a.exam_completed,
            "exam_score": a.exam_score,
            "exam_passed": a.exam_passed,
            "exam_completed_at": a.exam_completed_at.isoformat() if a.exam_completed_at else None,
            "assigned_at": a.assigned_at.isoformat() if a.assigned_at else None,
        })
    return result


@router.get("/courses/{course_id}/material")
def download_material(
    course_id: str,
    current_user: PlatformUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    course = _get_course_or_404(db, course_id)
    _require_course_access(course_id, current_user, db)
    if not course.file_path:
        raise HTTPException(status_code=404, detail="No training material uploaded for this course")
    local_path = ensure_local(course.file_path)
    dl_name = course.material_file_name or f"training_material_{course_id}"
    media = course.material_content_type or "application/octet-stream"
    return FileResponse(local_path, filename=dl_name, media_type=media)


@router.get("/courses/{course_id}/exam-file")
def download_exam_file(
    course_id: str,
    current_user: PlatformUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    course = _get_course_or_404(db, course_id)
    _require_course_access(course_id, current_user, db)
    if not course.exam_file_path:
        raise HTTPException(status_code=404, detail="No exam file uploaded for this course")
    local_path = ensure_local(course.exam_file_path)
    dl_name = course.exam_file_name or f"exam_{course_id}"
    media = course.exam_content_type or "application/octet-stream"
    return FileResponse(local_path, filename=dl_name, media_type=media)


@router.post("/assignments/{assignment_id}/complete-training")
def complete_training(
    assignment_id: str,
    current_user: PlatformUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    assignment = db.query(TrainingAssignment).filter(TrainingAssignment.id == assignment_id).first()
    if not assignment:
        raise HTTPException(status_code=404, detail="Assignment not found")
    if assignment.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="This assignment is not assigned to you")
    assignment.training_completed = True
    assignment.training_completed_at = datetime.utcnow()
    db.commit()
    db.refresh(assignment)
    logger.info("[Trainings] Training completed assignment=%s user=%s", assignment_id, current_user.id)
    return {"status": "training_completed", "assignment_id": assignment_id}


@router.post("/assignments/{assignment_id}/submit-exam")
def submit_exam(
    assignment_id: str,
    payload: ExamSubmitRequest,
    current_user: PlatformUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    assignment = db.query(TrainingAssignment).filter(TrainingAssignment.id == assignment_id).first()
    if not assignment:
        raise HTTPException(status_code=404, detail="Assignment not found")
    if assignment.user_id != current_user.id:
        raise HTTPException(status_code=403, detail="This assignment is not assigned to you")
    if not assignment.training_completed:
        raise HTTPException(status_code=400, detail="You must complete the training before taking the exam")
    if assignment.exam_completed:
        raise HTTPException(status_code=400, detail="Exam already submitted")

    # Fetch answer key for the course
    questions = (
        db.query(TrainingExamQuestion)
        .filter(TrainingExamQuestion.course_id == assignment.course_id)
        .all()
    )
    if not questions:
        raise HTTPException(status_code=400, detail="No exam questions configured for this course")

    # Build answer key map: question_number -> correct_option_index
    answer_key = {q.question_number: q.correct_option_index for q in questions}

    # Grade the exam
    total_questions = len(answer_key)
    correct_count = 0
    for ans in payload.answers:
        correct_idx = answer_key.get(ans.question_number)
        if correct_idx is not None and ans.selected_option_index == correct_idx:
            correct_count += 1

    score = (correct_count / total_questions) * 100 if total_questions > 0 else 0.0

    # Fetch passing grade from course
    course = db.query(TrainingCourse).filter(TrainingCourse.id == assignment.course_id).first()
    passing_grade = course.passing_grade if course else 70

    passed = score >= passing_grade

    # Persist submitted answers for audit trail
    assignment.exam_answers = json.dumps([
        {"question_number": a.question_number, "selected_option_index": a.selected_option_index}
        for a in payload.answers
    ])
    assignment.exam_completed = True
    assignment.exam_score = round(score, 2)
    assignment.exam_passed = passed
    assignment.exam_completed_at = datetime.utcnow()
    db.commit()
    db.refresh(assignment)

    logger.info(
        "[Trainings] Exam submitted assignment=%s user=%s score=%.1f passed=%s",
        assignment_id, current_user.id, score, passed,
    )
    return {
        "score": round(score, 2),
        "passed": passed,
        "passing_grade": passing_grade,
        "total_questions": total_questions,
        "correct_count": correct_count,
    }


@router.get("/courses/{course_id}/questions")
def get_questions(
    course_id: str,
    current_user: PlatformUser = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _get_course_or_404(db, course_id)

    is_officer = current_user.role in ("admin", "training_officer")

    # Non-officer users must have an assignment for this course
    if not is_officer:
        assignment = (
            db.query(TrainingAssignment)
            .filter(
                TrainingAssignment.course_id == course_id,
                TrainingAssignment.user_id == current_user.id,
            )
            .first()
        )
        if not assignment:
            raise HTTPException(status_code=403, detail="You are not assigned to this course")

    questions = (
        db.query(TrainingExamQuestion)
        .filter(TrainingExamQuestion.course_id == course_id)
        .order_by(TrainingExamQuestion.question_number)
        .all()
    )

    result = []
    for q in questions:
        item = {
            "id": q.id,
            "course_id": q.course_id,
            "question_number": q.question_number,
            "question_text": q.question_text,
            "options": json.loads(q.options),
        }
        if is_officer:
            item["correct_option_index"] = q.correct_option_index
        result.append(item)

    return result
