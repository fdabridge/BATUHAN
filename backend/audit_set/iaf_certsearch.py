"""IAF CertSearch registration used before final certificate issuance.

The IAF account controls whether a CB API key is assigned to v1 or v2.  Certiva
keeps one canonical v2-shaped payload internally and only translates it when
CertSearch explicitly reports that the key belongs to the other API version.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import re
from typing import Any

import httpx

from audit_set.certificate_generator import CertificateValues, normalize_standard
from calculator.advanced import EA_CODE_NAMES


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

# IAF validates the scheme and standard as an accreditation-specific pair.
# These values mirror the UAF rows shown in this CB account's Standards and
# Schemes register.  They intentionally preserve the register's exact spelling
# because a generic IAF dataset label can still be rejected for this CB.
UAF_SCHEME_NAMES = {
    "QMS": "Quality Management System",
    "EMS": "Environment Management System",
    "OHSMS": "Occupational and Health Management System",
    "FSMS": "Food & Safety Management System",
    "ISMS": "Information Security Management System",
    "ENMS": "Energy Management System",
    "MDQMS": "Medial devices quality managemen system",
    "ABMS": "Anti Bribery Management Systems",
}

IAF_SCHEME_NAMES_BY_ACCREDITATION = {
    "UAF": UAF_SCHEME_NAMES,
}

IAF_ACCREDITATION_BODIES = {
    "UAF": ("United Accreditation Foundation Inc.", "UAF"),
    "TURKAK": ("Turkish Accreditation Agency", "TURKAK"),
    "TÜRKAK": ("Turkish Accreditation Agency", "TURKAK"),
}

_V2_COUNTRY_ALIASES = {
    "tr": "Türkiye",
    "tur": "Türkiye",
    "turkey": "Türkiye",
    "turkiye": "Türkiye",
    "türkiye": "Türkiye",
    "us": "United States of America (the)",
    "usa": "United States of America (the)",
    "united states": "United States of America (the)",
    "united states of america": "United States of America (the)",
    "united states of america (the)": "United States of America (the)",
    "gb": "United Kingdom of Great Britain and Northern Ireland (the)",
    "gbr": "United Kingdom of Great Britain and Northern Ireland (the)",
    "uk": "United Kingdom of Great Britain and Northern Ireland (the)",
    "united kingdom": "United Kingdom of Great Britain and Northern Ireland (the)",
    "united kingdom of great britain and northern ireland (the)": "United Kingdom of Great Britain and Northern Ireland (the)",
    "netherlands": "Netherlands (Kingdom of the)",
    "netherlands (kingdom of the)": "Netherlands (Kingdom of the)",
}

_V1_COUNTRY_ALIASES = {
    "tr": "Turkey",
    "tur": "Turkey",
    "turkiye": "Turkey",
    "türkiye": "Turkey",
    "turkey": "Turkey",
    "united states of america (the)": "United States",
    "united states of america": "United States",
    "united states": "United States",
    "united kingdom of great britain and northern ireland (the)": "United Kingdom",
    "united kingdom": "United Kingdom",
    "netherlands (kingdom of the)": "Netherlands",
    "netherlands": "Netherlands",
}


class IAFCertSearchError(RuntimeError):
    """Safe, user-displayable IAF CertSearch integration failure."""


@dataclass(frozen=True)
class IAFCertSearchRegistration:
    company_certifications_id: str
    verification_url: str


_VERSION_PATH = re.compile(r"/api/client/v(?P<version>[12])/cb/?$", re.IGNORECASE)


def _date(value: date) -> str:
    return value.strftime("%Y%m%d")


def _country_v2(value: Any) -> str:
    country = str(value or "").strip()
    return _V2_COUNTRY_ALIASES.get(country.casefold(), country)


def _country_v1(value: Any) -> str:
    country = str(value or "").strip()
    return _V1_COUNTRY_ALIASES.get(country.casefold(), country)


def _entity_id(audit_set: Any) -> str:
    # The internal audit-set UUID is stable across every standard/cycle and
    # contains no personal information.
    return f"CERTIVA-{str(audit_set.id).replace('-', '').upper()}"


def _additional_sites(
    audit_set: Any,
    entity_id: str,
    scope: str,
    default_country: str,
) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for site in getattr(audit_set, "sites", None) or []:
        if not isinstance(site, dict):
            continue
        full_address = str(site.get("address") or "").strip()
        if not full_address:
            continue
        country = _country_v2(site.get("country") or default_country)
        result.append({
            "certified_entity_unique_id": entity_id,
            "site_type": "Additional Site",
            "street": "",
            "city": "",
            "state": "",
            "zip_code": "",
            "country": country,
            "full_address": full_address,
            "scope_description": str(site.get("process") or scope).strip(),
        })
    return result


def _sectors(audit_set: Any) -> list[dict[str, str]]:
    raw_codes = str(getattr(audit_set, "ea_code", "") or "")
    codes: list[int] = []
    for match in re.finditer(r"(?:\bEA\s*)?(\d{1,4})\b", raw_codes, re.IGNORECASE):
        code = int(match.group(1))
        if code in EA_CODE_NAMES and code not in codes:
            codes.append(code)
    return [
        {
            "sector_name": EA_CODE_NAMES[code],
            "sector_code": f"{code:02d}",
        }
        for code in codes
    ]


def build_certification_payload(
    audit_set: Any,
    standard: str,
    values: CertificateValues,
) -> dict[str, Any]:
    """Map a reviewed Certiva audit set to the official IAF v2 contract."""
    canonical = normalize_standard(standard)
    country = _country_v2(getattr(audit_set, "country", ""))
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
    scheme_name = IAF_SCHEME_NAMES_BY_ACCREDITATION.get(
        accreditation,
        IAF_SCHEME_NAMES,
    )[canonical]

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
                "scheme_name": scheme_name,
                "standard_list": [{"standards_name": IAF_STANDARD_NAMES[canonical]}],
            }],
            "cert_sites": _additional_sites(audit_set, entity_id, scope, country),
            "sectors": _sectors(audit_set),
        },
    }


def _v1_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Translate the canonical v2 CB payload to the official v1 contract."""

    entity = payload.get("certified_entity") or {}
    certification = payload.get("certification") or {}
    sites = []
    for site in certification.get("cert_sites") or []:
        if not isinstance(site, dict):
            continue
        sites.append({
            "street": site.get("street") or site.get("full_address") or "",
            "city": site.get("city") or "",
            "state": site.get("state") or "",
            "country": _country_v1(site.get("country")),
            "postcode": site.get("zip_code") or "",
            "scope_description": site.get("scope_description") or site.get("scope") or "",
        })

    return {
        "certificate_identity_number": certification.get("certificate_identity_number") or "",
        "certificate_number": certification.get("certificate_number") or "",
        "certification_status": certification.get("certification_status") or "",
        "certificate_accreditation_status": certification.get("certificate_accreditation_status") or "",
        "certification_type": certification.get("certification_type") or "",
        "certification_scope": certification.get("certification_scope") or "",
        "certification_original_issue_date": certification.get("certification_original_issue_date") or "",
        "certification_issue_date": certification.get("certification_issue_date") or "",
        "certification_expiry_date": certification.get("certification_expiry_date") or "",
        "certified_entity_name": entity.get("certified_entity_name") or "",
        "certified_entity_english_name": entity.get("certified_entity_english_name") or "",
        "certified_entity_trading_name": entity.get("certified_entity_trading_name") or "",
        "certified_entity_unique_id": entity.get("certified_entity_unique_id") or "",
        "certified_entity_street_address": entity.get("business_registered_street")
        or entity.get("business_registered_full_address") or "",
        "certified_entity_street_city": entity.get("business_registered_city") or "",
        "certified_entity_state": entity.get("business_registered_state") or "",
        "certified_entity_post_code": entity.get("business_registered_zip_code") or "",
        "certified_entity_country": _country_v1(entity.get("business_registered_country")),
        "certified_entity_website": entity.get("certified_entity_website") or "",
        "accreditation_body_name": certification.get("accreditation_body_name") or "",
        "accreditation_body_acronym_name": certification.get("accreditation_body_acronym_name") or "",
        "schemes": certification.get("schemes") or [],
        "sites": sites,
    }


def _error_detail(response: httpx.Response) -> str:
    try:
        error_body = response.json()
    except ValueError:
        return ""
    if not isinstance(error_body, dict):
        return ""
    errors = error_body.get("errors")
    if not isinstance(errors, dict):
        return ""
    message = errors.get("message")
    if message:
        return str(message)
    return str(errors.get("code") or "")


def _alternate_version_request(
    api_base_url: str,
    payload: dict[str, Any],
) -> tuple[str, dict[str, Any]] | None:
    match = _VERSION_PATH.search(api_base_url.rstrip("/"))
    if not match:
        return None
    current = match.group("version")
    alternate = "1" if current == "2" else "2"
    alternate_url = _VERSION_PATH.sub(
        f"/api/client/v{alternate}/cb",
        api_base_url.rstrip("/"),
    )
    return alternate_url, _v1_payload(payload) if alternate == "1" else payload


def _payload_for_base_url(api_base_url: str, payload: dict[str, Any]) -> dict[str, Any]:
    match = _VERSION_PATH.search(api_base_url.rstrip("/"))
    return _v1_payload(payload) if match and match.group("version") == "1" else payload


def _certification_id(response: httpx.Response) -> str:
    try:
        body = response.json()
        data = body.get("data") if isinstance(body, dict) else None
        raw_id = data.get("company_certifications_id") if isinstance(data, dict) else None
        if not raw_id and isinstance(body, dict):
            # The v1 response returns the ID beside a boolean `data` field.
            raw_id = body.get("company_certifications_id")
        return str(raw_id or "").strip()
    except (TypeError, ValueError, AttributeError):
        return ""


def _mapping_context(payload: dict[str, Any]) -> str:
    """Return non-sensitive mapped values to make IAF's generic error useful."""

    entity = payload.get("certified_entity") or {}
    certification = payload.get("certification") or {}
    if not entity and not certification:
        entity = {
            "business_registered_country": payload.get("certified_entity_country"),
        }
        certification = {
            "certification_type": payload.get("certification_type"),
            "certification_status": payload.get("certification_status"),
            "accreditation_body_acronym_name": payload.get("accreditation_body_acronym_name"),
            "schemes": payload.get("schemes") or [],
            # v1 does not accept certification sectors on this endpoint.
            "sectors": [],
        }
    schemes = certification.get("schemes") or []
    scheme_names: list[str] = []
    standard_names: list[str] = []
    for scheme in schemes:
        if not isinstance(scheme, dict):
            continue
        if scheme.get("scheme_name"):
            scheme_names.append(str(scheme["scheme_name"]))
        for standard in scheme.get("standard_list") or []:
            if isinstance(standard, dict) and standard.get("standards_name"):
                standard_names.append(str(standard["standards_name"]))
    sectors = certification.get("sectors") or []
    sector_values = [
        f"{sector.get('sector_code')}/{sector.get('sector_name')}"
        for sector in sectors
        if isinstance(sector, dict)
    ]
    fields = [
        f"country={entity.get('business_registered_country') or 'blank'}",
        f"certification type={certification.get('certification_type') or 'blank'}",
        f"status={certification.get('certification_status') or 'blank'}",
        f"accreditation={certification.get('accreditation_body_acronym_name') or 'blank'}",
        f"scheme={', '.join(scheme_names) or 'blank'}",
        f"standard={', '.join(standard_names) or 'blank'}",
    ]
    if sector_values:
        fields.append(f"sectors={', '.join(sector_values)}")
    return "; ".join(fields)


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

    request_base_url = api_base_url.rstrip("/")
    request_payload = _payload_for_base_url(request_base_url, payload)
    try:
        with httpx.Client(timeout=timeout_seconds) as client:
            response = client.post(
                f"{request_base_url}/upload-cert",
                headers={
                    "Content-Type": "application/json",
                    "x-http-authorization": api_key,
                },
                json=request_payload,
            )

            detail = _error_detail(response)
            version_mismatch = (
                response.status_code == 401
                and "does not match the version settings" in detail.casefold()
            )
            alternate = _alternate_version_request(request_base_url, payload)
            if version_mismatch and alternate:
                request_base_url, request_payload = alternate
                response = client.post(
                    f"{request_base_url}/upload-cert",
                    headers={
                        "Content-Type": "application/json",
                        "x-http-authorization": api_key,
                    },
                    json=request_payload,
                )
    except httpx.RequestError as exc:
        raise IAFCertSearchError(
            "IAF CertSearch could not be reached. No certificate PDF was issued; please retry."
        ) from exc

    if response.status_code >= 400:
        detail = _error_detail(response)
        if detail.strip().rstrip(".").casefold() == "wrong mapping":
            detail = (
                "IAF account mapping rejected one of these values: "
                f"{_mapping_context(request_payload)}. Check Import Settings > Global Mapping "
                "and the UAF accreditation assignment"
            )
        suffix = f": {detail}" if detail else ""
        raise IAFCertSearchError(
            f"IAF CertSearch rejected the certificate registration (HTTP {response.status_code}){suffix}."
        )

    certification_id = _certification_id(response)
    if not certification_id:
        raise IAFCertSearchError(
            "IAF CertSearch accepted the request but did not return a certification ID. No PDF was issued."
        )

    return IAFCertSearchRegistration(
        company_certifications_id=certification_id,
        verification_url=f"{public_base_url.rstrip('/')}/certification/{certification_id}",
    )
