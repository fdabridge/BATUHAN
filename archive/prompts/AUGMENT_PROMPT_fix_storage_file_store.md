# AUGMENT PROMPT — Fix: Missing `storage.file_store` Module

## Problem

Railway deployment logs show the Celery worker crashing at startup with:

```
ModuleNotFoundError: No module named 'storage.file_store'
```

Traceback:
```
File "/app/jobs/tasks.py", line 24, in <module>
    from jobs.state import update_job_state
  File "/app/jobs/state.py", line 15, in <module>
    from storage.file_store import save_text_artifact, read_text_artifact
ModuleNotFoundError: No module named 'storage.file_store'
```

## What to do

### Step 1 — Check what exists

Look for:
- `backend/storage/` directory
- `backend/storage/file_store.py`
- Any file in the project that defines `save_text_artifact` or `read_text_artifact`

### Step 2a — If `storage/` exists but `file_store.py` is missing

Create `backend/storage/file_store.py` with stub implementations that are safe to call:

```python
"""
File store utilities for persisting job artifacts.
"""
import os
import json
from pathlib import Path

ARTIFACT_DIR = os.environ.get("ARTIFACT_DIR", "/tmp/artifacts")


def save_text_artifact(job_id: str, filename: str, content: str) -> str:
    """Save a text artifact for a job. Returns the file path."""
    path = Path(ARTIFACT_DIR) / str(job_id)
    path.mkdir(parents=True, exist_ok=True)
    file_path = path / filename
    file_path.write_text(content, encoding="utf-8")
    return str(file_path)


def read_text_artifact(job_id: str, filename: str) -> str | None:
    """Read a text artifact for a job. Returns content or None if not found."""
    file_path = Path(ARTIFACT_DIR) / str(job_id) / filename
    if file_path.exists():
        return file_path.read_text(encoding="utf-8")
    return None
```

Also make sure `backend/storage/__init__.py` exists (can be empty).

### Step 2b — If `storage/` directory doesn't exist at all

Create both files:
- `backend/storage/__init__.py` (empty)
- `backend/storage/file_store.py` with the content above

### Step 2c — If the functions exist under a different name/path

Update the import in `backend/jobs/state.py` line 15 to point to wherever `save_text_artifact` and `read_text_artifact` actually live.

---

## Also check

Does `jobs/tasks.py` or `jobs/state.py` get imported anywhere in the FastAPI app startup (e.g., in `main.py` or any router)? If yes, this error is also killing the web API — confirm the web service is healthy after this fix by checking that `/health` or the login page responds.

## What NOT to change

- Do not touch `auditors.py`, the bulk import endpoint, or anything from Portal 38.
- Do not remove or change any existing Celery task logic — just make the import work.

## Commit message

`fix: create missing storage.file_store module to unblock Celery worker startup`
