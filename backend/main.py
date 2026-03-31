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
from ui import router as ui_router
from calculator.routes import router as calculator_router

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
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# --- Routers ---
app.include_router(jobs.router)
app.include_router(ui_router.router)
app.include_router(calculator_router)


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

