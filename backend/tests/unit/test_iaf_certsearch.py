from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import httpx
import pytest

from audit_set.certificate_generator import CertificateValues
from audit_set.iaf_certsearch import (
    IAFCertSearchError,
    build_certification_payload,
    register_certification,
)


def _audit_set(**overrides):
    values = {
        "id": "123e4567-e89b-12d3-a456-426614174000",
        "country": "Germany",
        "city": "Dortmund",
        "website": "https://example.test",
        "accreditation_body": "UAF",
        "ea_code": "EA 18",
        "ea_category": "Machinery and equipment",
        "sites": [
            {
                "address": "Plant 2, Essen, Germany",
                "process": "Assembly",
            }
        ],
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _certificate_values() -> CertificateValues:
    return CertificateValues(
        company_name="Example Manufacturing Limited",
        company_address="12 Certification Avenue, Dortmund, Germany",
        scope="Manufacture and distribution of example products",
        initial_date=date(2026, 1, 2),
        issue_date=date(2026, 10, 19),
        revision="0",
        validity_date=date(2027, 10, 18),
        expiry_date=date(2029, 1, 1),
        certificate_number="IFC-Q-1-26-1801",
    )


def test_payload_matches_iaf_v2_contract_and_keeps_personal_data_out():
    payload = build_certification_payload(_audit_set(), "QMS", _certificate_values())

    entity = payload["certified_entity"]
    certification = payload["certification"]
    assert entity["certified_entity_unique_id"] == "CERTIVA-123E4567E89B12D3A456426614174000"
    assert entity["certified_entity_english_name"] == "Example Manufacturing Limited"
    assert "email" not in entity
    assert "phone" not in entity
    assert certification["certificate_identity_number"] == "IFC-Q-1-26-1801"
    assert certification["certification_status"] == "Active"
    assert certification["certification_original_issue_date"] == "20260102"
    assert certification["certification_issue_date"] == "20261019"
    assert certification["certification_expiry_date"] == "20290101"
    assert certification["accreditation_body_name"] == "UNITED ACCREDITATION FOUNDATION INC"
    assert certification["schemes"] == [{
        "scheme_name": "Quality Management Systems",
        "standard_list": [{"standards_name": "ISO 9001:2015"}],
    }]
    assert certification["cert_sites"][0]["full_address"] == "Plant 2, Essen, Germany"
    assert certification["sectors"] == [{
        "sector_name": "Machinery and equipment",
        "sector_code": "18",
    }]


def test_payload_requires_country_before_external_registration():
    with pytest.raises(IAFCertSearchError, match="country is required"):
        build_certification_payload(_audit_set(country=""), "QMS", _certificate_values())


def test_isms_uses_the_iaf_iso_iec_standard_name():
    payload = build_certification_payload(_audit_set(), "ISMS", _certificate_values())
    scheme = payload["certification"]["schemes"][0]
    assert scheme["standard_list"] == [{"standards_name": "ISO/IEC 27001:2022"}]


def test_registration_uses_returned_iaf_id_as_certificate_verification_url(monkeypatch):
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["key"] = request.headers.get("x-http-authorization")
        return httpx.Response(
            200,
            json={"data": {"company_certifications_id": "iaf-record-123"}},
        )

    transport = httpx.MockTransport(handler)
    real_client = httpx.Client
    monkeypatch.setattr(
        "audit_set.iaf_certsearch.httpx.Client",
        lambda **kwargs: real_client(transport=transport, **kwargs),
    )

    result = register_certification(
        api_key="secret-test-key",
        api_base_url="https://api.sandbox.iafcertsearch.org/api/client/v2/cb",
        public_base_url="https://www.iafcertsearch.org",
        timeout_seconds=5,
        payload={"certified_entity": {}, "certification": {}},
    )

    assert seen["url"] == "https://api.sandbox.iafcertsearch.org/api/client/v2/cb/upload-cert"
    assert seen["key"] == "secret-test-key"
    assert result.company_certifications_id == "iaf-record-123"
    assert result.verification_url == "https://www.iafcertsearch.org/certification/iaf-record-123"


def test_registration_failure_exposes_validation_detail_but_not_api_key(monkeypatch):
    transport = httpx.MockTransport(lambda request: httpx.Response(
        422,
        json={"errors": {"code": "validation_error", "message": "Invalid Accreditation"}},
    ))
    real_client = httpx.Client
    monkeypatch.setattr(
        "audit_set.iaf_certsearch.httpx.Client",
        lambda **kwargs: real_client(transport=transport, **kwargs),
    )

    with pytest.raises(IAFCertSearchError) as caught:
        register_certification(
            api_key="do-not-leak-this-key",
            api_base_url="https://api.iafcertsearch.org/api/client/v2/cb",
            public_base_url="https://www.iafcertsearch.org",
            timeout_seconds=5,
            payload={},
        )

    assert "Invalid Accreditation" in str(caught.value)
    assert "do-not-leak-this-key" not in str(caught.value)
