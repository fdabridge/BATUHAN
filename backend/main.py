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
from audit_set.employee_router import router as employee_router
from health_router import router as health_full_router
try:
    from audit_set.crm_router import router as crm_router
    _crm_router_ok = True
except Exception as _crm_exc:
    import logging as _log
    _log.getLogger("batuhan").error("[Portal 91] crm_router failed to import: %s", _crm_exc)
    _crm_router_ok = False
try:
    from audit_set.crm_router import router as crm_router
    _crm_router_ok = True
except Exception as _crm_exc:
    import logging as _log
    _log.getLogger("batuhan").error("[Portal 91] crm_router failed to import: %s", _crm_exc)
    _crm_router_ok = False

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
app.include_router(employee_router)
# Full system health check — calculator smoke tests + DB connectivity (Prompt 36).
app.include_router(health_full_router)
# CRM portal — finance / operations staff. Read-only. Portal 91.
if _crm_router_ok:
    app.include_router(crm_router)
# CRM portal — finance / operations staff. Read-only. Portal 91.
if _crm_router_ok:
    app.include_router(crm_router)


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

    # Portal 47 — backfill: any audit set still at agreement_signed without
    # FR.218 slots gets seeded and auto-advanced to fr218_in_progress.
    try:
        from audit_set.db_models import (
            AuditSet, AuditDocumentSignature, AuditSetStatusEvent,
            get_db as audit_get_db,
        )
        from audit_set.pipeline_triggers import seed_fr218_slots
        from datetime import datetime as _dt
        adb = next(audit_get_db())
        try:
            stuck = adb.query(AuditSet).filter_by(workflow_status="agreement_signed").all()
            backfilled = 0
            for aset in stuck:
                has_slots = (
                    adb.query(AuditDocumentSignature)
                    .filter_by(audit_set_id=aset.id, document_type="FR218")
                    .first()
                )
                if has_slots:
                    continue
                seed_fr218_slots(aset, triggered_by="system_backfill", db=adb)
                aset.workflow_status = "fr218_in_progress"
                adb.add(AuditSetStatusEvent(
                    audit_set_id=aset.id,
                    from_status="agreement_signed",
                    to_status="fr218_in_progress",
                    triggered_by="system_backfill",
                    triggered_at=_dt.utcnow(),
                    notes="Portal 47 backfill: seeded FR.218 slots + advanced",
                ))
                backfilled += 1
            adb.commit()
            if backfilled:
                logger.info("[BATUHAN] Portal 47 backfill: %d audit set(s) advanced to fr218_in_progress", backfilled)
        finally:
            adb.close()
    except Exception as exc:
        logger.warning("[BATUHAN] Portal 47 backfill skipped: %s", exc)

    # Portal 47e — backfill: any audit set at fr218_in_progress where all required
    # FR.218 slots are already signed should advance to fr218_complete.
    # Handles both paths:
    #   • Old-style (Portal 47 internal-approval rows, document_type="FR218")
    #   • New-style (viewer-signed fr218_review AuditSetSharedDocument rows)
    try:
        from audit_set.db_models import (
            AuditSet, AuditDocumentSignature, AuditSetStatusEvent,
            AuditSetSharedDocument,
            get_db as audit_get_db,
        )
        from datetime import datetime as _dt
        adb2 = next(audit_get_db())
        try:
            stuck218 = adb2.query(AuditSet).filter_by(workflow_status="fr218_in_progress").all()
            completed = 0
            for aset in stuck218:
                # ── Old-style: internal FR218 slots ───────────────────────────
                total = (
                    adb2.query(AuditDocumentSignature)
                    .filter_by(audit_set_id=aset.id, document_type="FR218", required=True)
                    .count()
                )
                if total > 0:
                    unsigned = (
                        adb2.query(AuditDocumentSignature)
                        .filter_by(audit_set_id=aset.id, document_type="FR218", required=True)
                        .filter(AuditDocumentSignature.signed_at.is_(None))
                        .count()
                    )
                    if unsigned == 0:
                        aset.workflow_status = "fr218_complete"
                        adb2.add(AuditSetStatusEvent(
                            audit_set_id=aset.id,
                            from_status="fr218_in_progress",
                            to_status="fr218_complete",
                            triggered_by="system_backfill",
                            triggered_at=_dt.utcnow(),
                            notes="Portal 47e backfill: all FR.218 slots were signed (old-style), advancing to fr218_complete",
                        ))
                        completed += 1
                    continue  # old-style slots present — skip new-style check

                # ── New-style: viewer-signed fr218_review document ─────────────
                fr218_doc = (
                    adb2.query(AuditSetSharedDocument)
                    .filter_by(audit_set_id=aset.id, document_type="fr218_review")
                    .order_by(AuditSetSharedDocument.id.desc())
                    .first()
                )
                if not fr218_doc:
                    continue
                new_total = (
                    adb2.query(AuditDocumentSignature)
                    .filter_by(document_id=fr218_doc.id, required=True)
                    .count()
                )
                new_unsigned = (
                    adb2.query(AuditDocumentSignature)
                    .filter_by(document_id=fr218_doc.id, required=True)
                    .filter(AuditDocumentSignature.signed_at.is_(None))
                    .count()
                )
                if new_total > 0 and new_unsigned == 0:
                    aset.workflow_status = "fr218_complete"
                    adb2.add(AuditSetStatusEvent(
                        audit_set_id=aset.id,
                        from_status="fr218_in_progress",
                        to_status="fr218_complete",
                        triggered_by="system_backfill",
                        triggered_at=_dt.utcnow(),
                        notes="Portal 47e backfill: fr218_review document fully signed (new-style), advancing to fr218_complete",
                    ))
                    completed += 1
            adb2.commit()
            if completed:
                logger.info(
                    "[BATUHAN] Portal 47e backfill: %d audit set(s) advanced to fr218_complete",
                    completed,
                )
        finally:
            adb2.close()
    except Exception as exc:
        logger.warning("[BATUHAN] Portal 47e backfill skipped: %s", exc)

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

