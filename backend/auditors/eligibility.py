"""
BATUHAN — Auditor Eligibility Engine.

check_eligibility() evaluates whether a given auditor may legally perform
an audit for a specific standard, EA scope, and accreditation body.

Hard blocks  → eligible=False  (IAF / accreditation body requirements)
Warnings     → eligible=True   (items to verify before issuing the certificate)
"""
from __future__ import annotations
from datetime import date, timedelta

from sqlalchemy.orm import Session

from auditors.models import Auditor, AuditorStandardQualification
from auditors.schemas import EligibilityResultSchema

_THREE_YEARS = timedelta(days=3 * 365)
_ONE_YEAR    = timedelta(days=365)


def _ea_int(code: str) -> int | None:
    """Normalise 'EA 28', 'EA28', '28' → 28. Returns None if unparseable."""
    import re
    m = re.search(r'\d+', str(code))
    return int(m.group()) if m else None


def check_eligibility(
    db: Session,
    auditor_id: str,
    standard_code: str,
    company_ea_code: str,
    accreditation_body: str,
    role: str,
) -> EligibilityResultSchema:
    """
    Run all eligibility checks for the given auditor + audit context.
    Always returns an EligibilityResultSchema — never raises.
    eligible=True only when blocking_reasons is empty.
    """
    auditor = db.query(Auditor).filter(Auditor.id == auditor_id).first()
    if not auditor:
        return EligibilityResultSchema(
            eligible=False,
            blocking_reasons=["Auditor not found."],
            warnings=[],
        )

    blocking_reasons: list[str] = []
    warnings: list[str] = []
    today = date.today()

    # ── Hard blocks ────────────────────────────────────────────

    if not auditor.is_active:
        blocking_reasons.append("Auditor profile is inactive.")

    # Fetch qualification row first — needed for both the EA check and warnings
    qual = (
        db.query(AuditorStandardQualification)
        .filter(
            AuditorStandardQualification.auditor_id == auditor_id,
            AuditorStandardQualification.standard_code == standard_code,
            AuditorStandardQualification.is_qualified == True,  # noqa: E712
        )
        .first()
    )
    if not qual:
        blocking_reasons.append(
            f"Auditor has no active qualification recorded for {standard_code}."
        )

    # EA code check — use per-standard qual.ea_codes if available, else top-level
    # Normalise with _ea_int() so "EA 28", "EA28", and "28" all compare as 28.
    company_ea_int = _ea_int(company_ea_code)
    qual_ea_codes  = (qual.ea_codes if qual else None) or auditor.ea_codes or []
    if company_ea_int is not None:
        auditor_ea_ints = {_ea_int(c) for c in qual_ea_codes} - {None}
        if company_ea_int not in auditor_ea_ints:
            blocking_reasons.append(
                f"Auditor EA codes {qual_ea_codes} do not cover the client scope "
                f"{company_ea_code}. IAF MD22 requires a matching EA code."
            )
    elif qual_ea_codes and company_ea_code not in qual_ea_codes:
        # Fallback: plain string match when company_ea_code isn't numeric format
        blocking_reasons.append(
            f"Auditor EA codes {qual_ea_codes} do not cover the client scope "
            f"{company_ea_code}. IAF MD22 requires a matching EA code."
        )

    accreditation_bodies = auditor.accreditation_bodies or []
    if accreditation_body not in accreditation_bodies:
        blocking_reasons.append(
            f"Auditor is not authorized under {accreditation_body}."
        )

    # ── Warnings (only computable when the qualification row exists) ───

    if qual:
        # Training currency — must be within 3 years
        if qual.last_training_date:
            try:
                ltr = date.fromisoformat(qual.last_training_date)
                if ltr < today - _THREE_YEARS:
                    warnings.append(
                        f"Last training for {standard_code} was on "
                        f"{qual.last_training_date}. Verify currency."
                    )
            except ValueError:
                pass  # malformed date — ignore silently

        # Lead auditor minimum experience
        if role == "lead_auditor" and (qual.experience_years or 0) < 2:
            warnings.append(
                f"Auditor has fewer than 2 years of experience in {standard_code}. "
                "Confirm lead auditor eligibility with the accreditation body."
            )

    # TURKAK annual verification — checked regardless of qual existence
    if accreditation_body == "TURKAK":
        last_verified: date | None = None
        if qual and qual.last_verified_date:
            try:
                last_verified = date.fromisoformat(qual.last_verified_date)
            except ValueError:
                pass
        if last_verified is None or last_verified < today - _ONE_YEAR:
            warnings.append(
                "TÜRKAK requires annual competency verification. "
                "No recent verification date on record."
            )

    return EligibilityResultSchema(
        eligible=len(blocking_reasons) == 0,
        blocking_reasons=blocking_reasons,
        warnings=warnings,
    )
