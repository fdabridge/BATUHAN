# Portal 85 — Persistent file storage: fix document loss on Railway redeploy

## Root cause

Every time a new Docker image is deployed on Railway, the container is replaced
with a fresh one built from the image. The Dockerfile creates `/app/storage` at
**image build time** (`mkdir -p /app/storage`) — this directory lives in the
container layer and is wiped on every deploy.

`settings.py` defaults to `storage_base_path = "./storage"` which resolves to
`/app/storage` inside the container. Every upload, generated PDF, and shared
document is written there. After a redeploy, the Postgres DB still holds absolute
paths like `/app/storage/shared_docs/{id}/file.docx` — but those files are gone.
Every `os.path.exists(path)` check in `viewer_router`, `documents_router`,
`report_router`, etc. returns `False` → "Document file not found on server."

**The already-lost files cannot be recovered** — Railway does not preserve the old
container filesystem. The fix ensures this never happens again: mount a Railway
Volume at `/data` and redirect all writes there.

---

## Part A — Railway dashboard (do this first, before deploying the code change)

1. Open the Certiva backend service in Railway.
2. Go to **Settings → Storage → Add Volume**.
3. Mount path: `/data`
4. Size: start with 5 GB (can be expanded later without data loss).
5. Once the volume appears as attached, go to **Variables** and add:

```
STORAGE_BASE_PATH=/data/storage
```

Railway will pass this to the container at runtime. The existing `settings.py`
field `storage_base_path` reads from `STORAGE_BASE_PATH` automatically because
Pydantic BaseSettings maps env-var names to field names case-insensitively.

**Do not deploy the code change until the volume is attached and the env var is
set.** If you deploy first, the app will write to the default `./storage` path
inside the container (still ephemeral). Attach the volume first, then push.

---

## Part B — Code changes

### Change 1 — `backend/Dockerfile`

Two sub-changes:

#### 1a. Remove the unprivileged-user setup

The current lines:
```dockerfile
RUN useradd --no-create-home --shell /bin/false batuhan \
    && mkdir -p /app/storage /app/prompts \
    && chown -R batuhan:batuhan /app
USER batuhan
```

Replace with:
```dockerfile
RUN mkdir -p /app/prompts
```

**Why remove `USER batuhan`:** Railway Volumes are mounted at container start as
`root:root`. The non-root `batuhan` user cannot write to a root-owned volume
directory. Railway already runs each service in an isolated container — running as
root inside that container does not create a real security risk, and is the
standard approach on Railway. The `useradd` + `USER batuhan` pattern is correct
for bare-metal deployments but actively breaks Railway Volumes.

The `mkdir -p /app/storage` line is also dropped — storage will live on the volume
at `/data/storage`, not inside the container image. The `mkdir -p /app/prompts`
line is kept because prompts are baked into the image at build time and are
read-only at runtime.

#### 1b. Update CMD to pre-create the storage directory

Replace the existing CMD:
```dockerfile
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
```

With:
```dockerfile
CMD ["sh", "-c", "mkdir -p ${STORAGE_BASE_PATH:-/app/storage} && uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
```

This ensures the directory exists under the mounted volume path before uvicorn
starts. `os.makedirs(upload_dir, exist_ok=True)` in the application code already
creates sub-directories on each upload, but this startup `mkdir -p` ensures the
root storage dir exists immediately (needed by `health_checker.py` which probes it
on `/health`).

The full Dockerfile `RUN useradd...` + `USER batuhan` block and the final CMD
block should look like this after the change:

```dockerfile
# -----------------------------------------------------------------------
# Runtime configuration
# -----------------------------------------------------------------------
RUN mkdir -p /app/prompts

# API port
EXPOSE 8000

# Default command: start the FastAPI API server.
# Override in docker-compose for the Celery worker.
CMD ["sh", "-c", "mkdir -p ${STORAGE_BASE_PATH:-/app/storage} && uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]
```

---

## What does NOT change

- `config/settings.py` — no change; `storage_base_path` is already driven by the
  `STORAGE_BASE_PATH` env var through Pydantic BaseSettings. The default
  `"./storage"` is the correct local-dev fallback.
- All upload/save code — no change; `os.makedirs(upload_dir, exist_ok=True)` already
  creates sub-directories as needed.
- `viewer_router.py`, `documents_router.py`, `report_router.py`, etc. — no change;
  their `os.path.exists()` guards are correct.
- The Postgres database — no change; new uploads will be written to
  `/data/storage/...` and those paths will be stored in `file_path` columns going
  forward.

---

## About already-lost documents

Documents uploaded before this fix are gone — Railway did not persist the old
container's `/app/storage`. Their `file_path` values in Postgres still point to
`/app/storage/...` which no longer exists. They will continue to show "Document
file not found on server" until those documents are re-uploaded.

No DB migration is needed: the paths in old broken rows are irrelevant since the
files don't exist. New uploads will go to `/data/storage/...` and work correctly.
If you want to clean up the orphaned records from the DB to remove the confusing
broken entries, that can be done separately as a one-time SQL operation — it's not
required for the fix.

---

## Verification checklist (post-deploy)

1. Confirm Railway shows the Volume as "Attached" and `STORAGE_BASE_PATH=/data/storage`
   is in the Variables tab before deploying.
2. Deploy (push the Dockerfile change).
3. Upload any shared document via the planner UI.
4. Confirm the document is visible and openable in the viewer.
5. Push a dummy commit to trigger a second deploy (no code change needed — just a
   comment edit).
6. After the second deploy, re-open the same document.
7. Confirm it still loads — this is the actual test that proves persistence.

---

## Commit message suggestion

```
Portal 85: mount Railway Volume for persistent document storage

- Dockerfile: remove non-root user setup (batuhan user) — root is required
  for Railway Volume write access; Railway containers are already isolated
- Dockerfile: drop mkdir /app/storage from image build; add mkdir to CMD
  startup so storage dir is created under STORAGE_BASE_PATH at runtime
- Railway (dashboard): attach 5GB Volume at /data; set STORAGE_BASE_PATH=/data/storage

Files no longer lost on redeploy.
```
