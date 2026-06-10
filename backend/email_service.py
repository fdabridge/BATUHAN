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


def send_meeting_signing_link(
    to: str,
    full_name: str,
    company_name: str,
    stage_label: str,
    sign_url: str,
) -> bool:
    """Sent to an external meeting attendee with their personal signing link."""
    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto">
      <h2 style="color:#1A4731">IFC Global LLC — Audit Meeting Attendance</h2>
      <p>Dear {full_name},</p>
      <p>You are registered as a meeting attendee for the IFC Global audit of
         <strong>{company_name}</strong> ({stage_label}).</p>
      <p>Please use your personal signing link to record your attendance at the
         opening and closing meetings. Each signature requires a one-time code
         sent to this email.</p>
      <p style="margin:24px 0">
        <a href="{sign_url}" style="background:#1A4731;color:white;padding:12px 24px;
           border-radius:4px;text-decoration:none;font-weight:bold">Sign Meetings</a>
      </p>
      <p style="color:#888;font-size:12px">
        This link is personal and expires in 72 hours. Do not share it.<br>
        If you believe this was sent in error, please ignore this email.<br>
        IFC Global LLC · application@ifcglobal.us
      </p>
    </div>
    """
    return _send(to, f"IFC Global — Audit Meeting Sign-in: {company_name}", html)


def send_meeting_otp(
    to: str,
    full_name: str,
    event_type: str,
    company_name: str,
    otp: str,
) -> bool:
    """OTP code for signing an opening or closing meeting."""
    label = "Opening Meeting" if event_type == "opening" else "Closing Meeting"
    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto">
      <h2 style="color:#1A4731">IFC Global — Meeting Signature Code</h2>
      <p>Dear {full_name},</p>
      <p>Use the following code to sign the <strong>{label}</strong>
         attendance record for <strong>{company_name}</strong>:</p>
      <div style="background:#1A4731;color:white;padding:24px;border-radius:6px;
                  margin:16px 0;text-align:center">
        <span style="font-size:36px;letter-spacing:8px;font-weight:bold">{otp}</span>
      </div>
      <p style="color:#666">This code expires in 10 minutes. Do not share it.</p>
      <p style="color:#666;font-size:12px">IFC Global LLC · application@ifcglobal.us</p>
    </div>
    """
    return _send(to, f"IFC Global — {label} Signature Code", html)



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


def send_nc_form_la_request(
    to: str,
    full_name: str,
    company_name: str,
    stage_label: str,
    nc_label: str,
) -> bool:
    """Sent to Lead Auditor when CB uploads an NC form requiring their signature."""
    settings = get_settings()
    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto">
      <h2 style="color:#1A4731">IFC Global LLC — NC Form Signature Required</h2>
      <p>Dear {full_name},</p>
      <p>An NC Form has been uploaded for your signature for the audit of
         <strong>{company_name}</strong> ({stage_label}):</p>
      <div style="background:#f5f5f5;padding:16px;border-radius:6px;margin:16px 0">
        <strong>{nc_label}</strong>
      </div>
      <p>Please log in to the portal and navigate to the NC Forms tab in your audit
         assignment to review and sign.</p>
      <p><a href="{settings.email_base_url}/auditor/dashboard"
            style="background:#1A4731;color:white;padding:10px 20px;border-radius:4px;
                   text-decoration:none">Go to Portal</a></p>
      <p style="color:#666;font-size:12px">IFC Global LLC · application@ifcglobal.us</p>
    </div>
    """
    return _send(to, f"IFC Global — NC Form Signature Required: {company_name}", html)


def send_nc_form_client_ready(
    to: str,
    full_name: str,
    company_name: str,
    nc_label: str,
) -> bool:
    """Sent to client after Lead Auditor signs — NC form ready for counter-signature."""
    settings = get_settings()
    portal_url = f"{settings.email_base_url}/client/documents"
    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto">
      <h2 style="color:#1A4731">IFC Global LLC — NC Form Ready for Your Signature</h2>
      <p>Dear {full_name},</p>
      <p>An NC Form related to your certification audit has been signed by the Lead Auditor
         and is now ready for your counter-signature:</p>
      <div style="background:#FFF3E0;padding:16px;border-radius:6px;margin:16px 0;
                  border-left:4px solid #E65100">
        <strong>{nc_label}</strong>
      </div>
      <p>Please log in to review the form and provide your signature.</p>
      <p><a href="{portal_url}"
            style="background:#1A4731;color:white;padding:10px 20px;border-radius:4px;
                   text-decoration:none">Review &amp; Sign</a></p>
      <p style="color:#666;font-size:12px">IFC Global LLC · application@ifcglobal.us</p>
    </div>
    """
    return _send(to, f"IFC Global — NC Form Ready for Counter-Signature", html)


def send_impartiality_declaration_request(
    to: str,
    full_name: str,
    company_name: str,
    stage_label: str,
    role: str,
) -> bool:
    """Sent to each audit team member when CB creates declaration records for a stage."""
    settings = get_settings()
    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto">
      <h2 style="color:#1A4731">IFC Global LLC — Impartiality Declaration Required</h2>
      <p>Dear {full_name},</p>
      <p>You are assigned as <strong>{role}</strong> for the audit of
         <strong>{company_name}</strong> ({stage_label}).</p>
      <p>As required by ISO 17021-1, you must sign an impartiality declaration
         before the audit commences. Please log in to the portal, navigate to
         the relevant audit assignment, and complete the declaration under the
         <strong>Declarations</strong> tab.</p>
      <p><a href="{settings.email_base_url}/auditor/dashboard"
            style="background:#1A4731;color:white;padding:10px 20px;border-radius:4px;
                   text-decoration:none">Go to Portal</a></p>
      <p style="color:#666;font-size:12px">IFC Global LLC · application@ifcglobal.us</p>
    </div>
    """
    return _send(to, f"IFC Global — Impartiality Declaration Required: {company_name}", html)
