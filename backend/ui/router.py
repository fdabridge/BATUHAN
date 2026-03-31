"""
BATUHAN — Internal UI Router (Phase 7)
Serves the Jinja2-rendered HTML pages for the internal management interface.

Routes:
  GET /ui              → Job submission form  (submit.html)
  GET /ui/status/{id} → Real-time job progress (status.html)
  GET /ui/results/{id}→ Download + correction view (results.html)
"""

from __future__ import annotations
import json
import logging
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from schemas.models import ISOStandard, AuditStage
from storage.file_store import job_exists, read_text_artifact

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ui", tags=["ui"])

TEMPLATES_DIR = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

# Pre-build the lists once at import time (they're static enums)
STANDARDS = [s.value for s in ISOStandard]
STAGES = [st.value for st in AuditStage]


# ---------------------------------------------------------------------------
# Job submission form
# ---------------------------------------------------------------------------

@router.get("/", response_class=HTMLResponse)
def ui_home(request: Request):
    """Render the job submission form."""
    return templates.TemplateResponse(
        "submit.html",
        {
            "request": request,
            "standards": STANDARDS,
            "stages": STAGES,
            "error": None,
        },
    )


# ---------------------------------------------------------------------------
# Job status / progress polling page
# ---------------------------------------------------------------------------

@router.get("/status/{job_id}", response_class=HTMLResponse)
def ui_status(request: Request, job_id: str):
    """Render the live job progress page for a given job_id."""
    if not job_exists(job_id):
        return templates.TemplateResponse(
            "submit.html",
            {
                "request": request,
                "standards": STANDARDS,
                "stages": STAGES,
                "error": f"Job not found: {job_id}",
            },
            status_code=404,
        )
    return templates.TemplateResponse(
        "status.html",
        {"request": request, "job_id": job_id},
    )


# ---------------------------------------------------------------------------
# Results / download page
# ---------------------------------------------------------------------------

@router.get("/calculator", response_class=HTMLResponse)
def ui_calculator(request: Request):
    """Render the Audit Time Calculator page."""
    return templates.TemplateResponse("calculator.html", {"request": request})


@router.get("/guide", response_class=HTMLResponse)
def ui_guide(request: Request):
    """Render the comprehensive user guide page."""
    return templates.TemplateResponse("guide.html", {"request": request})


@router.get("/results/{job_id}", response_class=HTMLResponse)
def ui_results(request: Request, job_id: str):
    """Render the results page once a job is complete."""
    if not job_exists(job_id):
        return templates.TemplateResponse(
            "submit.html",
            {
                "request": request,
                "standards": STANDARDS,
                "stages": STAGES,
                "error": f"Job not found: {job_id}",
            },
            status_code=404,
        )

    # Load summary
    try:
        summary_raw = read_text_artifact(job_id, "job_summary.json")
        summary = json.loads(summary_raw)
    except Exception:
        summary = {
            "standard": "—",
            "stage": "—",
            "correction_count": 0,
            "completed_at": "—",
            "files_used": [],
        }

    # Load correction log (structured JSON)
    corrections: list[dict] = []
    try:
        corr_raw = read_text_artifact(job_id, "step_c_correction_log.json")
        corr_data = json.loads(corr_raw)
        # CorrectionLog schema: {"corrections": [{description, section_title?}]}
        corrections = corr_data.get("corrections", [])
    except Exception:
        pass

    return templates.TemplateResponse(
        "results.html",
        {
            "request": request,
            "job_id": job_id,
            "summary": summary,
            "corrections": corrections,
        },
    )

