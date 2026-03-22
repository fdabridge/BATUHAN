"""
BATUHAN — Health Checker (T38)
Provides deep health checks for the /health/detailed endpoint.

Checks:
  - Redis connectivity (required for Celery job queue)
  - Disk space on the storage path (warn if <500 MB free)
  - Stuck jobs: any job in STEP_A / STEP_B / STEP_C for >10 minutes
  - Claude API key presence (does NOT make a live API call to save cost)

Returns a dict suitable for direct JSON serialisation.
"""

from __future__ import annotations
import logging
import json
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path

from backend.config.settings import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# Jobs stuck longer than this are flagged as warnings
STUCK_JOB_THRESHOLD = timedelta(minutes=10)

# States that indicate a job is actively running (should not be stuck)
ACTIVE_STATES = {"PREPROCESSING", "STEP_A", "STEP_B", "STEP_C", "ASSEMBLING"}


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

def _check_redis() -> dict:
    """Try to ping Redis. Returns {ok, detail}."""
    try:
        import redis as redis_lib
        client = redis_lib.from_url(settings.redis_url, socket_connect_timeout=2)
        client.ping()
        return {"ok": True, "detail": "Redis reachable"}
    except Exception as exc:
        return {"ok": False, "detail": f"Redis unreachable: {exc}"}


def _check_disk() -> dict:
    """Check free disk space on the storage path. Warn below 500 MB."""
    try:
        storage_path = Path(settings.storage_base_path)
        storage_path.mkdir(parents=True, exist_ok=True)
        stat = os.statvfs(str(storage_path))
        free_mb = (stat.f_bavail * stat.f_frsize) / (1024 * 1024)
        ok = free_mb >= 500
        return {
            "ok": ok,
            "detail": f"{free_mb:.0f} MB free on storage volume",
        }
    except Exception as exc:
        return {"ok": False, "detail": f"Disk check failed: {exc}"}


def _check_api_key() -> dict:
    """Verify the Anthropic API key is configured (non-empty, non-placeholder)."""
    key = settings.anthropic_api_key or ""
    ok = bool(key) and key != "your-anthropic-api-key-here"
    return {
        "ok": ok,
        "detail": "API key configured" if ok else "ANTHROPIC_API_KEY is missing or placeholder",
    }


def _check_stuck_jobs() -> dict:
    """
    Scan job directories for status.json files where state is ACTIVE
    and last_updated is older than STUCK_JOB_THRESHOLD.
    Returns list of stuck job IDs as a warning (does not fail the overall check).
    """
    stuck: list[str] = []
    try:
        base = Path(settings.storage_base_path)
        if not base.exists():
            return {"ok": True, "detail": "No jobs found", "stuck_jobs": []}

        now = datetime.now(timezone.utc)
        for job_dir in base.iterdir():
            if not job_dir.is_dir():
                continue
            status_file = job_dir / "artifacts" / "status.json"
            if not status_file.exists():
                continue
            try:
                data = json.loads(status_file.read_text(encoding="utf-8"))
                state = data.get("state", "")
                if state not in ACTIVE_STATES:
                    continue
                updated_str = data.get("updated_at") or data.get("last_updated")
                if not updated_str:
                    continue
                updated = datetime.fromisoformat(updated_str.replace("Z", "+00:00"))
                if updated.tzinfo is None:
                    updated = updated.replace(tzinfo=timezone.utc)
                if now - updated > STUCK_JOB_THRESHOLD:
                    stuck.append(job_dir.name)
            except Exception:
                continue  # corrupt status.json — skip

        ok = len(stuck) == 0
        detail = f"{len(stuck)} job(s) stuck >10min" if stuck else "No stuck jobs"
        return {"ok": ok, "detail": detail, "stuck_jobs": stuck}
    except Exception as exc:
        return {"ok": True, "detail": f"Stuck-job scan skipped: {exc}", "stuck_jobs": []}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def run_health_checks() -> dict:
    """
    Run all health checks and return a combined report.
    The top-level 'healthy' flag is True only if all critical checks pass.
    Disk space and stuck jobs are warnings — they degrade 'healthy' too.
    """
    redis_result = _check_redis()
    disk_result = _check_disk()
    api_key_result = _check_api_key()
    stuck_result = _check_stuck_jobs()

    all_ok = all([
        redis_result["ok"],
        disk_result["ok"],
        api_key_result["ok"],
        stuck_result["ok"],
    ])

    return {
        "healthy": all_ok,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "version": settings.app_version,
        "checks": {
            "redis": redis_result,
            "disk": disk_result,
            "api_key": api_key_result,
            "stuck_jobs": stuck_result,
        },
    }

