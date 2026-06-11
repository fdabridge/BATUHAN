"""
BATUHAN — FastAPI Application Entry Point
Run with: uvicorn backend.main:app --reload
"""

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import logging

from config.settings import get_settings
from api.routes import jobs
from api.routes import review
from ui import router as ui_router
from calculator.routes import router as calculator_router
from audit_plan.routes import router as audit_plan_router
from meetings.router import router as meetings_router
from api.routes.auditors import router as auditors_router
from api.routes.audit_sets import router as audit_sets_router
from api.routes.auth import router as auth_router
from api.routes.admin_users import router as admin_users_router
from api.routes.dashboard import router as dashboard_router
from api.routes.config import router as config_router
from audit_set.apply_router import router as apply_router
from audit_set.workflow_router import router as workflow_router
from audit_set.client_router import router as client_router
from audit_set.messages_router import router as messages_router
from audit_set.documents_router import router as documents_router
from audit_set.signatures_router import router as signatures_router
from audit_set.committee_router import router as committee_router
from audit_set.meeting_router import protected_router as meeting_protected_router
from audit_set.meeting_router import public_router as meeting_public_router
from audit_set.assessment_router import router as assessment_router
from audit_set.nc_router import router as nc_router
from audit_set.declaration_router import router as declaration_router
from audit_set.report_router import router as report_router
from audit_set.viewer_router import router as viewer_router
from audit_set.auditor_router import router as auditor_router
from auth.user_signature_router import router as user_signature_router
from health_router import router as health_full_router

settings = get_settings()

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("batuhan")

app = FastAPI(
    title="BATUHAN — Reporting for Duty",
    description=(
        "Internal AI-powered ISO audit report automation system. "
        "Accepts company documents, sample reports, and a blank template. "
        "Returns a completed, validated audit report."
    ),
    version=settings.app_version,
    docs_url="/docs",
    redoc_url="/redoc",
)

# CORS — restrict to configured origins (set ALLOWED_ORIGINS in production)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Routers ---
app.include_router(jobs.router)
app.include_router(review.router)
app.include_router(ui_router.router)
app.include_router(calculator_router)
app.include_router(audit_plan_router)
app.include_router(meetings_router, prefix="/meetings", tags=["meetings"])
app.include_router(auditors_router, prefix="/auditors", tags=["auditors"])
# Workflow + messages routers MUST be registered before audit_sets_router so
# that literal paths like /audit-sets/pending-applications and the explicit
# /audit-sets/{id}/messages handlers are matched before the generic
# /audit-sets/{audit_set_id} handler.
app.include_router(workflow_router)
app.include_router(messages_router)
app.include_router(signatures_router)
app.include_router(committee_router)
app.include_router(meeting_protected_router)
app.include_router(meeting_public_router)
app.include_router(assessment_router)
app.include_router(nc_router)
app.include_router(declaration_router)
app.include_router(report_router)
app.include_router(viewer_router)
app.include_router(documents_router)
app.include_router(audit_sets_router, prefix="/audit-sets", tags=["audit-sets"])
app.include_router(auth_router, prefix="/auth", tags=["auth"])
app.include_router(admin_users_router, prefix="/admin", tags=["admin"])
app.include_router(dashboard_router, prefix="/dashboard", tags=["dashboard"])
app.include_router(config_router, prefix="/config", tags=["config"])
# Public client application form — no auth required on POST /apply.
app.include_router(apply_router)
# Client portal — auth enforced per-endpoint via get_current_user.
app.include_router(client_router)
# Auditor portal — auth + assignment check enforced per-endpoint.
app.include_router(auditor_router)
# User signature profile — all portal users (CB / auditor / client).
app.include_router(user_signature_router)
# Full system health check — calculator smoke tests + DB connectivity (Prompt 36).
app.include_router(health_full_router)


# --- Startup: create DB tables + first-admin bootstrap ---
@app.on_event("startup")
def on_startup():
    from meetings.models import create_tables
    create_tables()
    from auditors.models import create_tables as auditors_create_tables
    auditors_create_tables()
    from audit_set.db_models import create_tables as audit_set_create_tables
    audit_set_create_tables()
    from auth.db_models import create_tables as auth_create_tables, get_db as auth_get_db
    auth_create_tables()

    # First-admin bootstrap — only runs if both env vars are set
    startup_settings = get_settings()
    if startup_settings.admin_email and startup_settings.admin_password:
        from auth.service import create_user, get_user_by_email
        db = next(auth_get_db())
        try:
            if not get_user_by_email(db, startup_settings.admin_email):
                create_user(
                    db,
                    startup_settings.admin_email,
                    startup_settings.admin_password,
                    "Administrator",
                    "admin",
                )
                logger.info("[BATUHAN] First admin created: %s", startup_settings.admin_email)
        finally:
            db.close()

    logger.info("All DB tables initialised.")


# --- Global error handler ---
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "An internal error occurred. Please check server logs."},
    )


@app.get("/", tags=["health"])
def root():
    return {
        "system": "BATUHAN",
        "tagline": "Reporting for Duty",
        "version": settings.app_version,
        "status": "operational",
    }


@app.get("/health", tags=["health"])
def health():
    return {"status": "ok", "version": settings.app_version}


@app.get("/health/detailed", tags=["health"])
def health_detailed():
    """
    Deep health check: verifies Redis connectivity, disk space, and detects
    stuck jobs. Returns 200 if healthy, 503 if any critical check fails.
    """
    from fastapi.responses import JSONResponse
    from monitoring.health_checker import run_health_checks
    report = run_health_checks()
    status_code = 200 if report["healthy"] else 503
    return JSONResponse(content=report, status_code=status_code)

