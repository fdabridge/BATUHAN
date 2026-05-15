"""
BATUHAN — Public Configuration Routes
No auth required — called by the frontend on load to read CB branding.

GET /config/branding  → BrandingResponse
"""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from config.settings import get_settings

router = APIRouter()


class BrandingResponse(BaseModel):
    cb_name: str
    cb_short_name: str
    cb_logo_url: str
    cb_primary_color: str
    cb_website: str
    cb_email: str
    cb_phone: str
    cb_address: str
    accreditation_bodies: list[str]
    supported_standards: list[str]


@router.get("/branding", response_model=BrandingResponse)
def get_branding():
    """Return CB identity and branding configuration.
    No authentication required — safe to call before login."""
    s = get_settings()
    return BrandingResponse(
        cb_name=s.cb_name,
        cb_short_name=s.cb_short_name,
        cb_logo_url=s.cb_logo_url,
        cb_primary_color=s.cb_primary_color,
        cb_website=s.cb_website,
        cb_email=s.cb_email,
        cb_phone=s.cb_phone,
        cb_address=s.cb_address,
        accreditation_bodies=s.accreditation_bodies_list,
        supported_standards=s.supported_standards_list,
    )
