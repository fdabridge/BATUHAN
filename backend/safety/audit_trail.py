"""
BATUHAN — Internal Audit Trail (T30)
Builds and persists audit_trail.json for every completed job.

Records:
  - All uploaded files (names + sizes in bytes)
  - Prompt version and Claude model used
  - ISO standard and audit stage
  - Step A evidence summary (section count, weak items)
  - Step B report summary (section count)
  - Step C correction summary (count, validated_at)
  - Full pipeline step timestamps
  - List of all persisted artifacts
"""

from __future__ import annotations
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from config.settings import get_settings
from storage.file_store import (
    save_text_artifact, read_text_artifact, list_files,
)

logger = logging.getLogger(__name__)
settings = get_settings()


def _file_meta(path: str) -> dict:
    """Return name and size_bytes for a stored file path."""
    p = Path(path)
    return {
        "name": p.name,
        "size_bytes": p.stat().st_size if p.exists() else 0,
    }


def build_audit_trail(job_id: str) -> dict:
    """
    Assemble the full audit trail dict by reading all stored artifacts.
    Safe to call even when some artifacts are absent (missing ones are noted).
    """
    trail: dict = {
        "job_id": job_id,
        "system": "BATUHAN",
        "prompt_version": settings.prompt_version,
        "claude_model": settings.claude_model,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    # --- Bundle: uploaded files + metadata ---
    try:
        bundle = json.loads(read_text_artifact(job_id, "bundle.json"))
        trail["standard"] = bundle.get("standard")
        trail["stage"] = bundle.get("stage")
        trail["company_documents"] = [
            _file_meta(p) for p in bundle.get("company_document_paths", [])
        ]
        trail["sample_reports"] = [
            _file_meta(p) for p in bundle.get("sample_report_paths", [])
        ]
        trail["template"] = _file_meta(bundle.get("template_path", ""))
    except Exception as e:
        logger.warning(f"[AuditTrail] Could not read bundle for {job_id}: {e}")
        trail["bundle_error"] = str(e)

    # --- Status: step timestamps and final state ---
    try:
        status = json.loads(read_text_artifact(job_id, "status.json"))
        trail["step_timestamps"] = status.get("step_timestamps", {})
        trail["started_at"] = status.get("started_at")
        trail["completed_at"] = status.get("completed_at")
        trail["final_state"] = status.get("state")
    except Exception as e:
        logger.warning(f"[AuditTrail] Could not read status for {job_id}: {e}")
        trail["status_error"] = str(e)

    # --- Step A: evidence summary ---
    try:
        evidence = json.loads(read_text_artifact(job_id, "step_a_evidence.json"))
        sections = evidence.get("sections", {})
        weak_count = sum(
            1 for items in sections.values() if isinstance(items, list)
            for item in items
            if isinstance(item, dict) and item.get("confidence") == "low"
        )
        trail["step_a"] = {
            "section_count": len(sections),
            "weak_evidence_items": weak_count,
        }
    except Exception:
        trail["step_a"] = {"status": "artifact_absent"}

    # --- Step B: report summary ---
    try:
        report = json.loads(read_text_artifact(job_id, "step_b_report.json"))
        trail["step_b"] = {
            "section_count": len(report.get("sections", [])),
        }
    except Exception:
        trail["step_b"] = {"status": "artifact_absent"}

    # --- Step C: correction summary ---
    try:
        corr = json.loads(read_text_artifact(job_id, "step_c_correction_log.json"))
        trail["step_c"] = {
            "correction_count": corr.get("correction_count", 0),
            "validated_at": corr.get("validated_at"),
        }
    except Exception:
        trail["step_c"] = {"status": "artifact_absent"}

    # --- Artifact inventory ---
    try:
        artifacts = list_files(job_id, "artifacts")
        trail["artifacts"] = [Path(p).name for p in artifacts]
    except Exception:
        trail["artifacts"] = []

    return trail


def write_audit_trail(job_id: str) -> str:
    """Build and persist audit_trail.json. Returns the artifact path."""
    trail = build_audit_trail(job_id)
    path = save_text_artifact(
        job_id, "audit_trail.json",
        json.dumps(trail, indent=2, default=str),
    )
    logger.info(
        f"[AuditTrail] Written for job {job_id} — "
        f"{len(trail.get('artifacts', []))} artifacts recorded."
    )
    return path

