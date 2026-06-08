# Augment Prompt — Deploy Templates to Railway (Fix MISSING_TEMPLATES)

## Problem

The live Railway app returns a `MISSING_TEMPLATES.txt` file instead of a filled audit package ZIP. Root cause: the `uaf_blank_set copy/` template folder lived at the repo root, outside Railway's Docker build context (`"dockerContext": "backend"`), so it was never included in the Docker image.

---

## What Was Already Done (do NOT redo)

1. **All 69 `.docx` templates copied** from `uaf_blank_set copy/` → `backend/uaf_blank_set/` (3.5 MB, three subfolders: `13485/`, `27001/`, `9-14-45-22-5001/`).
2. **`backend/config/settings.py`** — `blank_set_path` default changed from the Mac-local path to `./uaf_blank_set` so it resolves to `/app/uaf_blank_set` inside the container automatically (no extra env var needed on Railway).

---

## Your Task

### Step 1 — Verify the files are there

```bash
find backend/uaf_blank_set -name "*.docx" | wc -l
# Must print 69
ls backend/uaf_blank_set/
# Must show: 13485  27001  9-14-45-22-5001
```

### Step 2 — Make sure backend/.dockerignore does NOT exclude it

Check `backend/.dockerignore` — confirm there is no line that would exclude `uaf_blank_set/` or `*.docx`. The current `.dockerignore` does not exclude these. Do NOT add an exclusion.

### Step 3 — Commit and push

```bash
git add backend/uaf_blank_set/
git add backend/config/settings.py
git commit -m "feat: bundle UAF templates in Docker image — fix MISSING_TEMPLATES on Railway"
git push
```

Railway auto-deploys on push. The new image will include `/app/uaf_blank_set/` with all 69 templates.

### Step 4 — Verify the Railway deploy

Wait for Railway to finish building (watch the deploy logs in the Railway dashboard or via CLI). Once green:

1. Log in at https://compassionate-miracle-production.up.railway.app/login
2. Open an existing audit set (or create a new one)
3. Click **Download Audit Set**
4. The ZIP should now contain `.docx` files — NOT `MISSING_TEMPLATES.txt`

### Step 5 — Smoke test a render

After confirming the ZIP contains actual documents, open one of the rendered `.docx` files and confirm:
- No `{{ ... }}` placeholders left unfilled
- No Jinja2 error messages embedded in the document
- Tables look correct

---

## If You See Errors

### "No such file or directory: /app/uaf_blank_set/..."

`BLANK_SET_PATH` env var is set to a wrong path on Railway. Go to Railway → Service → Variables and **delete** any `BLANK_SET_PATH` variable so the code falls back to the `settings.py` default (`./uaf_blank_set` = `/app/uaf_blank_set`).

### "TemplateNotFound" or "FileNotFoundError" for a specific FR number

Run:
```bash
ls backend/uaf_blank_set/9-14-45-22-5001/"Initial Certification/Stage 1/" | grep FR
ls backend/uaf_blank_set/13485/"Initial Certification/Stage 1/" | grep FR
ls backend/uaf_blank_set/27001/"Initial Certification/Stage 1/" | grep FR
```
Report the missing file name.

### Railway still shows old image

Force a redeploy from the Railway dashboard: **Deployments → Redeploy**.

---

## No Other Changes Required

The Dockerfile already contains `COPY . .` which will include `backend/uaf_blank_set/` in the image now that it's inside the build context. No Dockerfile edits are needed.
