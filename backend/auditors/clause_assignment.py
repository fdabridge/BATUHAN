"""
BATUHAN — Multi-Auditor Clause Assignment Suggester.

suggest_clause_assignment() proposes which auditor covers which clauses
based on role seniority, technical depth, and experience years.
Read-only — nothing is persisted.

Ranking (higher = more complex clauses):
  lead_auditor role       → +100
  technical_depth="technical" → +50
  experience_years        → +N (direct)

Group split by section prefix:
  A  4.x / 5.x / 6.x  — Context & Planning
  B  7.x              — Support
  C  8.x              — Operation
  D  9.x / 10.x       — Evaluation & Improvement
"""
from __future__ import annotations
from pydantic import BaseModel
from sqlalchemy.orm import Session

from auditors.models import Auditor, AuditorStandardQualification


class ClauseAssignmentRequest(BaseModel):
    auditor_ids: list[str]
    standard_code: str


# ── Internal helpers ───────────────────────────────────────────

def _rank(auditor: Auditor, qual: AuditorStandardQualification | None) -> int:
    score = 0
    if auditor.role and auditor.role.lower() == "lead_auditor":
        score += 100
    if qual:
        if (qual.technical_depth or "").lower() == "technical":
            score += 50
        score += qual.experience_years or 0
    return score


def _split_equal(items: list, n: int) -> list[list]:
    """Divide items into n roughly equal chunks (last chunk may be smaller)."""
    if not n or not items:
        return [[] for _ in range(n)]
    k, rem = divmod(len(items), n)
    chunks, start = [], 0
    for i in range(n):
        end = start + k + (1 if i < rem else 0)
        chunks.append(items[start:end])
        start = end
    return chunks


def _clause_dict(c) -> dict:
    """Normalize a ClauseConfig object to a plain dict for the API response."""
    return {
        "clause_id": c.clause_id,
        "title": c.title,
        "applicability": c.applicability,   # Applicability is str,Enum — serialises as string
    }


# ── Main function ──────────────────────────────────────────────

def suggest_clause_assignment(
    db: Session,
    auditor_ids: list[str],
    standard_code: str,
) -> dict:
    """
    Returns a suggestion dict — raises if no clause config exists for standard_code.
    Caller is responsible for catching and converting to HTTP 422.
    """
    from config.clause_configs.loader import load_clause_config

    config = load_clause_config(standard_code)          # raises if not found
    clauses = [_clause_dict(c) for c in config.clauses]

    # ── Fetch and rank auditors ────────────────────────────────
    ranked: list[tuple[Auditor, AuditorStandardQualification | None, int]] = []
    for aid in auditor_ids:
        auditor = db.query(Auditor).filter(Auditor.id == aid).first()
        if not auditor:
            continue
        qual = (
            db.query(AuditorStandardQualification)
            .filter(
                AuditorStandardQualification.auditor_id == aid,
                AuditorStandardQualification.standard_code == standard_code,
            )
            .first()
        )
        ranked.append((auditor, qual, _rank(auditor, qual)))

    ranked.sort(key=lambda t: t[2], reverse=True)   # highest rank first
    n = len(ranked)

    # ── Group clauses by section prefix ───────────────────────
    def _group(*prefixes: str) -> list[dict]:
        return [c for c in clauses if any(c["clause_id"].startswith(p) for p in prefixes)]

    grp_a = _group("4.", "5.", "6.")   # Context & Planning
    grp_b = _group("7.")               # Support
    grp_c = _group("8.")               # Operation
    grp_d = _group("9.", "10.")        # Evaluation & Improvement

    # ── Assign groups by rank position ────────────────────────
    if n == 0:
        clause_lists: list[list] = []
    elif n == 1:
        clause_lists = [grp_a + grp_b + grp_c + grp_d]
    elif n == 2:
        clause_lists = [grp_c + grp_d, grp_a + grp_b]
    elif n == 3:
        clause_lists = [grp_c + grp_d, grp_b, grp_a]
    else:
        # rank 1→D, rank 2→C, rank 3→B; remaining auditors split A equally
        a_splits = _split_equal(grp_a, n - 3)
        clause_lists = [grp_d, grp_c, grp_b] + a_splits

    # ── Build response ─────────────────────────────────────────
    assignments = []
    for i, (auditor, qual, _) in enumerate(ranked):
        assignments.append({
            "auditor_id": auditor.id,
            "auditor_name": auditor.name,
            "role": auditor.role,
            "technical_depth": qual.technical_depth if qual else "general",
            "experience_years": qual.experience_years if qual else 0,
            "assigned_clauses": clause_lists[i] if i < len(clause_lists) else [],
        })

    return {
        "standard_code": standard_code,
        "assignments": assignments,
        "note": "This is a suggested split. Adjust as needed before finalizing.",
    }
