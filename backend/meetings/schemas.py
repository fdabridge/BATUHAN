"""
BATUHAN — Meetings Module: Pydantic v2 Schemas
"""

from __future__ import annotations
from typing import Optional
from pydantic import BaseModel, ConfigDict


class ParseRequest(BaseModel):
    """Input for natural-language meeting parsing."""
    text: str


class MeetingCreate(BaseModel):
    """Input schema for creating a meeting."""
    title:            str
    description:      Optional[str] = None
    start_time:       str           # ISO 8601 string in the caller's chosen timezone
    duration_minutes: int = 60
    timezone:         str = "TRT"  # "TRT" (Europe/Istanbul) or "ET" (America/New_York)


class MeetingOut(BaseModel):
    """Output schema — always includes both TRT and ET formatted times."""
    model_config = ConfigDict(from_attributes=True)

    id:               int
    title:            str
    description:      Optional[str]
    start_utc:        str           # ISO string for programmatic use
    start_trt:        str           # e.g. "Mon 13 Jan 2025 14:30 TRT"
    start_et:         str           # e.g. "06:30 ET"
    duration_minutes: int
    notified_30min:   bool
    created_at:       Optional[str]
