#!/usr/bin/env python3
"""
Portal 50a — One-time repair: restore lead_auditor_id on AuditSetStage rows
where it is blank but lead_auditor_name is present.

Root cause: Bug in frontend clients/[id]/page.tsx buildStageEdit() was
hardcoding lead_auditor_id = '' on every save, overwriting the correct value.

This script restores the ID by matching the name to the Auditor table.

Run from the project root (backend container or locally with DB access):
    python backend/scripts/repair_lead_auditor_ids.py
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from audit_set.db_models import AuditSetStage, get_db

# Import the Auditor model
try:
    from auditors.db_models import Auditor
except ImportError:
    # Fallback if co-located
    try:
        from audit_set.db_models import Auditor
    except ImportError:
        print("ERROR: Cannot import Auditor model. Check your module structure.")
        sys.exit(1)


def repair():
    db = next(get_db())
    stages = db.query(AuditSetStage).all()

    fixed = 0
    skipped = 0
    warnings = 0

    for stage in stages:
        # Only repair stages where lead_auditor_id is missing/blank but name is present
        if stage.lead_auditor_id or not stage.lead_auditor_name:
            skipped += 1
            continue

        auditor = (
            db.query(Auditor)
            .filter(Auditor.name == stage.lead_auditor_name)
            .first()
        )
        if auditor:
            stage.lead_auditor_id = auditor.id
            fixed += 1
            print(f"  ✓ FIXED stage {stage.id[:8]}… "
                  f"({stage.stage_type}): '{stage.lead_auditor_name}' → {auditor.id[:8]}…")
        else:
            warnings += 1
            print(f"  ⚠ WARN  stage {stage.id[:8]}… "
                  f"({stage.stage_type}): no auditor record found for "
                  f"'{stage.lead_auditor_name}'")

    db.commit()
    print(f"\nDone.")
    print(f"  Fixed:   {fixed}")
    print(f"  Skipped: {skipped} (already OK or no name)")
    print(f"  Warnings: {warnings} (name present but no matching auditor record)")

if __name__ == "__main__":
    repair()
