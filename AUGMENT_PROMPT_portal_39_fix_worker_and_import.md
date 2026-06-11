# AUGMENT PROMPT — Portal 39: Fix Celery Worker Crash + Confirm Import

## Problems

### Problem 1 — Celery Worker Crash-Looping (BLOCKING)

The Railway worker service is crash-looping with:
```
File "/app/jobs/state.py", line 15, in <module>
    from storage.file_store import save_text_artifact, read_text_artifact
ModuleNotFoundError: No module named 'storage.file_store'
```

`jobs/state.py` imports from `storage.file_store` but that module does not exist in the codebase.

**Fix options (pick the correct one based on the actual code):**

**Option A** — If `storage/file_store.py` was partially written but never committed, create it now with stub implementations:
```python
# backend/storage/file_store.py

def save_text_artifact(job_id: str, filename: str, content: str) -> str:
    """Save a text artifact for a job. Returns the file path."""
    import os
    base = os.environ.get("ARTIFACT_DIR", "/tmp/artifacts")
    os.makedirs(f"{base}/{job_id}", exist_ok=True)
    path = f"{base}/{job_id}/{filename}"
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    return path


def read_text_artifact(job_id: str, filename: str) -> str:
    """Read a text artifact for a job. Returns file content."""
    import os
    base = os.environ.get("ARTIFACT_DIR", "/tmp/artifacts")
    path = f"{base}/{job_id}/{filename}"
    with open(path, "r", encoding="utf-8") as f:
        return f.read()
```

**Option B** — If `jobs/state.py` is referencing the wrong module path (e.g., the file was moved or renamed), fix the import to point to the correct location.

**Option C** — If `save_text_artifact` and `read_text_artifact` are not yet needed (e.g., the code that calls them isn't wired up yet), comment out or guard those imports in `jobs/state.py`:
```python
# Temporarily disabled until storage module is implemented
# from storage.file_store import save_text_artifact, read_text_artifact
```

Look at `jobs/state.py` and `jobs/tasks.py` to understand which option is correct. If the functions are actively used in those files, do Option A. If they're just imported but not called yet, do Option C.

---

### Problem 2 — Confirm `POST /auditors/bulk-import-json` works

After fixing the worker crash and deploying:

1. Test the import endpoint with `auditors_import.json` (available at project root) via Admin → Auditors → Import JSON with `replace_all: true`
2. If it returns 500, paste the **web service** logs from Railway (not the worker service logs) so we can see the FastAPI traceback

---

## What NOT to change

- Do not modify `auditors.py` routes — the cascade delete fix from fc89124 is already correct
- Do not modify any auditor models or schemas
- Do not touch the frontend

---

## After deploying

Confirm in Railway that:
1. The worker service starts without the `ModuleNotFoundError`
2. The web service returns 200 on `POST /auditors/bulk-import-json`
