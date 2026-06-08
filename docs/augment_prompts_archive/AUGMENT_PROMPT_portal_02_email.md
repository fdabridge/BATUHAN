# Portal Build — Prompt 2 of 8: Email Service (Resend)

## ⚠️ CRITICAL: DO NOT BREAK THE EXISTING PORTAL
Purely additive. Only add new files and new settings keys. Do not modify any existing route,
endpoint, or frontend page.

---

## Context

We use Resend (https://resend.com) for transactional email. The RESEND_API_KEY environment
variable will be set in Railway. For local dev without the key, email sending should fail
silently (log the error, don't crash).

---

## Task

### 1. Add Resend settings to `backend/config/settings.py`

Add these fields to the `Settings` class:
```python
# ── Email (Resend) ─────────────────────────────────────────────────────────
resend_api_key: str = ""          # Set in Railway env. Empty = email disabled (dev mode).
email_from: str = "IFC Global <no-reply@ifcglobal.us>"
email_base_url: str = "https://compassionate-miracle-production.up.railway.app"
# email_base_url is used to build links inside emails (e.g. login link).
# Override with the actual production URL once custom domain is set.
```

### 2. Create `backend/email_service.py`

New file at `backend/email_service.py`:

```python
"""
BATUHAN — Email Service (Resend)
Thin wrapper around the Resend HTTP API.
All functions log and silently return False on failure so the app never crashes
when email is unavailable (e.g. local dev without RESEND_API_KEY).
"""
from __future__ import annotations
import logging
import httpx
from config.settings import get_settings

logger = logging.getLogger(__name__)
RESEND_SEND_URL = "https://api.resend.com/emails"


def _send(to: str, subject: str, html: str) -> bool:
    """Send one email via Resend. Returns True on success, False on failure."""
    settings = get_settings()
    if not settings.resend_api_key:
        logger.info(f"[EMAIL DISABLED] Would send to {to}: {subject}")
        return False
    try:
        resp = httpx.post(
            RESEND_SEND_URL,
            headers={"Authorization": f"Bearer {settings.resend_api_key}",
                     "Content-Type": "application/json"},
            json={"from": settings.email_from, "to": [to],
                  "subject": subject, "html": html},
            timeout=10,
        )
        if resp.status_code not in (200, 201):
            logger.error(f"Resend error {resp.status_code}: {resp.text}")
            return False
        return True
    except Exception as exc:
        logger.error(f"Email send failed: {exc}")
        return False


# ── Template functions ──────────────────────────────────────────────────────

def send_client_welcome(to: str, full_name: str, temp_password: str, audit_set_id: str) -> bool:
    """Sent when a client submits an application. Gives them login credentials."""
    settings = get_settings()
    login_url = f"{settings.email_base_url}/login"
    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto">
      <h2 style="color:#1A4731">IFC Global LLC — Application Received</h2>
      <p>Dear {full_name},</p>
      <p>Thank you for submitting your certification application.
         Your application is currently under review and you will be notified when it progresses.</p>
      <p>You can track the status of your application using the following credentials:</p>
      <div style="background:#f5f5f5;padding:16px;border-radius:6px;margin:16px 0">
        <p style="margin:4px 0"><strong>Portal:</strong> <a href="{login_url}">{login_url}</a></p>
        <p style="margin:4px 0"><strong>Email:</strong> {to}</p>
        <p style="margin:4px 0"><strong>Temporary Password:</strong> {temp_password}</p>
      </div>
      <p>Please change your password after your first login.</p>
      <p style="color:#666;font-size:12px">IFC Global LLC · application@ifcglobal.us</p>
    </div>
    """
    return _send(to, "IFC Global — Your Application Has Been Received", html)


def send_client_status_update(to: str, full_name: str, new_status: str, notes: str = "") -> bool:
    """Sent whenever workflow_status changes on a client's audit set."""
    STATUS_LABELS = {
        "in_planning": "Under Review — We are processing your application",
        "quotation_sent": "Quotation Ready — Please review and sign your quotation",
        "agreement_signed": "Agreement Confirmed",
        "audit_scheduled": "Audit Dates Confirmed",
        "audit_in_progress": "Audit In Progress",
        "under_review": "Certification Under Review",
        "certified": "🎉 Certification Issued",
    }
    settings = get_settings()
    label = STATUS_LABELS.get(new_status, new_status.replace("_", " ").title())
    portal_url = f"{settings.email_base_url}/client/overview"
    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto">
      <h2 style="color:#1A4731">IFC Global — Status Update</h2>
      <p>Dear {full_name},</p>
      <p>Your certification application status has been updated:</p>
      <div style="background:#E8F5E9;padding:16px;border-radius:6px;margin:16px 0;border-left:4px solid #1A4731">
        <strong>{label}</strong>
        {f'<p style="margin-top:8px">{notes}</p>' if notes else ''}
      </div>
      <p><a href="{portal_url}" style="background:#1A4731;color:white;padding:10px 20px;border-radius:4px;text-decoration:none">View in Portal</a></p>
      <p style="color:#666;font-size:12px">IFC Global LLC · application@ifcglobal.us</p>
    </div>
    """
    return _send(to, f"IFC Global — {label}", html)


def send_document_released(to: str, full_name: str, document_label: str) -> bool:
    """Sent when CB releases a document (e.g. quotation) to the client for signing."""
    settings = get_settings()
    portal_url = f"{settings.email_base_url}/client/documents"
    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto">
      <h2 style="color:#1A4731">IFC Global — Document Ready for Signature</h2>
      <p>Dear {full_name},</p>
      <p>A document is ready for your review and signature in the portal:</p>
      <div style="background:#f5f5f5;padding:16px;border-radius:6px;margin:16px 0">
        <strong>{document_label}</strong>
      </div>
      <p><a href="{portal_url}" style="background:#1A4731;color:white;padding:10px 20px;border-radius:4px;text-decoration:none">Review &amp; Sign</a></p>
      <p style="color:#666;font-size:12px">IFC Global LLC · application@ifcglobal.us</p>
    </div>
    """
    return _send(to, f"IFC Global — {document_label} Ready for Signature", html)


def send_otp_code(to: str, full_name: str, otp: str, document_label: str) -> bool:
    """Sent when client requests OTP to sign a document."""
    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto">
      <h2 style="color:#1A4731">IFC Global — Signature Code</h2>
      <p>Dear {full_name},</p>
      <p>Use the following code to sign <strong>{document_label}</strong>:</p>
      <div style="background:#1A4731;color:white;padding:24px;border-radius:6px;margin:16px 0;text-align:center">
        <span style="font-size:36px;letter-spacing:8px;font-weight:bold">{otp}</span>
      </div>
      <p style="color:#666">This code expires in 10 minutes. Do not share it with anyone.</p>
      <p style="color:#666;font-size:12px">IFC Global LLC · application@ifcglobal.us</p>
    </div>
    """
    return _send(to, "IFC Global — Your Signature Code", html)


def send_new_message_notification(to: str, full_name: str, sender_name: str) -> bool:
    """Sent when a new portal message is received (max once per hour to avoid spam)."""
    settings = get_settings()
    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto">
      <h2 style="color:#1A4731">IFC Global — New Message</h2>
      <p>Dear {full_name},</p>
      <p>You have a new message from <strong>{sender_name}</strong> in your certification portal.</p>
      <p><a href="{settings.email_base_url}/client/messages" style="background:#1A4731;color:white;padding:10px 20px;border-radius:4px;text-decoration:none">Read Message</a></p>
      <p style="color:#666;font-size:12px">IFC Global LLC · application@ifcglobal.us</p>
    </div>
    """
    return _send(to, f"IFC Global — New message from {sender_name}", html)
```

### 3. Verify import works

```bash
cd backend
python -c "from email_service import send_client_welcome; print('email_service OK')"
```

Should print `email_service OK` (no crash even without RESEND_API_KEY).

### Commit and push

Commit: `feat(portal): add Resend email service with all notification templates`
Push to main.

## Files to create/edit
- `backend/config/settings.py` — add `resend_api_key`, `email_from`, `email_base_url`
- `backend/email_service.py` — new file (all email templates)
