# BATUHAN — New CB Deployment Checklist (Railway)

Follow these steps in order to spin up a fresh BATUHAN instance for a new Certification Body.

---

## 1. Prerequisites

Before you start, make sure you have:

- [ ] Railway CLI installed (`npm i -g @railway/cli`) and logged in (`railway login`)
- [ ] Access to the CB's `uaf_blank_set/` folder (the blank document template set)
- [ ] The following CB branding details confirmed and ready:
  - Full legal name (e.g. "Acme Certification LLC")
  - Short name / acronym (e.g. "ACL")
  - Logo URL (publicly accessible image link, or leave blank)
  - Primary brand color (hex, e.g. `#1A4731`)
  - Website URL
  - Contact email address
  - Phone number
  - Mailing address
  - Accreditation bodies (comma-separated, e.g. `UAF,TURKAK`)
  - Supported standards (comma-separated, e.g. `QMS,EMS,OHSMS`)

---

## 2. Create the Railway Project

1. Go to [railway.app](https://railway.app) → **New Project** → **Deploy from GitHub repo**
2. Select the BATUHAN repository and the branch you want to deploy
3. Railway will detect the `Dockerfile` or `nixpacks` config and begin the initial build — let it fail for now (env vars not set yet)
4. In the same project, click **+ New** → **Database** → **Add Redis**
   - Railway will provision Redis and auto-inject `REDIS_URL` into the project environment
5. Note the Railway-generated domain shown under **Settings → Domains** (e.g. `batuhan-production.up.railway.app`) — you will need it for DNS and handoff

---

## 3. Set Environment Variables

In Railway: **Project → Service → Variables**. Add every variable below.

### Core
| Variable | Value |
|---|---|
| `SECRET_KEY` | A long random string — generate with `openssl rand -hex 32` |
| `REDIS_URL` | Auto-injected by Railway Redis service — verify it exists |
| `ALLOWED_ORIGINS` | The Railway domain (and custom domain if set), comma-separated |

### Anthropic / Claude
| Variable | Value |
|---|---|
| `ANTHROPIC_API_KEY` | CB's or shared Anthropic API key |

### Branding
| Variable | Example value |
|---|---|
| `CB_NAME` | `Acme Certification LLC` |
| `CB_SHORT_NAME` | `ACL` |
| `CB_LOGO_URL` | `https://cdn.example.com/logo.png` (or leave blank) |
| `CB_PRIMARY_COLOR` | `#1A4731` |
| `CB_WEBSITE` | `https://www.example.com` |
| `CB_EMAIL` | `info@example.com` |
| `CB_PHONE` | `+1 212 555 0100` |
| `CB_ADDRESS` | `123 Main St, New York, NY 10001` |
| `CB_ACCREDITATION_BODIES` | `UAF,TURKAK` |
| `CB_SUPPORTED_STANDARDS` | `QMS,EMS,OHSMS,FSMS,ISMS,MDQMS,ABMS,ENMS` |

### Paths
| Variable | Value |
|---|---|
| `BLANK_SET_PATH` | `/data/blank_set` (set after volume is mounted in step 4) |

### Auth
| Variable | Value |
|---|---|
| `ADMIN_EMAIL` | Initial admin email address |
| `ADMIN_PASSWORD` | Strong initial password (the admin must change this on first login) |
| `JWT_ALGORITHM` | `HS256` (default — only change if you know why) |
| `JWT_EXPIRY_HOURS` | `8` (default) |

---

## 4. Upload the Blank Document Set

The app requires the CB's `uaf_blank_set/` template folder at a fixed path on disk.

1. In Railway: **Project → Service → Volumes** → **Add Volume**
   - Mount path: `/data/blank_set`
2. Set `BLANK_SET_PATH=/data/blank_set` in the service variables (step 3)
3. Upload the `uaf_blank_set/` folder contents into the volume:
   ```bash
   # From your local machine, with Railway CLI:
   railway run --service <service-name> bash
   # Then inside the shell, use railway volume cp or scp to transfer files.
   # Alternatively, include the blank set in the Docker image at build time
   # and set BLANK_SET_PATH to the image-internal path instead.
   ```
   > **Tip:** For simpler deployments, copy the `uaf_blank_set/` folder into the repo and set `BLANK_SET_PATH` to its path relative to the working directory (e.g. `./uaf_blank_set`). The volume approach is preferred for production so the templates can be updated without a redeploy.

---

## 5. Deploy and Bootstrap

1. In Railway: **Service → Deploy** (or push a commit to trigger auto-deploy)
2. Watch the build and startup logs — you should see:
   ```
   [BATUHAN] First admin created: <ADMIN_EMAIL>
   All DB tables initialised.
   ```
   This happens automatically on first startup via the `on_startup` hook in `main.py`. It only runs when both `ADMIN_EMAIL` and `ADMIN_PASSWORD` are set **and** no admin exists yet.
3. Verify branding is correct — no auth required:
   ```bash
   curl https://<railway-domain>/config/branding
   ```
   Response should show the CB's `cb_name`, `cb_email`, etc.
4. Verify login works:
   ```bash
   curl -X POST https://<railway-domain>/auth/login \
     -H "Content-Type: application/json" \
     -d '{"email": "<ADMIN_EMAIL>", "password": "<ADMIN_PASSWORD>"}'
   ```
   A `200 OK` with an `access_token` confirms auth is working.

---

## 6. Custom Domain (Optional)

1. Railway: **Service → Settings → Domains → Add Custom Domain**
2. Enter the CB's desired domain (e.g. `app.example.com`)
3. Railway will display a CNAME target (e.g. `xyz.up.railway.app`)
4. At the CB's DNS registrar, add a CNAME record:
   - **Name:** `app` (or `@` for root)
   - **Value:** the Railway CNAME target
5. HTTPS is provisioned automatically by Railway — no certificate management needed
6. Update `ALLOWED_ORIGINS` to include the custom domain

---

## 7. Handoff Checklist

Before signing off with the CB:

- [ ] Share the deployment URL (Railway domain or custom domain)
- [ ] Share the initial admin credentials and **instruct the admin to change the password immediately** via:
  ```
  POST /auth/change-password
  Body: { "current_password": "...", "new_password": "..." }
  ```
- [ ] Confirm `GET /config/branding` returns the correct CB name, email, colors, and supported standards
- [ ] Create any additional user accounts the CB needs (`POST /admin/users/`) with appropriate roles (`planner`, `auditor`, `officer`, `executive`)
- [ ] Run one full test job end-to-end (upload documents → generate report → download) before signing off
- [ ] Hand over the Railway project access or transfer project ownership to the CB's Railway account
