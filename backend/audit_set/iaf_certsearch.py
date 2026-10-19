"""IAF CertSearch v2 registration used before final certificate issuance."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

import httpx

from audit_set.certificate_generator import CertificateValues, normalize_standard


IAF_STANDARD_NAMES = {
    "QMS": "ISO 9001:2015",
    "EMS": "ISO 14001:2015",
    "OHSMS": "ISO 45001:2018",
    "FSMS": "ISO 22000:2018",
    "ISMS": "ISO/IEC 27001:2022",
    "ENMS": "ISO 50001:2018",
    "MDQMS": "ISO 13485:2016",
    "ABMS": "ISO 37001:2016",
}

# These names follow the IAF dataset terminology. IAF data mapping can map a
# CB-specific variant if the accreditation profile uses a different label.
IAF_SCHEME_NAMES = {
    "QMS": "Quality Management Systems",
    "EMS": "Environmental Management Systems",
    "OHSMS": "Occupational Health and Safety Management Systems",
    "FSMS": "Food Safety Management Systems",
    "ISMS": "Information Security Management Systems",
    "ENMS": "Energy Management Systems",
    "MDQMS": "Medical Devices - Quality Management Systems",
    "ABMS": "Anti-Bribery Management Systems",
}

IAF_ACCREDITATION_BODIES = {
    "UAF": ("UNITED ACCREDITATION FOUNDATION INC", "UAF"),
    "TURKAK": ("TURKISH ACCREDITATION AGENCY", "TURKAK"),
    "TÜRKAK": ("TURKISH ACCREDITATION AGENCY", "TURKAK"),
}


class IAFCertSearchError(RuntimeError):
    """Safe, user-displayable IAF CertSearch integration failure."""


@dataclass(frozen=True)
class IAFCertSearchRegistration:
    company_certifications_id: str
    verification_url: str


def _date(value: date) -> str:
    return value.strftime("%Y%m%d")


def _entity_id(audit_set: Any) -> str:
    # The internal audit-set UUID is stable across every standard/cycle and
    # contains no personal information.
    return f"CERTIVA-{str(audit_set.id).replace('-', '').upper()}"


def _additional_sites(audit_set: Any, entity_id: str, scope: str) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for site in getattr(audit_set, "sites", None) or []:
        if not isinstance(site, dict):
            continue
        full_address = str(site.get("address") or "").strip()
        if not full_address:
            continue
        result.append({
            "certified_entity_unique_id": entity_id,
            "site_type": "Additional Site",
            "street": "",
            "city": "",
            "state": "",
            "zip_code": "",
            "country": str(getattr(audit_set, "country", "") or "").strip(),
            "full_address": full_address,
            "scope_description": str(site.get("process") or scope).strip(),
        })
    return result


def _sectors(audit_set: Any) -> list[dict[str, str]]:
    code = str(getattr(audit_set, "ea_code", "") or "").strip()
    name = str(getattr(audit_set, "ea_category", "") or "").strip()
    if not code or not name:
        return []
    if code.upper().startswith("EA "):
        code = code[3:].strip()
    return [{"sector_name": name, "sector_code": code}]


def build_certification_payload(
    audit_set: Any,
    standard: str,
    values: CertificateValues,
) -> dict[str, Any]:
    """Map a reviewed Certiva audit set to the official IAF v2 contract."""
    canonical = normalize_standard(standard)
    country = str(getattr(audit_set, "country", "") or "").strip()
    if not country:
        raise IAFCertSearchError(
            "Company country is required before registration with IAF CertSearch."
        )
    accreditation = str(getattr(audit_set, "accreditation_body", "") or "").strip().upper()
    try:
        accreditation_name, accreditation_acronym = IAF_ACCREDITATION_BODIES[accreditation]
    except KeyError as exc:
        raise IAFCertSearchError(
            f"IAF CertSearch mapping is not configured for accreditation body '{accreditation or 'unknown'}'."
        ) from exc

    entity_id = _entity_id(audit_set)
    city = str(getattr(audit_set, "city", "") or "").strip()
    website = str(getattr(audit_set, "website", "") or "").strip()
    address = values.company_address.strip()
    scope = values.scope.strip()

    return {
        "certified_entity": {
            "certified_entity_unique_id": entity_id,
            "certified_entity_name": values.company_name,
            "certified_entity_english_name": values.company_name,
            "confidential_certified_entity": "No",
            "business_registered_city": city,
            "business_registered_country": country,
            "business_registered_full_address": address,
            "certified_entity_website": website,
        },
        "certification": {
            "certificate_identity_number": values.certificate_number,
            "certificate_number": values.certificate_number,
            "certification_status": "Active",
            "certificate_accreditation_status": "Accredited",
            "certification_type": "Management System",
            "certification_scope": scope,
            "certification_original_issue_date": _date(values.initial_date),
            "certification_issue_date": _date(values.issue_date),
            "certification_expiry_date": _date(values.expiry_date),
            "certified_entity_unique_id": entity_id,
            "main_site_city": city,
            "main_site_country": country,
            "main_site_full_address": address,
            "accreditation_body_name": accreditation_name,
            "accreditation_body_acronym_name": accreditation_acronym,
            "confidential_certified_entity": "No",
            "schemes": [{
                "scheme_name": IAF_SCHEME_NAMES[canonical],
                "standard_list": [{"standards_name": IAF_STANDARD_NAMES[canonical]}],
            }],
            "cert_sites": _additional_sites(audit_set, entity_id, scope),
            "sectors": _sectors(audit_set),
        },
    }


def register_certification(
    *,
    api_key: str,
    api_base_url: str,
    public_base_url: str,
    timeout_seconds: float,
    payload: dict[str, Any],
) -> IAFCertSearchRegistration:
    """Create/update the IAF certification and return its public QR target."""
    if not api_key.strip():
        raise IAFCertSearchError(
            "IAF CertSearch API key is not configured. Add the CB API key before issuing certificates."
        )

    endpoint = f"{api_base_url.rstrip('/')}/upload-cert"
    try:
        with httpx.Client(timeout=timeout_seconds) as client:
            response = client.post(
                endpoint,
                headers={
                    "Content-Type": "application/json",
                    "x-http-authorization": api_key,
                },
                json=payload,
            )
    except httpx.RequestError as exc:
        raise IAFCertSearchError(
            "IAF CertSearch could not be reached. No certificate PDF was issued; please retry."
        ) from exc

    if response.status_code >= 400:
        detail = ""
        try:
            error_body = response.json()
            errors = error_body.get("errors") if isinstance(error_body, dict) else None
            if isinstance(errors, dict):
                message = errors.get("message")
                detail = str(message) if message else str(errors.get("code") or "")
        except ValueError:
            detail = ""
        suffix = f": {detail}" if detail else ""
        raise IAFCertSearchError(
            f"IAF CertSearch rejected the certificate registration (HTTP {response.status_code}){suffix}."
        )

    try:
        certification_id = str(response.json()["data"]["company_certifications_id"]).strip()
    except (KeyError, TypeError, ValueError) as exc:
        raise IAFCertSearchError(
            "IAF CertSearch accepted the request but did not return a certification ID. No PDF was issued."
        ) from exc
    if not certification_id:
        raise IAFCertSearchError(
            "IAF CertSearch returned an empty certification ID. No PDF was issued."
        )

    return IAFCertSearchRegistration(
        company_certifications_id=certification_id,
        verification_url=f"{public_base_url.rstrip('/')}/certification/{certification_id}",
    )
