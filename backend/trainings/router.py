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
from datetime import datetime
from secrets import token_hex
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import FileResponse
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


def _course_to_dict(course: TrainingCourse, question_count: int = 0) -> dict:
    return {
        "id": course.id,
        "title": course.title,
        "description": course.description,
        "file_path": course.file_path,
        "exam_file_path": course.exam_file_path,
        "passing_grade": course.passing_grade,
        "is_active": course.is_active,
        "created_by": course.created_by,
        "created_at": course.created_at.isoformat() if course.created_at else None,
        "updated_at": course.updated_at.isoformat() if course.updated_at else None,
        "question_count": question_count,
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
    result = []
    for c in courses:
        q_count = db.query(TrainingExamQuestion).filter(TrainingExamQuestion.course_id == c.id).count()
        result.append(_course_to_dict(c, question_count=q_count))
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
    return _course_to_dict(course, question_count=q_count)


@router.put("/courses/{course_id}")
def update_course(
    course_id: str,
    payload: CourseUpdateRequest,
    current_user: PlatformUser = Depends(require_training_officer),
    db: Session = Depends(get_db),
):
    course = _get_course_or_404(db, course_id)
    if payload.title is not None:
        course.title = payload.title
    if payload.description is not None:
        course.description = payload.description
    if payload.passing_grade is not None:
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
    content = await file.read()
    filename = file.filename or "material.pdf"
    rel_path = f"training_materials/{course_id}/{token_hex(8)}_{filename}"
    ref = store_upload(rel_path, content, content_type=file.content_type or "application/pdf")
    course.file_path = ref
    db.commit()
    db.refresh(course)
    logger.info("[Trainings] Material uploaded for course=%s by=%s", course_id, current_user.id)
    return {"file_path": ref}


@router.post("/courses/{course_id}/upload-exam-file")
async def upload_exam_file(
    course_id: str,
    file: UploadFile = File(...),
    current_user: PlatformUser = Depends(require_training_officer),
    db: Session = Depends(get_db),
):
    course = _get_course_or_404(db, course_id)
    content = await file.read()
    filename = file.filename or "exam.pdf"
    rel_path = f"training_exams/{course_id}/{token_hex(8)}_{filename}"
    ref = store_upload(rel_path, content, content_type=file.content_type or "application/pdf")
    course.exam_file_path = ref
    db.commit()
    db.refresh(course)
    logger.info("[Trainings] Exam file uploaded for course=%s by=%s", course_id, current_user.id)
    return {"exam_file_path": ref}


@router.post("/courses/{course_id}/questions")
def replace_questions(
    course_id: str,
    payload: QuestionsReplaceRequest,
    current_user: PlatformUser = Depends(require_training_officer),
    db: Session = Depends(get_db),
):
    _get_course_or_404(db, course_id)
    # Delete existing questions for this course
    db.query(TrainingExamQuestion).filter(TrainingExamQuestion.course_id == course_id).delete()
    # Insert new questions
    for q in payload.questions:
        question = TrainingExamQuestion(
            course_id=course_id,
            question_number=q.question_number,
            question_text=q.question_text,
            options=json.dumps(q.options),
            correct_option_index=q.correct_option_index,
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
    _get_course_or_404(db, course_id)
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
    # Collect user IDs and look up names from auth DB
    user_ids = list({a.user_id for a in assignments})
    users_map: dict[str, str] = {}
    if user_ids:
        users = auth_db.query(PlatformUser).filter(PlatformUser.id.in_(user_ids)).all()
        users_map = {u.id: u.full_name for u in users}

    result = []
    for a in assignments:
        result.append({
            "id": a.id,
            "course_id": a.course_id,
            "user_id": a.user_id,
            "user_full_name": users_map.get(a.user_id, "Unknown"),
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


# ---------------------------------------------------------------------------
# User / Auditor endpoints (any authenticated user)
# ---------------------------------------------------------------------------

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
    return FileResponse(local_path, filename=f"training_material_{course_id}.pdf", media_type="application/pdf")


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
    return FileResponse(local_path, filename=f"exam_{course_id}.pdf", media_type="application/pdf")


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
