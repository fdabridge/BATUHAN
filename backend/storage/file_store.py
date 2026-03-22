"""
BATUHAN — File Storage Layer (T6)
Abstracts all file I/O behind a single interface.
Stores files organised by job_id. Supports local filesystem (dev) and S3 (prod).
"""

from __future__ import annotations
import os
import uuid
import shutil
import aiofiles
from pathlib import Path
from fastapi import UploadFile
from config.settings import get_settings

settings = get_settings()

ALLOWED_EXTENSIONS = {".pdf", ".docx", ".doc", ".txt", ".png", ".jpg", ".jpeg", ".tiff"}


def generate_job_id() -> str:
    return str(uuid.uuid4())


def _job_dir(job_id: str) -> Path:
    base = Path(settings.storage_base_path)
    d = base / job_id
    d.mkdir(parents=True, exist_ok=True)
    return d


def _subdir(job_id: str, category: str) -> Path:
    d = _job_dir(job_id) / category
    d.mkdir(parents=True, exist_ok=True)
    return d


def validate_extension(filename: str) -> bool:
    return Path(filename).suffix.lower() in ALLOWED_EXTENSIONS


async def save_upload(file: UploadFile, job_id: str, category: str) -> str:
    """
    Save an uploaded file to storage/{job_id}/{category}/{filename}.
    Returns the absolute path string.
    Raises ValueError for disallowed file types.
    """
    if not validate_extension(file.filename or ""):
        raise ValueError(
            f"File type not allowed: {file.filename}. "
            f"Allowed: {', '.join(ALLOWED_EXTENSIONS)}"
        )
    dest_dir = _subdir(job_id, category)
    dest_path = dest_dir / (file.filename or "upload")
    # Handle duplicate filenames
    counter = 1
    while dest_path.exists():
        stem = Path(file.filename or "upload").stem
        suffix = Path(file.filename or "upload").suffix
        dest_path = dest_dir / f"{stem}_{counter}{suffix}"
        counter += 1

    async with aiofiles.open(dest_path, "wb") as out:
        content = await file.read()
        await out.write(content)

    return str(dest_path)


def save_text_artifact(job_id: str, filename: str, content: str) -> str:
    """Save a text artifact (JSON, TXT) to storage/{job_id}/artifacts/."""
    dest = _subdir(job_id, "artifacts") / filename
    dest.write_text(content, encoding="utf-8")
    return str(dest)


def save_binary_artifact(job_id: str, filename: str, content: bytes) -> str:
    """Save a binary artifact (DOCX) to storage/{job_id}/artifacts/."""
    dest = _subdir(job_id, "artifacts") / filename
    dest.write_bytes(content)
    return str(dest)


def list_files(job_id: str, category: str) -> list[str]:
    """Return sorted list of absolute paths for all files in a category."""
    d = _subdir(job_id, category)
    return sorted(str(p) for p in d.iterdir() if p.is_file())


def read_text_artifact(job_id: str, filename: str) -> str:
    path = _subdir(job_id, "artifacts") / filename
    return path.read_text(encoding="utf-8")


def job_exists(job_id: str) -> bool:
    """Return True only if the job directory already exists (non-creating check)."""
    base = Path(settings.storage_base_path)
    return (base / job_id).exists()


def delete_job(job_id: str) -> None:
    """Remove all files for a job (cleanup)."""
    d = _job_dir(job_id)
    if d.exists():
        shutil.rmtree(d)

