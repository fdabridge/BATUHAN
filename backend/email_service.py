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
    """Stubbed — email sending is disabled."""
    return False


# ── Template functions (all stubbed — no emails are sent) ───────────────────

def send_client_welcome(to: str, full_name: str, temp_password: str, audit_set_id: str) -> bool:
    return False


def send_client_status_update(to: str, full_name: str, new_status: str, notes: str = "") -> bool:
    return False


def send_document_released(to: str, full_name: str, document_label: str) -> bool:
    return False


def send_otp_code(to: str, full_name: str, otp: str, document_label: str) -> bool:
    return False


def send_meeting_signing_link(
    to: str,
    full_name: str,
    company_name: str,
    stage_label: str,
    sign_url: str,
) -> bool:
    return False


def send_meeting_otp(
    to: str,
    full_name: str,
    event_type: str,
    company_name: str,
    otp: str,
) -> bool:
    return False


def send_new_message_notification(to: str, full_name: str, sender_name: str) -> bool:
    return False


def send_nc_form_la_request(
    to: str,
    full_name: str,
    company_name: str,
    stage_label: str,
    nc_label: str,
) -> bool:
    return False


def send_nc_form_client_ready(
    to: str,
    full_name: str,
    company_name: str,
    nc_label: str,
) -> bool:
    return False


def send_impartiality_declaration_request(
    to: str,
    full_name: str,
    company_name: str,
    stage_label: str,
    role: str,
) -> bool:
    return False


def send_audit_report_review_request(
    to: str,
    full_name: str,
    company_name: str,
    stage_label: str,
    report_form: str,
    label: str,
) -> bool:
    return False
