"""
repair_ea_codes.py — One-time migration: convert integer EA codes to strings.

Run on Railway:
    python backend/repair_ea_codes.py

What it fixes:
  1. auditors.auditors.ea_codes          — top-level list, e.g. [12] → ["12"]
  2. auditor_standard_qualifications.ea_codes — per-standard list, same fix
  3. audit_sets.committee_members        — JSON snapshot, ea_codes inside each entry
  4. audit_set_committee_members.ea_codes_at_appointment — appointment snapshot

Idempotent: running it twice is safe (already-string values are left unchanged).
Dry-run mode: pass --dry-run to print what would change without writing.
"""

import sys
import json
import os

DRY_RUN = "--dry-run" in sys.argv

# ── Database connections ──────────────────────────────────────────────────────

# Auditors DB (auditors/auditors, auditor_standard_qualifications)
from auditors.models import engine as auditors_engine, Auditor, AuditorStandardQualification, SessionLocal as AuditorsSession

# Audit-sets DB (audit_sets, audit_set_committee_members)
from audit_set.db_models import engine as sets_engine, AuditSet, AuditSetCommitteeMember, get_db as get_sets_db

from sqlalchemy import text
from sqlalchemy.orm import Session


def _coerce_ea_codes(codes) -> tuple[list, bool]:
    """
    Given a JSON value from an ea_codes column, return (fixed_list, changed).
    Converts any integer items to their string representation.
    Returns (original, False) if nothing needed fixing.
    """
    if not codes:
        return codes, False
    if not isinstance(codes, list):
        return codes, False
    fixed = []
    changed = False
    for c in codes:
        if isinstance(c, int):
            fixed.append(str(c))
            changed = True
        elif isinstance(c, float) and c == int(c):
            fixed.append(str(int(c)))
            changed = True
        else:
            fixed.append(c)
    return fixed, changed


def fix_auditor_ea_codes():
    print("\n── 1. auditors.auditors.ea_codes ────────────────────────────────")
    db: Session = AuditorsSession()
    try:
        auditors = db.query(Auditor).all()
        fixed_count = 0
        for a in auditors:
            new_codes, changed = _coerce_ea_codes(a.ea_codes)
            if changed:
                print(f"  Auditor '{a.name}' ({a.id}): {a.ea_codes!r} → {new_codes!r}")
                fixed_count += 1
                if not DRY_RUN:
                    a.ea_codes = new_codes
        if not DRY_RUN and fixed_count:
            db.commit()
        print(f"  {'[DRY RUN] Would fix' if DRY_RUN else 'Fixed'} {fixed_count} auditor(s).")
    finally:
        db.close()


def fix_qualification_ea_codes():
    print("\n── 2. auditor_standard_qualifications.ea_codes ──────────────────")
    db: Session = AuditorsSession()
    try:
        quals = db.query(AuditorStandardQualification).all()
        fixed_count = 0
        for q in quals:
            new_codes, changed = _coerce_ea_codes(q.ea_codes)
            if changed:
                print(f"  Qual id={q.id} ({q.standard_code}): {q.ea_codes!r} → {new_codes!r}")
                fixed_count += 1
                if not DRY_RUN:
                    q.ea_codes = new_codes
        if not DRY_RUN and fixed_count:
            db.commit()
        print(f"  {'[DRY RUN] Would fix' if DRY_RUN else 'Fixed'} {fixed_count} qualification row(s).")
    finally:
        db.close()


def fix_committee_members_snapshot():
    print("\n── 3. audit_sets.committee_members (JSON snapshot) ──────────────")
    db: Session = next(get_sets_db())
    try:
        from sqlalchemy.orm.attributes import flag_modified
        audit_sets = db.query(AuditSet).filter(AuditSet.committee_members.isnot(None)).all()
        fixed_count = 0
        for aset in audit_sets:
            members = aset.committee_members
            if not isinstance(members, list):
                continue
            changed_any = False
            new_members = []
            for m in members:
                if not isinstance(m, dict):
                    new_members.append(m)
                    continue
                new_codes, changed = _coerce_ea_codes(m.get("ea_codes"))
                if changed:
                    m = {**m, "ea_codes": new_codes}
                    changed_any = True
                new_members.append(m)
            if changed_any:
                print(f"  AuditSet {aset.id} ({aset.company_name}): fixed ea_codes in committee snapshot")
                fixed_count += 1
                if not DRY_RUN:
                    aset.committee_members = new_members
                    flag_modified(aset, "committee_members")
        if not DRY_RUN and fixed_count:
            db.commit()
        print(f"  {'[DRY RUN] Would fix' if DRY_RUN else 'Fixed'} {fixed_count} audit set(s).")
    finally:
        db.close()


def fix_appointment_snapshots():
    print("\n── 4. audit_set_committee_members.ea_codes_at_appointment ───────")
    db: Session = next(get_sets_db())
    try:
        members = db.query(AuditSetCommitteeMember).all()
        fixed_count = 0
        for m in members:
            new_codes, changed = _coerce_ea_codes(m.ea_codes_at_appointment)
            if changed:
                print(f"  CommitteeMember id={m.id} ({m.user_name}): {m.ea_codes_at_appointment!r} → {new_codes!r}")
                fixed_count += 1
                if not DRY_RUN:
                    m.ea_codes_at_appointment = new_codes
        if not DRY_RUN and fixed_count:
            db.commit()
        print(f"  {'[DRY RUN] Would fix' if DRY_RUN else 'Fixed'} {fixed_count} committee appointment(s).")
    finally:
        db.close()


if __name__ == "__main__":
    if DRY_RUN:
        print("DRY RUN — no changes will be written.")
    else:
        print("LIVE RUN — changes will be committed to the database.")

    fix_auditor_ea_codes()
    fix_qualification_ea_codes()
    fix_committee_members_snapshot()
    fix_appointment_snapshots()

    print("\n── Done ─────────────────────────────────────────────────────────")
    if DRY_RUN:
        print("Re-run without --dry-run to apply changes.")
    else:
        print("All integer EA codes converted to strings.")
