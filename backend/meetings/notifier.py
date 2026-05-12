"""
BATUHAN — Meetings Module: CallMeBot WhatsApp Notifier (sync, safe for Celery tasks).

Required env vars:
  CALLMEBOT_PHONE   — your WhatsApp number, e.g. +13054291890
  CALLMEBOT_API_KEY — your CallMeBot API key,  e.g. 8066493
"""

from __future__ import annotations
import logging
import os
import urllib.parse

import httpx

logger = logging.getLogger(__name__)

PHONE   = os.getenv("CALLMEBOT_PHONE", "")
API_KEY = os.getenv("CALLMEBOT_API_KEY", "")

_CALLMEBOT_URL = "https://api.callmebot.com/whatsapp.php"

# Log once at import time so Railway logs confirm the env vars are present
if PHONE and API_KEY:
    logger.info(
        "[Meetings/Notifier] ✅ WhatsApp ready — phone=%s key=***%s",
        PHONE, API_KEY[-3:],
    )
else:
    logger.warning(
        "[Meetings/Notifier] ⚠️  CALLMEBOT_PHONE or CALLMEBOT_API_KEY not set — "
        "WhatsApp notifications are DISABLED. Set both env vars on the worker service."
    )


def send_whatsapp(message: str) -> None:
    """
    Send a WhatsApp message via CallMeBot.
    Synchronous — safe to call from Celery worker processes.
    Silently logs a warning and returns if env vars are missing.
    """
    if not PHONE or not API_KEY:
        logger.warning(
            "[Meetings/Notifier] CALLMEBOT_PHONE or CALLMEBOT_API_KEY not set — skipping."
        )
        return

    encoded = urllib.parse.quote(message)
    url = f"{_CALLMEBOT_URL}?phone={PHONE}&text={encoded}&apikey={API_KEY}"

    try:
        with httpx.Client(timeout=10) as client:
            resp = client.get(url)
            logger.info("[Meetings/Notifier] WhatsApp sent. status=%d", resp.status_code)
    except Exception as exc:
        logger.error("[Meetings/Notifier] Failed to send WhatsApp: %s", exc)
