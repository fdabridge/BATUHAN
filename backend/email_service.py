"""
BATUHAN — Email Service (Resend)
Thin wrapper around the Resend HTTP API.

Existing notification templates remain disabled. Verification-code delivery is
enabled because account and employee-signature policy gates must fail closed
when a code cannot be delivered.
"""
from __future__ import annotations

from html import escape
import logging

import httpx

from config.settings import get_settings

logger = logging.getLogger(__name__)
RESEND_SEND_URL = "https://api.resend.com/emails"


def _send(to: str, subject: str, html: str) -> bool:
    settings = get_settings()
    if not settings.resend_api_key:
        logger.warning("Email unavailable: RESEND_API_KEY is not configured")
        return False
    try:
        response = httpx.post(
            RESEND_SEND_URL,
            headers={
                "Authorization": f"Bearer {settings.resend_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "from": settings.email_from,
                "to": [to],
                "subject": subject,
                "html": html,
            },
            timeout=15.0,
        )
        response.raise_for_status()
        return True
    except Exception as exc:
        logger.warning("Resend delivery failed for %s: %s", to, exc)
        return False


def send_client_welcome(to: str, full_name: str, temp_password: str, audit_set_id: str) -> bool:
    return False


def send_client_status_update(to: str, full_name: str, new_status: str, notes: str = "") -> bool:
    return False


def send_document_released(to: str, full_name: str, document_label: str) -> bool:
    return False


def send_otp_code(to: str, full_name: str, otp: str, document_label: str) -> bool:
    return _send(
        to,
        f"Verification code for {document_label}",
        (
            '<div style="font-family:Arial,sans-serif;max-width:620px;margin:auto;'
            'color:#24332b;line-height:1.55">'
            f"<h2>Hello, {escape(full_name)}</h2>"
            f"<p>Your verification code for {escape(document_label)} is:</p>"
            f'<p style="font-size:28px;font-weight:700;letter-spacing:5px">{escape(otp)}</p>'
            "<p>This code expires in 10 minutes. If you did not request it, ignore this email.</p>"
            "</div>"
        ),
    )


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
