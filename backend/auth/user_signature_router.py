"""
Certiva — User Signature Profile (Prompt 22).

Every user (CB / auditor / client) may save one personal signature image.
The image is a base64 PNG data URL, captured via canvas draw or image upload
with white-background removal.

Routes:
  GET    /me/signature   → current user's signature or null
  POST   /me/signature   → upsert signature
  DELETE /me/signature   → remove signature
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from auth.db_models import UserSignature, get_db, PlatformUser
from auth.dependencies import get_current_user
from audit_set.signature_image import normalize_signature_data_url

router = APIRouter(prefix="/me", tags=["user_signature"])

# Max allowed base64 size ≈ 1.5 MB — handles high-res scanned signatures
_MAX_DATA_LEN = 2_000_000


class SignatureIn(BaseModel):
    image_data: str   # must be "data:image/png;base64,..."
    source: str       # "drawn" | "uploaded"


# ── GET ───────────────────────────────────────────────────────────────────────

@router.get("/signature")
def get_my_signature(
    db:           Session      = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    sig = db.query(UserSignature).filter_by(user_id=current_user.id).first()
    if not sig:
        return None
    return {
        "has_signature": True,
        "image_data":    sig.image_data,
        "source":        sig.source,
        "created_at":    sig.created_at.isoformat(),
        "updated_at":    sig.updated_at.isoformat(),
    }


# ── POST (upsert) ─────────────────────────────────────────────────────────────

@router.post("/signature")
def save_my_signature(
    body:         SignatureIn,
    db:           Session      = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    if not body.image_data.startswith("data:image/png;base64,"):
        raise HTTPException(400, "image_data must be a PNG data URL (data:image/png;base64,...)")
    if len(body.image_data) > _MAX_DATA_LEN:
        raise HTTPException(400, "Signature image is too large. Maximum is ~1.5 MB.")
    if body.source not in ("drawn", "uploaded"):
        raise HTTPException(400, "source must be 'drawn' or 'uploaded'")

    try:
        image_data = normalize_signature_data_url(body.image_data)
    except Exception:
        raise HTTPException(400, "Signature image could not be processed as a PNG.")

    sig = db.query(UserSignature).filter_by(user_id=current_user.id).first()
    if sig:
        sig.image_data = image_data
        sig.source     = body.source
    else:
        sig = UserSignature(
            user_id=current_user.id,
            image_data=image_data,
            source=body.source,
        )
        db.add(sig)

    db.commit()
    db.refresh(sig)
    return {"saved": True, "source": sig.source, "updated_at": sig.updated_at.isoformat()}


# ── DELETE ────────────────────────────────────────────────────────────────────

@router.delete("/signature")
def delete_my_signature(
    db:           Session      = Depends(get_db),
    current_user: PlatformUser = Depends(get_current_user),
):
    deleted = db.query(UserSignature).filter_by(user_id=current_user.id).delete()
    db.commit()
    return {"deleted": bool(deleted)}
