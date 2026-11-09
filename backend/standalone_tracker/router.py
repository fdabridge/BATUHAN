"""Authenticated, independent register; imports never touch operational tables."""
import json
import math
import os
from urllib.parse import urlparse
from datetime import date, datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from auth.db_models import get_db
from auth.dependencies import require_admin, get_current_user
from .models import TrackerRecord, TrackerHistory, TrackerMetadata

router = APIRouter(prefix="/standalone-tracker", tags=["standalone-tracker"])
def staff(user=Depends(get_current_user)):
    editors = {email.strip().casefold() for email in os.getenv("IFC_TRACKER_EDITOR_EMAILS", "").split(",") if email.strip()}
    if user.role != "admin" and user.email.casefold() not in editors:
        raise HTTPException(403, "Tracker access is limited to administrators and designated editors")
    return user
STAGES = {"Application Received", "Audit Planning", "Decision", "Certificate"}


def now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def encode(value):
    return json.dumps(value, ensure_ascii=False, allow_nan=False)


def validate_record(value: Any, kind=None):
    if not isinstance(value, dict):
        raise HTTPException(422, "A record must be an object")
    r = dict(value)
    if kind and r.get("kind", kind) != kind:
        raise HTTPException(422, "Record kind does not match its collection")
    r["kind"] = kind or r.get("kind")
    if r["kind"] not in {"certificate", "invoice", "other"}:
        raise HTTPException(422, "Invalid record kind")
    for field in ("id", "company"):
        if not isinstance(r.get(field), str) or not r[field].strip():
            raise HTTPException(422, f"{field} is required")
    try:
        encoded = encode(r)
    except (ValueError, TypeError):
        raise HTTPException(422, "Record contains invalid values")
    if "archived" in r and not isinstance(r["archived"], bool):
        raise HTTPException(422, "Archived must be true or false")
    if len(r["id"]) > 100 or len(encoded) > 200000:
        raise HTTPException(422, "Record is too large")
    if r["kind"] == "certificate" and r.get("stage") not in STAGES:
        raise HTTPException(422, "Invalid certificate stage")
    for key in ("issue", "annual", "expiry", "date", "reminderDate"):
        if r.get(key):
            try:
                date.fromisoformat(r[key])
            except (ValueError, TypeError):
                raise HTTPException(422, f"Invalid {key} date")
    for key, allowed in (("invoiced", {"", "Yes", "No"}), ("payment", {"", "Paid", "Unpaid", "Part-paid"}), ("currency", {"", "TRY", "USD", "EUR"})):
        if key in r and r[key] not in allowed:
            raise HTTPException(422, f"Invalid {key}")
    for key in ("fee", "paid", "balance", "total"):
        v = r.get(key)
        if v is not None and (isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) or v < 0):
            raise HTTPException(422, f"Invalid {key} amount")
    if r["kind"] == "invoice":
        if r.get("total") is None or not str(r.get("ref", "")).strip():
            raise HTTPException(422, "Invoice total and reference are required")
        if r.get("paid") is not None:
            if r["paid"] > r["total"]:
                raise HTTPException(422, "Paid amount exceeds invoice total")
            r["balance"] = round(r["total"] - r["paid"], 2)
        else:
            r["balance"] = None
    elif r.get("payment") == "Paid":
        r["balance"] = 0
    for name in ("iaf", "uaf"):
        registry = r.get(name)
        if registry and (not isinstance(registry, dict) or not str(registry.get("url", "")).startswith("https://")):
            raise HTTPException(422, "Registry links must use HTTPS")
    return r


async def limited_json(request: Request, maximum: int):
    body = bytearray()
    async for chunk in request.stream():
        body.extend(chunk)
        if len(body) > maximum:
            raise HTTPException(413, "Import exceeds the size limit")
    try:
        return json.loads(body)
    except (ValueError, UnicodeDecodeError):
        raise HTTPException(422, "Invalid JSON")


@router.get("")
def read_records(history: bool = False, user=Depends(staff), db: Session = Depends(get_db)):
    if history:
        rows = db.query(TrackerHistory).order_by(TrackerHistory.saved_at.desc()).limit(1000).all()
        return {"history": [{k: getattr(r, k) for k in ("id", "actor", "saved_at", "action", "before_payload", "after_payload")} for r in rows]}
    result = {"records": [], "invoices": [], "other": []}
    for row in db.query(TrackerRecord).all():
        record = json.loads(row.payload)
        record["revision"] = row.revision
        result[{"certificate": "records", "invoice": "invoices", "other": "other"}[row.kind]].append(record)
    metadata = db.get(TrackerMetadata, "snapshot")
    result.update(json.loads(metadata.value) if metadata else {})
    result.update(user=user.email, syncedAt=now(), canImport=user.role == "admin" and not bool(result["records"] or result["invoices"] or result["other"]))
    return result


@router.post("")
async def save_record(request: Request, user=Depends(staff), db: Session = Depends(get_db)):
    r = validate_record(await limited_json(request, 250000))
    expected = r.get("revision", 0)
    if isinstance(expected, bool) or not isinstance(expected, int) or expected < 0:
        raise HTTPException(422, "Invalid revision")
    existing = db.get(TrackerRecord, r["id"])
    if existing and (existing.revision != expected or existing.kind != r["kind"]):
        raise HTTPException(409, "This record changed. Close and refresh before editing again.")
    if not existing and expected:
        raise HTTPException(409, "This record no longer exists. Refresh the tracker.")
    before = existing.payload if existing else "{}"
    old = json.loads(before)
    # A local edit cannot silently replace registry evidence for another certificate.
    if any(old.get(k) != r.get(k) for k in ("company", "certificate", "standard", "country")):
        r.pop("iaf", None)
        r.pop("uaf", None)
        r.pop("iafCheck", None)
        r.pop("uafCheck", None)
    r.update(revision=expected + 1, updatedAt=now(), updatedBy=user.email)
    r["archived"] = bool(r.get("archived", False))
    try:
        if existing:
            changed = db.execute(update(TrackerRecord).where(TrackerRecord.id == r["id"], TrackerRecord.revision == expected).values(payload=encode(r), revision=expected + 1)).rowcount
            if changed != 1:
                db.rollback()
                raise HTTPException(409, "This record changed. Refresh before saving.")
        else:
            db.add(TrackerRecord(id=r["id"], kind=r["kind"], revision=1, payload=encode(r)))
        db.add(TrackerHistory(record_id=r["id"], actor=user.email, saved_at=r["updatedAt"], action="Archived" if r["archived"] else "Updated", before_payload=before, after_payload=encode(r)))
        if r["kind"] == "invoice":
            # Propagate collections only within this independent register.
            for cert in db.query(TrackerRecord).filter_by(kind="certificate").all():
                c = json.loads(cert.payload)
                if c.get("invoiceRef") != r.get("ref") or c.get("paymentConfirmedByOwner"):
                    continue
                if r.get("balance") is None:
                    continue
                previous = cert.payload
                c.update(invoiced="Yes", payment="Paid" if r["balance"] == 0 else "Unpaid" if r["paid"] == 0 else "Part-paid", updatedAt=now(), updatedBy=user.email, revision=cert.revision + 1)
                c["paid"] = c.get("fee") if r["balance"] == 0 else 0 if r["paid"] == 0 else None
                c["balance"] = 0 if r["balance"] == 0 else c.get("fee") if r["paid"] == 0 else None
                changed = db.execute(update(TrackerRecord).where(TrackerRecord.id == cert.id, TrackerRecord.revision == cert.revision).values(payload=encode(c), revision=cert.revision + 1)).rowcount
                if changed != 1:
                    db.rollback()
                    raise HTTPException(409, "A linked certificate changed. Refresh and retry.")
                db.add(TrackerHistory(record_id=cert.id, actor=user.email, saved_at=c["updatedAt"], action="Invoice payment updated", before_payload=previous, after_payload=encode(c)))
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "Record already exists. Refresh the tracker.")
    return {"record": r}


@router.post("/import")
async def import_snapshot(request: Request, user=Depends(require_admin), db: Session = Depends(get_db)):
    data = await limited_json(request, 20_000_000)
    if not isinstance(data, dict) or any(not isinstance(data.get(k), list) for k in ("records", "invoices", "other")):
        raise HTTPException(422, "Choose an IFC tracker sweep export")
    if db.query(TrackerRecord).first() or db.get(TrackerMetadata, "snapshot"):
        raise HTTPException(409, "Import is only available for an empty tracker; existing records were not changed")
    validated = [validate_record(r, kind) for key, kind in (("records", "certificate"), ("invoices", "invoice"), ("other", "other")) for r in data[key]]
    if not validated or len(validated) > 20000 or len({r["id"] for r in validated}) != len(validated):
        raise HTTPException(422, "Import must contain 1–20,000 records with unique IDs")
    timestamp = now()
    metadata = {k: data[k] for k in ("asOf", "iafSnapshot", "uafSnapshot") if k in data}
    metadata.update(importedAt=timestamp, importedBy=user.email)
    try:
        db.add(TrackerMetadata(key="snapshot", value=encode(metadata)))
        db.flush()  # Unique key makes concurrent imports mutually exclusive.
        for r in validated:
            r.update(revision=1, updatedAt=timestamp, updatedBy=user.email)
            db.add(TrackerRecord(id=r["id"], kind=r["kind"], revision=1, payload=encode(r)))
        db.add(TrackerHistory(record_id="import", actor=user.email, saved_at=timestamp, action="Imported", before_payload="{}", after_payload=encode({"company": "IFC tracker snapshot", "records": len(validated)})))
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409, "An import or edit completed concurrently; refresh the tracker")
    return {"imported": len(validated)}


@router.post("/registry-checks")
async def save_registry_checks(request: Request, user=Depends(require_admin), db: Session = Depends(get_db)):
    """Apply reviewed registry evidence without importing or replacing business records."""
    data = await limited_json(request, 5_000_000)
    if not isinstance(data, dict) or set(data) != {"checks"} or not isinstance(data["checks"], list):
        raise HTTPException(422, "Choose a registry checks file")
    checks = data["checks"]
    if not 1 <= len(checks) <= 20000:
        raise HTTPException(422, "Registry checks must contain 1–20,000 records")
    seen, prepared = set(), []
    for check in checks:
        if not isinstance(check, dict) or set(check) - {"id", "revision", "iaf", "uaf"} or not ({"iaf", "uaf"} & set(check)):
            raise HTTPException(422, "Only IAF and UAF evidence can be updated here")
        rid, revision = check.get("id"), check.get("revision")
        if not isinstance(rid, str) or rid in seen or type(revision) is not int:
            raise HTTPException(422, "Each check needs a unique record and revision")
        seen.add(rid)
        row = db.get(TrackerRecord, rid)
        if not row or row.kind != "certificate" or row.revision != revision:
            raise HTTPException(409, "A certificate changed. Export a fresh sweep before applying these checks.")
        record = json.loads(row.payload)
        for key in ("iaf", "uaf"):
            if key not in check:
                continue
            evidence = check[key]
            if not isinstance(evidence, dict):
                raise HTTPException(422, "Registry evidence must include its check date and source")
            host = urlparse(str(evidence.get("url", "")))
            allowed = {"member.iafcertsearch.org", "www.iafcertsearch.org"} if key == "iaf" else {"dashboard.uafaccreditation.org"}
            if host.scheme != "https" or host.hostname not in allowed or evidence.get("status") not in {"Active", "Expired", "Withdrawn", "Suspended", "Not found"}:
                raise HTTPException(422, "Invalid registry source or status")
            for field in ("checkedAt", "issued", "expiry"):
                value = evidence.get(field)
                if field == "checkedAt" or value:
                    try:
                        date.fromisoformat(value)
                    except (ValueError, TypeError):
                        raise HTTPException(422, "Invalid registry evidence date")
            # Store negative searches separately; they must not produce a registration tag.
            if evidence["status"] == "Not found":
                record[key] = None
                record[key + "Check"] = evidence
            else:
                record[key] = evidence
                record.pop(key + "Check", None)
        record.update(revision=revision + 1, updatedAt=now(), updatedBy=user.email)
        prepared.append((row.id, revision, row.payload, record))
    try:
        for rid, revision, before, record in prepared:
            changed = db.execute(update(TrackerRecord).where(TrackerRecord.id == rid, TrackerRecord.revision == revision).values(payload=encode(record), revision=revision + 1)).rowcount
            if changed != 1:
                raise HTTPException(409, "A certificate changed. Refresh before applying registry checks.")
            db.add(TrackerHistory(record_id=rid, actor=user.email, saved_at=record["updatedAt"], action="Registry checked", before_payload=before, after_payload=encode(record)))
        db.commit()
    except Exception:
        db.rollback()
        raise
    return {"updated": len(prepared)}
