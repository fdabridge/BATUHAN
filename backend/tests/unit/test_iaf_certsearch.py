from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import httpx
import pytest

from audit_set.certificate_generator import CertificateValues
from audit_set.iaf_certsearch import (
    IAFCertSearchError,
    _v1_payload,
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
    assert certification["accreditation_body_name"] == "United Accreditation Foundation Inc."
    assert certification["schemes"] == [{
        "scheme_name": "Quality Management System",
        "standard_list": [{"standards_name": "ISO 9001:2015"}],
    }]
    assert certification["cert_sites"][0]["full_address"] == "Plant 2, Essen, Germany"
    assert certification["sectors"] == [{
        "sector_name": "Machinery and equipment",
        "sector_code": "18",
    }]


def test_payload_uses_official_country_and_multiple_ea_sector_values():
    payload = build_certification_payload(
        _audit_set(
            country="USA",
            ea_code="EA 3, EA 29",
            ea_category="Free-text value must not be submitted as an IAF mapping",
        ),
        "QMS",
        _certificate_values(),
    )

    assert payload["certified_entity"]["business_registered_country"] == (
        "United States of America (the)"
    )
    assert payload["certification"]["main_site_country"] == (
        "United States of America (the)"
    )
    assert payload["certification"]["sectors"] == [
        {"sector_name": "Food products, beverages and tobacco", "sector_code": "03"},
        {"sector_name": "Wholesale and retail trade", "sector_code": "29"},
    ]


def test_payload_normalizes_ascii_turkiye_for_entity_main_and_additional_sites():
    payload = build_certification_payload(
        _audit_set(
            country="Turkiye",
            sites=[
                {"address": "Plant 2, Ankara", "process": "Assembly"},
                {
                    "address": "Plant 3, Istanbul",
                    "process": "Distribution",
                    "country": "TURKIYE",
                },
            ],
        ),
        "QMS",
        _certificate_values(),
    )

    assert payload["certified_entity"]["business_registered_country"] == "Türkiye"
    assert payload["certification"]["main_site_country"] == "Türkiye"
    assert [site["country"] for site in payload["certification"]["cert_sites"]] == [
        "Türkiye",
        "Türkiye",
    ]


def test_payload_requires_country_before_external_registration():
    with pytest.raises(IAFCertSearchError, match="country is required"):
        build_certification_payload(_audit_set(country=""), "QMS", _certificate_values())


def test_isms_uses_the_iaf_iso_iec_standard_name():
    payload = build_certification_payload(_audit_set(), "ISMS", _certificate_values())
    scheme = payload["certification"]["schemes"][0]
    assert scheme["standard_list"] == [{"standards_name": "ISO/IEC 27001:2022"}]


@pytest.mark.parametrize(
    ("standard", "expected_scheme", "expected_standard"),
    [
        ("QMS", "Quality Management System", "ISO 9001:2015"),
        ("EMS", "Environment Management System", "ISO 14001:2015"),
        ("OHSMS", "Occupational and Health Management System", "ISO 45001:2018"),
        ("FSMS", "Food & Safety Management System", "ISO 22000:2018"),
        ("ISMS", "Information Security Management System", "ISO/IEC 27001:2022"),
        ("ENMS", "Energy Management System", "ISO 50001:2018"),
        ("MDQMS", "Medial devices quality managemen system", "ISO 13485:2016"),
        ("ABMS", "Anti Bribery Management Systems", "ISO 37001:2016"),
    ],
)
def test_every_supported_certificate_uses_its_iaf_scheme_and_standard(
    standard: str,
    expected_scheme: str,
    expected_standard: str,
):
    payload = build_certification_payload(_audit_set(), standard, _certificate_values())

    assert payload["certification"]["schemes"] == [{
        "scheme_name": expected_scheme,
        "standard_list": [{"standards_name": expected_standard}],
    }]


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


def test_v1_payload_flattens_the_v2_entity_and_certification_contract():
    canonical = build_certification_payload(_audit_set(), "QMS", _certificate_values())

    payload = _v1_payload(canonical)

    assert "certified_entity" not in payload
    assert "certification" not in payload
    assert payload["certificate_number"] == "IFC-Q-1-26-1801"
    assert payload["certified_entity_name"] == "Example Manufacturing Limited"
    assert payload["certified_entity_street_address"] == (
        "12 Certification Avenue, Dortmund, Germany"
    )
    assert payload["certified_entity_country"] == "Germany"
    assert payload["schemes"][0]["standard_list"] == [
        {"standards_name": "ISO 9001:2015"}
    ]
    assert payload["sites"][0]["street"] == "Plant 2, Essen, Germany"


def test_v1_payload_uses_the_v1_country_dataset_names():
    canonical = build_certification_payload(
        _audit_set(country="United States"),
        "QMS",
        _certificate_values(),
    )

    payload = _v1_payload(canonical)

    assert canonical["certified_entity"]["business_registered_country"] == (
        "United States of America (the)"
    )
    assert payload["certified_entity_country"] == "United States"


def test_v1_payload_uses_legacy_turkey_name_for_ascii_turkiye_input():
    canonical = build_certification_payload(
        _audit_set(country="Turkiye"),
        "QMS",
        _certificate_values(),
    )

    payload = _v1_payload(canonical)

    assert canonical["certified_entity"]["business_registered_country"] == "Türkiye"
    assert payload["certified_entity_country"] == "Turkey"
    assert payload["sites"][0]["country"] == "Turkey"


def test_registration_retries_v1_only_after_explicit_version_mismatch(monkeypatch):
    requests: list[tuple[str, dict]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        request_payload = __import__("json").loads(request.content)
        requests.append((str(request.url), request_payload))
        if "/v2/" in str(request.url):
            return httpx.Response(
                401,
                json={
                    "errors": {
                        "code": "invalid_api_version",
                        "message": "The api being accessed does not match the version settings.",
                    }
                },
            )
        return httpx.Response(
            200,
            json={"data": True, "company_certifications_id": "iaf-v1-record"},
        )

    transport = httpx.MockTransport(handler)
    real_client = httpx.Client
    monkeypatch.setattr(
        "audit_set.iaf_certsearch.httpx.Client",
        lambda **kwargs: real_client(transport=transport, **kwargs),
    )
    canonical = build_certification_payload(_audit_set(), "QMS", _certificate_values())

    result = register_certification(
        api_key="v1-configured-key",
        api_base_url="https://api.iafcertsearch.org/api/client/v2/cb",
        public_base_url="https://www.iafcertsearch.org",
        timeout_seconds=5,
        payload=canonical,
    )

    assert [url for url, _ in requests] == [
        "https://api.iafcertsearch.org/api/client/v2/cb/upload-cert",
        "https://api.iafcertsearch.org/api/client/v1/cb/upload-cert",
    ]
    assert "certified_entity" in requests[0][1]
    assert "certified_entity" not in requests[1][1]
    assert requests[1][1]["certificate_number"] == "IFC-Q-1-26-1801"
    assert result.company_certifications_id == "iaf-v1-record"


def test_configured_v1_endpoint_receives_the_flat_v1_contract(monkeypatch):
    received: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        received.update(__import__("json").loads(request.content))
        return httpx.Response(
            200,
            json={"data": True, "company_certifications_id": "configured-v1-record"},
        )

    transport = httpx.MockTransport(handler)
    real_client = httpx.Client
    monkeypatch.setattr(
        "audit_set.iaf_certsearch.httpx.Client",
        lambda **kwargs: real_client(transport=transport, **kwargs),
    )
    canonical = build_certification_payload(_audit_set(), "QMS", _certificate_values())

    result = register_certification(
        api_key="v1-key",
        api_base_url="https://api.iafcertsearch.org/api/client/v1/cb",
        public_base_url="https://www.iafcertsearch.org",
        timeout_seconds=5,
        payload=canonical,
    )

    assert "certified_entity" not in received
    assert "certification" not in received
    assert received["certificate_number"] == "IFC-Q-1-26-1801"
    assert result.company_certifications_id == "configured-v1-record"


def test_registration_does_not_retry_an_unrelated_unauthorized_response(monkeypatch):
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(
            401,
            json={"errors": {"message": "Invalid Session token has been used."}},
        )

    transport = httpx.MockTransport(handler)
    real_client = httpx.Client
    monkeypatch.setattr(
        "audit_set.iaf_certsearch.httpx.Client",
        lambda **kwargs: real_client(transport=transport, **kwargs),
    )

    with pytest.raises(IAFCertSearchError, match="Invalid Session token"):
        register_certification(
            api_key="invalid-key",
            api_base_url="https://api.iafcertsearch.org/api/client/v2/cb",
            public_base_url="https://www.iafcertsearch.org",
            timeout_seconds=5,
            payload={},
        )

    assert calls == 1


def test_wrong_mapping_error_lists_only_safe_mapping_candidates(monkeypatch):
    transport = httpx.MockTransport(lambda request: httpx.Response(
        400,
        json={"errors": {"message": "Wrong mapping."}},
    ))
    real_client = httpx.Client
    monkeypatch.setattr(
        "audit_set.iaf_certsearch.httpx.Client",
        lambda **kwargs: real_client(transport=transport, **kwargs),
    )
    canonical = build_certification_payload(_audit_set(), "QMS", _certificate_values())

    with pytest.raises(IAFCertSearchError) as caught:
        register_certification(
            api_key="must-not-appear",
            api_base_url="https://api.iafcertsearch.org/api/client/v1/cb",
            public_base_url="https://www.iafcertsearch.org",
            timeout_seconds=5,
            payload=canonical,
        )

    message = str(caught.value)
    assert "country=Germany" in message
    assert "accreditation=UAF" in message
    assert "scheme=Quality Management System" in message
    assert "standard=ISO 9001:2015" in message
    assert "must-not-appear" not in message
