"""
BATUHAN — File Storage Layer (T6)
Redis-backed shared artifact storage.

Both the API container and the Celery Worker container share all job state
through the same Redis instance. The local filesystem is NOT used for job
artifacts — it is NOT shared across Railway services.

Temporary files written by the worker during processing live in /tmp/{job_id}/
and are never read by the API.
"""

from __future__ import annotations
import uuid
from pathlib import Path

import redis as redis_lib

from config.settings import get_settings

settings = get_settings()

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".doc", ".txt", ".png", ".jpg", ".jpeg", ".tiff"}

# Redis keys expire after 7 days — plenty of time for any realistic job
_JOB_TTL = 7 * 24 * 60 * 60


# ---------------------------------------------------------------------------
# Simple helpers
# ---------------------------------------------------------------------------

def generate_job_id() -> str:
    return str(uuid.uuid4())


def validate_extension(filename: str) -> bool:
    return Path(filename).suffix.lower() in ALLOWED_EXTENSIONS


# ---------------------------------------------------------------------------
# Redis connection
# ---------------------------------------------------------------------------

def _redis() -> redis_lib.Redis:
    """Return a Redis client. A fresh connection is made per call so this is
    safe to call from both async API handlers and forked Celery workers."""
    return redis_lib.from_url(settings.redis_url, decode_responses=False)


# ---------------------------------------------------------------------------
# Internal key helpers
# ---------------------------------------------------------------------------

def _text_key(job_id: str, filename: str) -> str:
    return f"batuhan:job:{job_id}:text:{filename}"


def _binary_key(job_id: str, filename: str) -> str:
    return f"batuhan:job:{job_id}:binary:{filename}"


def _exists_key(job_id: str) -> str:
    return f"batuhan:job:{job_id}:exists"


def _binaries_set_key(job_id: str) -> str:
    return f"batuhan:job:{job_id}:binaries"


def _touch_exists(r: redis_lib.Redis, job_id: str) -> None:
    r.set(_exists_key(job_id), "1")
    r.expire(_exists_key(job_id), _JOB_TTL)


# ---------------------------------------------------------------------------
# Public artifact API
# ---------------------------------------------------------------------------

def save_text_artifact(job_id: str, filename: str, content: str) -> str:
    """Store a UTF-8 text artifact in Redis. Returns a pseudo-path string."""
    r = _redis()
    key = _text_key(job_id, filename)
    r.set(key, content.encode("utf-8"))
    r.expire(key, _JOB_TTL)
    _touch_exists(r, job_id)
    return f"redis:{job_id}/{filename}"


def save_binary_artifact(job_id: str, filename: str, content: bytes) -> str:
    """Store a binary artifact (e.g. DOCX bytes) in Redis. Returns a pseudo-path."""
    r = _redis()
    key = _binary_key(job_id, filename)
    r.set(key, content)
    r.expire(key, _JOB_TTL)
    r.sadd(_binaries_set_key(job_id), filename)
    r.expire(_binaries_set_key(job_id), _JOB_TTL)
    _touch_exists(r, job_id)
    return f"redis:{job_id}/{filename}"


def read_text_artifact(job_id: str, filename: str) -> str:
    """Read a text artifact from Redis. Raises FileNotFoundError if absent."""
    r = _redis()
    val = r.get(_text_key(job_id, filename))
    if val is None:
        raise FileNotFoundError(f"Artifact not found: {job_id}/{filename}")
    return val.decode("utf-8")


def read_binary_artifact(job_id: str, filename: str) -> bytes:
    """Read a binary artifact from Redis. Raises FileNotFoundError if absent."""
    r = _redis()
    val = r.get(_binary_key(job_id, filename))
    if val is None:
        raise FileNotFoundError(f"Binary artifact not found: {job_id}/{filename}")
    return val


def list_files(job_id: str, category: str) -> list[str]:
    """Return the list of stored binary artifact filenames for the job.
    The `category` parameter is kept for API compatibility but is not used."""
    r = _redis()
    members = r.smembers(_binaries_set_key(job_id))
    return sorted(
        m.decode("utf-8") if isinstance(m, bytes) else m for m in members
    )


def job_exists(job_id: str) -> bool:
    """Return True if any artifact has been stored for this job."""
    return _redis().exists(_exists_key(job_id)) > 0


def delete_job(job_id: str) -> None:
    """Remove all Redis keys for a job."""
    r = _redis()
    keys = r.keys(f"batuhan:job:{job_id}:*")
    if keys:
        r.delete(*keys)

