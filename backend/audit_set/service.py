"""
BATUHAN — Audit Set: Service layer (CRUD + calculation bridge).
"""
from __future__ import annotations
import json
import math
import re
import uuid
import logging
from datetime import date
from pathlib import Path

from sqlalchemy import cast, func, or_, String
from sqlalchemy.orm import Session, selectinload
from sqlalchemy.orm.attributes import flag_modified

from audit_set.db_models import AuditSet, AuditSetSharedDocument, AuditSetStage, AuditSetStatusEvent
from audit_set.schemas import (
    AuditSetCertUpdateSchema,
    AuditSetCreateSchema,
    AuditSetUpdatePlanningSchema,
    QuickCalcSchema,
)

logger = logging.getLogger(__name__)


def _stage_member_ids(stage: AuditSetStage) -> set[str]:
    ids: set[str] = set()
    if stage.lead_auditor_id:
        ids.add(stage.lead_auditor_id)
    for attr in ("auditors", "technical_experts", "observers", "trainees", "ik_experts", "evaluators"):
        for member in getattr(stage, attr, None) or []:
            if isinstance(member, dict) and member.get("id"):
                ids.add(str(member["id"]))
    return ids


def _committee_member_ids(audit_set: AuditSet) -> set[str]:
    ids: set[str] = set()
    for member in audit_set.committee_members or []:
        if not isinstance(member, dict):
            continue
        auditor_id = member.get("id") or member.get("auditor_id") or member.get("auditorId")
        if auditor_id:
            ids.add(str(auditor_id))
    return ids


def _validate_transfer_reviewer_choice(audit_set: AuditSet, auditor_id: str | None) -> None:
    """Transfer Reviewer must be separate from the audit/team/review/committee roles."""
    if not auditor_id:
        return
    involved: set[str] = set()
    for stage in audit_set.stages or []:
        involved.update(_stage_member_ids(stage))
    involved.update(_committee_member_ids(audit_set))
    if audit_set.fr218_reviewer_id:
        involved.add(audit_set.fr218_reviewer_id)

    if auditor_id in involved:
        from fastapi import HTTPException
        raise HTTPException(
            status_code=400,
            detail=(
                "Transfer Reviewer must be independent from this audit: choose an auditor "
                "who is not on the audit team, not a technical expert/reviewer, and not "
                "on the certification committee."
            ),
        )

# Standard code → full ISO name understood by calculator/engine.py
_CODE_TO_ISO: dict[str, str] = {
    "QMS":        "ISO 9001",
    "EMS":        "ISO 14001",
    "OHSMS":      "ISO 45001",
    "FSMS":       "ISO 22000",
    "FSSC 22000": "FSSC 22000",
    "MDQMS":      "ISO 13485",
    "MDMS":       "ISO 13485",
    "ISMS":       "ISO 27001",
    "ENMS":       "ISO 50001",
    "EnMS":       "ISO 50001",
    "ABMS":       "ISO 37001",
    "CMS":        "ISO 37301",
}

# Country → default spoken audit language (coordinator may override).
COUNTRY_LANGUAGE: dict[str, str] = {
    "Turkey": "Turkish", "Türkiye": "Turkish",
    "Russia": "Russian", "Bangladesh": "Bengali",
    "United States": "English", "United Kingdom": "English",
    "Germany": "German", "France": "French",
}

# ── Scope-derivation keyword maps ──────────────────────────────────────────
_FOOD_CHAIN_KW: dict[str, tuple[str, ...]] = {
    "CI":   ("meat", "poultry", "fish", "seafood", "dairy", "milk", "yogurt", "cheese", "ice cream", "egg"),
    "CII":  ("fresh juice", "cut vegetable", "fresh produce", "perishable plant", "fresh fruit"),
    "CIII": ("ready meal", "sandwich", "mixed perishable", "prepared food", "ready-to-eat"),
    "CIV":  ("confection", "chocolate", "candy", "biscuit", "cookie", "snack", "chip", "cracker",
             "canned", "ambient", "dried", "cereal", "flour", "rice", "pasta", "edible oil",
             "sauce", "condiment", "frozen", "beverage", "juice in carton", "soft drink", "bottled water",
             "coffee", "tea", "cake", "tortilla", "bread", "bakery", "pastry", "wrap", "gluten",
             "noodle", "wafer"),
    "D":    ("animal feed", "pet food", "feedstuff"),
    "E":    ("catering", "restaurant", "canteen", "food service", "hospitality kitchen"),
    "FI":   ("food retail", "food wholesale", "supermarket", "grocer"),
    "FII":  ("food broker", "food distribution", "food trader"),
    "G":    ("food storage", "cold chain", "food logistics", "food warehousing"),
    "I":    ("food packaging", "packaging material", "food contact material"),
    "K":    ("food chemical", "food additive", "ingredient manufacture", "food enzyme", "vitamin"),
    "BIII": ("plant pre-process", "cleaning of plant", "sorting plant", "packing whole plant"),
    "C0":   ("slaughter", "slaughterhouse", "abattoir", "animal primary"),
}

_MEDICAL_TA_KW: dict[str, tuple[str, ...]] = {
    "A1.1": (
        "bandage", "wound care", "catheter", "surgical instrument", "syringe",
        # Turkish
        "yara örtüsü", "pansuman", "kateter", "cerrahi alet", "şırınga", "enjektör",
        "tek kullanımlık", "disposable",
    ),
    "A1.2": (
        "hip replacement", "dental implant", "non-active implant", "orthopaedic",
        # Turkish
        "kalça protezi", "diş implantı", "kemik çivisi", "ortopedik implant",
        "pasif implant", "aktif olmayan implant",
    ),
    "A1.3": (
        "imaging equipment", "monitoring equipment", "ventilator",
        # Turkish
        "görüntüleme cihazı", "hasta monitörü", "solunum cihazı", "ventilatör",
        "ultrason cihazı", "mri", "tomografi", "endoskop",
    ),
    "A1.4": (
        "pacemaker", "active implant", "defibrillator",
        # Turkish
        "kalp pili", "defibrilatör", "aktif implant", "koklear implant",
    ),
    "A1.5": (
        "sterilization", "sterilisation", "ethylene oxide", "gamma steriliz",
        # Turkish
        "sterilizasyon", "etilen oksit", "gama sterilizasyon", "steril",
        "dezenfeksiyon hizmeti",
    ),
    "A1.6": (
        "software as medical device", "samd", "medical software", "ai medical",
        # Turkish
        "tıbbi yazılım", "tıbbi yapay zeka", "klinik karar destek",
        "sağlık bilgi sistemi", "hastane yönetim sistemi",
    ),
    "A1.7": (
        "medical device component", "medical parts supplier",
        # Turkish
        "tıbbi cihaz bileşeni", "tıbbi parça", "medikal komponent",
        "tıbbi malzeme tedarikçisi",
    ),
    "A2.1": (
        "in-vitro diagnostic", "ivd reagent",
        # Turkish
        "in vitro tanı", "ivd", "teşhis reaktifi", "laboratuvar kiti",
        "biyokimya kiti", "immünoloji kiti",
    ),
    "A2.2": (
        "ivd self-test", "self-testing diagnostic",
        # Turkish
        "kendi kendine test", "hızlı test", "ev tipi test",
        "antijen testi", "hamilelik testi", "glikoz ölçüm",
    ),
    "A2.3": (
        "ivd professional", "professional diagnostic",
        # Turkish
        "profesyonel tanı", "laboratuvar cihazı", "analizör",
        "kan sayım cihazı", "koagülasyon",
    ),
    "A2.4": (
        "companion diagnostic",
        # Turkish
        "eşlik eden tanı", "biyobelirteç testi", "hedefe yönelik tedavi testi",
    ),
}

_SECTOR_KW: dict[str, tuple[str, ...]] = {
    "Public":           ("government", "ministry", "municipality", "public authority", "state-owned", "public sector"),
    "Third sector/NGO": ("ngo", "non-profit", "nonprofit", "charity", "foundation", "association", "third sector"),
}

_ENERGY_HIGH_KW = ("chemical", "steel", "cement", "refinery", "petrochemical", "mining", "smelting")
_ENERGY_MED_KW  = ("manufacturing", "production", "industrial", "plant", "factory", "assembly")

_ISMS_TA_KW: dict[str, tuple[str, ...]] = {
    "D": (
        "data centre", "data center", "critical infrastructure", "cryptography",
        "crypto", "blockchain", "medical device", "payment processing", "fintech",
        "telecom core", "cloud provider", "managed security", "soc service",
        "industrial control", "scada", "ics",
    ),
    "C": (
        "telecom", "telecommunication", "internet service provider", "isp",
        "network operator", "mobile operator", "service provider infrastructure",
        "carrier", "broadband", "hosting provider",
    ),
    "B": (
        "industrial", "manufacturing", "factory", "production", "ot system",
        "operational technology", "automation", "plc", "plant network",
        "warehouse automation",
    ),
    "A": (
        "office", "administrative", "consulting", "software", "it service",
        "human resources", "finance", "accounting", "cloud application",
        "desktop", "server", "business system",
    ),
}


def _unique_preserve(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for raw in values:
        value = str(raw or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def _normalize_ea_code(raw: str | None) -> str | None:
    value = str(raw or "").strip().upper()
    if not value:
        return None
    value = value.replace("IAF", "").replace("EA", "").strip()
    try:
        return f"EA {int(value)}"
    except ValueError:
        return str(raw or "").strip()


def _split_codes(raw: str | None) -> list[str]:
    if not raw:
        return []
    parts = [p.strip() for p in re.split(r"[,;/|\n]+", str(raw))]
    return _unique_preserve([p for p in parts if p])


def _split_ea_codes(raw: str | None) -> list[str]:
    return _unique_preserve([
        code for code in (_normalize_ea_code(part) for part in _split_codes(raw))
        if code
    ])


def _as_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return _unique_preserve([str(v) for v in value])
    return _split_codes(str(value))


def _infer_isms_technical_area(haystack: str) -> str | None:
    for code in ("D", "C", "B", "A"):
        if any(kw in haystack for kw in _ISMS_TA_KW[code]):
            return code
    return None


def _derive_energy_complexity(application_data: dict | None, haystack: str) -> str:
    app = application_data or {}
    try:
        annual_tj = float(app.get("enms_annual_energy_tj") or 0)
    except (TypeError, ValueError):
        annual_tj = 0
    try:
        energy_types = int(app.get("enms_num_energy_types") or 0)
    except (TypeError, ValueError):
        energy_types = 0
    try:
        seu_count = int(app.get("enms_num_seus") or 0)
    except (TypeError, ValueError):
        seu_count = 0

    if energy_types >= 4 or seu_count >= 6 or annual_tj >= 100 or any(kw in haystack for kw in _ENERGY_HIGH_KW):
        return "High"
    if energy_types >= 2 or seu_count >= 3 or annual_tj > 0 or any(kw in haystack for kw in _ENERGY_MED_KW):
        return "Medium"
    return "Low"

# Scope text → EA code keyword map (IAF EA 1–39, per TÜRKAK R40.01 / IAF MD 1)
# Keys are the official IAF EA code numbers. Keyword sets derived from NACE Rev.2 sub-sectors.
_SCOPE_TO_EA_KW: dict[str, tuple[str, ...]] = {
    # EA 1  – Agriculture, forestry and fishing (NACE 01, 02, 03)
    "EA 1":  ("agriculture", "farming", "horticulture", "fishery", "aquaculture",
              "forestry", "livestock", "poultry", "crop", "harvest", "animal husbandry"),

    # EA 2  – Mining and quarrying (NACE 05–09)
    "EA 2":  ("mining", "quarrying", "coal mining", "oil extraction", "gas extraction",
              "mineral extraction", "stone quarry", "gravel extraction", "sand extraction"),

    # EA 3  – Food products, beverages and tobacco (NACE 10, 11, 12)
    "EA 3":  ("food", "beverage", "tobacco", "bakery", "confectionery", "dairy", "meat processing",
              "cake", "tortilla", "snack", "sandwich", "pastry", "bread", "milling", "brewing",
              "gluten", "biscuit", "cookie", "cracker", "noodle", "pasta production",
              "fruit", "nut", "dried fruit", "nuts", "vegetable", "spice", "herb", "grain",
              "cereal", "flour", "sugar", "chocolate", "candy", "jam", "sauce", "condiment",
              "olive", "oil production", "bottling", "canning", "packaging food", "food production",
              "food processing", "food manufacturing", "food storage", "halal", "organic food"),

    # EA 4  – Textiles and textile products (NACE 13, 14)
    "EA 4":  ("textile", "clothing", "apparel", "garment", "fabric", "weaving", "knitting",
              "yarn", "thread", "embroidery", "fashion", "tailor", "sewing"),

    # EA 5  – Leather and leather products (NACE 15)
    "EA 5":  ("leather", "tanning", "hide processing", "skin processing",
              "leather goods", "leatherwork", "footwear"),

    # EA 6  – Wood and wood products (NACE 16)
    "EA 6":  ("wood", "timber", "sawmill", "lumber", "furniture", "carpentry", "joinery",
              "plywood", "particleboard", "woodworking"),

    # EA 7  – Pulp, paper and paper products (NACE 17)
    "EA 7":  ("paper", "pulp", "paperboard", "cardboard", "packaging material",
              "paper manufacturing", "cellulose", "tissue paper", "stationery"),

    # EA 8  – Publishing companies (NACE 58.1, 59.2)
    "EA 8":  ("publishing", "book publishing", "journal publishing", "sound recording",
              "music publishing"),

    # EA 9  – Printing companies (NACE 18)
    "EA 9":  ("printing", "print shop", "offset printing", "digital printing",
              "flexography", "gravure", "screen printing", "print production"),

    # EA 10 – Manufacture of coke and refined petroleum products (NACE 19)
    "EA 10": ("coke production", "coke manufacture", "petroleum refinery", "oil refinery",
              "refining", "fuel production", "refined petroleum"),

    # EA 11 – Nuclear fuel (NACE 24.46)
    "EA 11": ("nuclear", "nuclear fuel", "uranium", "radioactive", "atomic energy"),

    # EA 12 – Chemicals, chemical products and fibres (NACE 20)
    "EA 12": ("chemical", "petrochemical", "fertilizer", "pesticide", "dye", "pigment",
              "adhesive", "paint", "coating", "varnish", "ink", "detergent",
              "industrial chemical", "synthetic fibre", "resin", "cosmetic"),

    # EA 13 – Pharmaceuticals (NACE 21)
    "EA 13": ("pharmaceutical", "medicine", "drug manufacturing", "medication",
              "biopharmaceutical", "vaccine", "active pharmaceutical", "api"),

    # EA 14 – Rubber and plastic products (NACE 22)
    "EA 14": ("rubber", "plastic", "polymer", "composite", "silicone", "elastomer",
              "plastic moulding", "injection moulding", "rubber product"),

    # EA 15 – Non-metallic mineral products (NACE 23, excl. 23.5/23.6)
    "EA 15": ("glass", "ceramic", "stone", "mineral product", "tile", "brick",
              "refractory", "abrasive", "porcelain", "fireclay", "insulation material"),

    # EA 16 – Concrete, cement, lime, plaster (NACE 23.5, 23.6)
    "EA 16": ("concrete", "cement", "lime", "plaster", "mortar", "readymix", "ready-mix",
              "precast", "aggregate", "asphalt"),

    # EA 17 – Basic metals and fabricated metal products (NACE 24 excl. 24.46, 25 excl. 25.4, 33.11)
    "EA 17": ("metal", "steel", "aluminium", "aluminum", "copper", "iron", "zinc",
              "foundry", "forging", "casting", "metallurgy", "welding", "sheet metal",
              "metal fabrication", "structural steel", "metal product", "wire drawing",
              "pipe fitting"),

    # EA 18 – Machinery and equipment (NACE 25.4, 28, 30.4, 33.12, 33.2)
    "EA 18": ("machinery", "equipment manufacturing", "pump", "compressor", "valve",
              "industrial equipment", "machine tool", "lifting equipment",
              "agricultural machinery", "food processing machinery", "mechanical engineering"),

    # EA 19 – Electrical and optical equipment (NACE 26, 27, 33.13, 33.14, 95.1)
    "EA 19": ("electrical", "electronics", "semiconductor", "circuit board", "pcb",
              "electronic component", "optical equipment", "lighting", "motor",
              "transformer", "switchgear", "instrumentation", "measurement equipment",
              "optical instrument"),

    # EA 20 – Shipbuilding (NACE 30.1, 33.15)
    "EA 20": ("shipbuilding", "ship repair", "marine vessel", "yacht", "boat building",
              "naval", "offshore platform", "marine engineering"),

    # EA 21 – Aerospace (NACE 30.3, 33.16)
    "EA 21": ("aerospace", "aircraft", "aviation", "spacecraft", "satellite",
              "helicopter", "aeronautical"),

    # EA 22 – Other transport equipment (NACE 29, 30.2, 30.9, 33.17)
    "EA 22": ("automotive", "vehicle", "car", "truck", "bus", "motorcycle",
              "auto component", "rail vehicle", "locomotive", "tram",
              "transport equipment manufacturing"),

    # EA 23 – Manufacturing not elsewhere classified (NACE 31, 32, 33.19)
    "EA 23": ("furniture manufacturing", "jewellery", "musical instrument", "toy",
              "sport equipment", "sign making", "miscellaneous manufacturing"),

    # EA 24 – Recycling (NACE 38.3)
    "EA 24": ("recycling", "scrap", "secondary raw material", "material recovery",
              "waste recycling", "metal recycling", "paper recycling"),

    # EA 25 – Electricity supply (NACE 35.1)
    "EA 25": ("electricity generation", "power plant", "power generation", "solar power",
              "wind power", "hydroelectric", "electricity supply", "grid operator"),

    # EA 26 – Gas supply (NACE 35.2)
    "EA 26": ("gas supply", "gas distribution", "natural gas", "lpg", "gas network"),

    # EA 27 – Water supply (NACE 35.3, 36)
    "EA 27": ("water supply", "water treatment", "water distribution", "drinking water",
              "water utility", "irrigation"),

    # EA 28 – Construction (NACE 41, 42, 43)
    "EA 28": ("construction", "building", "civil engineering", "infrastructure",
              "contractor", "installation services", "demolition", "real estate development",
              "building contractor", "road construction", "bridge construction", "earthworks"),

    # EA 29 – Wholesale and retail trade (NACE 45, 46, 47, 95.2)
    "EA 29": ("wholesale", "retail", "trade", "distribution", "import", "export",
              "commerce", "sales", "marketing", "medical devices", "medical supplies",
              "medical equipment", "spare parts", "dealership", "reseller", "supplier",
              "procurement", "motor vehicle trade", "consumer goods", "merchandise"),

    # EA 30 – Hotels and restaurants (NACE 55, 56)
    "EA 30": ("hotel", "restaurant", "catering", "hospitality", "tourism",
              "accommodation", "food service", "canteen", "cafeteria", "resort"),

    # EA 31 – Transport, storage and communication (NACE 49, 50, 51, 52, 53, 61)
    "EA 31": ("transport", "logistics", "freight", "courier", "shipping", "warehousing",
              "supply chain", "postal", "air transport", "road transport", "rail transport",
              "sea transport", "telecommunication", "telecom", "internet service provider", "isp"),

    # EA 32 – Financial intermediation; real estate; renting (NACE 64, 65, 66, 68, 77)
    "EA 32": ("financial", "banking", "insurance", "investment", "fintech",
              "asset management", "real estate", "property", "leasing", "renting equipment"),

    # EA 33 – Information technology (NACE 58.2, 62, 63.1)
    "EA 33": ("information technology", "it services", "data centre", "cloud",
              "managed services", "software development", "software house", "it consulting",
              "technology consulting", "saas", "data processing", "web development",
              "cybersecurity"),

    # EA 34 – Engineering services (NACE 71, 72, 74 excl. 74.2/74.3)
    "EA 34": ("engineering services", "technical consulting", "testing laboratory",
              "inspection services", "research and development", "r&d", "technical services",
              "design engineering", "architectural", "surveying", "scientific research"),

    # EA 35 – Other services (NACE 69, 70, 73, 74.2, 74.3, 78, 80, 81, 82)
    "EA 35": ("management consulting", "business services", "legal services", "advisory",
              "accounting", "audit firm", "market research", "advertising agency",
              "photography", "translation", "staffing", "security services",
              "facility management", "cleaning company", "office support"),

    # EA 36 – Public administration (NACE 84)
    "EA 36": ("public administration", "government services", "government agency",
              "ministry", "public authority", "state institution"),

    # EA 37 – Education (NACE 85)
    "EA 37": ("education", "training", "school", "university", "academy", "e-learning",
              "vocational training", "language school", "tutoring"),

    # EA 38 – Health and social work (NACE 75, 86, 87, 88)
    "EA 38": ("healthcare", "hospital", "clinic", "medical services", "diagnostic laboratory",
              "diagnostic", "acupuncture", "physiotherapy", "therapy", "chiropractic",
              "optometry", "pharmacy", "health centre", "health center", "medical centre",
              "medical center", "health services", "patient care", "outpatient",
              "veterinary", "social work", "nursing home", "rehabilitation", "dental"),

    # EA 39 – Other social services (NACE 37, 38.1/38.2, 39, 59–60, 63.9, 79, 90–96)
    "EA 39": ("waste collection", "sewage", "remediation", "film production",
              "media production", "broadcasting", "radio", "television",
              "libraries", "museums", "sports", "recreation", "fitness",
              "membership organisation", "beauty", "laundry", "personal services",
              "travel agency", "cultural activities", "entertainment"),
}

# Keywords for ISO 9001 HIGH risk per IAF MD 5:2023 Table QMS 2.
# Used as fallback when no EA code is set.
_RISK_HIGH_KW: tuple[str, ...] = (
    "food", "pharmaceutical", "medical", "aerospace", "nuclear", "defence",
    "chemical", "petrochemical", "construction", "mining", "oil", "gas",
    "cake", "tortilla", "snack", "sandwich", "dairy", "meat", "bakery",
    "implant", "surgical", "explosive", "shipbuilding",
)
# Keywords for ISO 9001 LOW risk per IAF MD 5:2023 Table QMS 2.
_RISK_LOW_KW: tuple[str, ...] = (
    "software development", "it consulting", "consultancy", "training",
    "education", "media", "publishing", "financial services", "insurance",
    # Textile/clothing = LOW for ISO 9001 per Table QMS 2
    "textile", "textil", "fabric", "garment", "clothing", "apparel", "fashion",
    "yarn", "weaving", "knitting", "spinning",
    # Hotels/Restaurants = LOW for ISO 9001
    "hotel", "restaurant", "hospitality",
)

# ── Per-standard EA-code → risk/complexity tables ─────────────────────────────
# Based on IAF MD 5:2023 Tables QMS 2, EMS 2, and OH&SMS 2.
# Key: integer EA code. Value: category string used by the calculator engine.
# Missing key → "Medium" (safe default per IAF guidance).

# ISO 9001 — Risk category (Table QMS 2)
_QMS_EA_RISK: dict[int, str] = {
    # HIGH risk sectors
    1:  "High",   # Agriculture, Forestry, Fishing (food chain primary production)
    3:  "High",   # Food products, Beverages, Tobacco
    10: "High",   # Shipbuilding
    11: "High",   # Aerospace
    12: "High",   # Chemical products
    13: "High",   # Pharmaceutical
    14: "High",   # Rubber and Plastics (medical/automotive grade)
    16: "High",   # Concrete, cement (complex construction materials)
    18: "High",   # Medical devices
    28: "High",   # Complex construction (bridges, hospitals) — medium for simple builds
    # LOW risk sectors (explicitly listed in Table QMS 2)
    4:  "Low",    # Textile and Leather Products
    5:  "Low",    # Wood and Wood Products (simple/furniture)
    22: "Low",    # Wholesale and Retail trade
    23: "Low",    # Hotels and Restaurants
    29: "Low",    # Computer and related activities / IT services
    31: "Low",    # Education
    32: "Low",    # Health and social work (admin/management; clinical = High)
    33: "Low",    # Other social services
    35: "Low",    # Financial intermediation
    36: "Low",    # Insurance
    37: "Low",    # Postal services
    39: "Low",    # Other social / personal services
    # Medium (not listed — fall through to default)
    # EA 6 Metals, EA 7 Fabricated metals, EA 8 Machinery, EA 9 Electrical, etc.
}

# ISO 14001 — Complexity category (Table EMS 2)
# Note: ISO 14001 uses 4 levels: High / Medium / Low / Limited
_EMS_EA_RISK: dict[int, str] = {
    # HIGH environmental complexity
    2:  "High",   # Mining and Quarrying
    6:  "High",   # Basic Metals (iron, steel, aluminium production)
    7:  "High",   # Fabricated Metal Products (surface treatment, plating)
    8:  "High",   # Machinery and Equipment (heavy manufacturing)
    9:  "High",   # Electrical and Optical Equipment (soldering, chemicals)
    10: "High",   # Shipbuilding
    11: "High",   # Aerospace
    12: "High",   # Chemical products
    13: "High",   # Pharmaceutical (active substances, solvents)
    17: "High",   # Electricity supply / generation
    20: "High",   # Waste water treatment
    21: "High",   # Waste collection and recycling
    # MEDIUM — manufacturing with moderate environmental impact
    1:  "Medium", # Agriculture, Forestry, Fishing
    3:  "Medium", # Food products, Beverages, Tobacco
    4:  "Medium", # Textile and Leather Products (EXCEPT tanning — see keyword override)
    5:  "Medium", # Wood and Wood Products
    14: "Medium", # Rubber and Plastics
    15: "Medium", # Non-metallic mineral products (ceramics, glass)
    16: "Medium", # Concrete, cement, lime
    18: "Medium", # Medical devices
    19: "Medium", # Other transport
    22: "Medium", # Wholesale and Retail trade (large distribution centres)
    24: "Medium", # Construction
    28: "Medium", # Construction (complex civil)
    # LOW — service-dominant sectors
    23: "Low",    # Hotels and Restaurants
    29: "Low",    # Computer and related activities
    30: "Low",    # Research and development
    31: "Low",    # Education
    32: "Low",    # Health and social work (clinics, hospitals)
    33: "Low",    # Other social services
    38: "Low",    # Other social / personal services
    # LIMITED — administrative/holding organisations
    35: "Limited", # Financial intermediation
    36: "Limited", # Insurance
    37: "Limited", # Postal services
    39: "Limited", # Other social services (admin only)
    40: "Limited", # Public administration
}

# ISO 45001 — Risk category (Table OH&SMS 2)
_OHSMS_EA_RISK: dict[int, str] = {
    # HIGH OHS risk sectors
    1:  "High",   # Agriculture, Forestry (chainsaw, tractor, pesticide exposure)
    2:  "High",   # Mining and Quarrying
    10: "High",   # Shipbuilding
    11: "High",   # Aerospace (high-risk assembly)
    12: "High",   # Chemical products
    13: "High",   # Pharmaceutical
    17: "High",   # Electricity supply (electrocution risk)
    20: "High",   # Waste water / sewage treatment
    21: "High",   # Waste collection / recycling
    28: "High",   # Complex construction
    # MEDIUM — manufacturing with moderate OHS risk
    3:  "Medium", # Food products, Beverages, Tobacco
    4:  "Medium", # Textile and Leather Products (EXCEPT dyeing/tanning — see keyword override)
    5:  "Medium", # Wood and Wood Products
    6:  "Medium", # Basic Metals
    7:  "Medium", # Fabricated Metal Products
    8:  "Medium", # Machinery and Equipment
    9:  "Medium", # Electrical and Optical Equipment
    14: "Medium", # Rubber and Plastics
    15: "Medium", # Non-metallic mineral products
    16: "Medium", # Concrete, cement
    18: "Medium", # Medical devices
    19: "Medium", # Other transport and logistics
    22: "Medium", # Wholesale and Retail (warehouse operations)
    24: "Medium", # Construction (simple builds)
    32: "Medium", # Health and social work (needle/pathogen exposure)
    # LOW — office/service dominant
    23: "Low",    # Hotels and Restaurants
    29: "Low",    # Computer and related activities
    30: "Low",    # Research and development
    31: "Low",    # Education
    33: "Low",    # Other social services
    35: "Low",    # Financial intermediation
    36: "Low",    # Insurance
    37: "Low",    # Postal services
    39: "Low",    # Other social / personal services
    40: "Low",    # Public administration
}

# Keyword overrides for sub-sector High risk WITHIN a normally-Medium EA code.
# These override the EA-code table result for specific processes.
# Keys: standard norm strings.  Values: list of (keywords, override_risk) tuples.
_EA_SUBSECTOR_HIGH_KW: dict[str, list[tuple[tuple[str, ...], str]]] = {
    "14001": [
        # Tanning of leather/textiles = High for EMS (Table EMS 2 footnote)
        (("tanning", "tannery", "tabakhane", "deri işleme"), "High"),
    ],
    "45001": [
        # Dyeing of textiles = High for OH&SMS (Table OH&SMS 2 footnote)
        (("dyeing", "boyama", "dye house"), "High"),
        # Tanning = High for OH&SMS too
        (("tanning", "tannery", "tabakhane", "deri işleme"), "High"),
    ],
}


def _first_ea_code_from_scope(required_scope: dict | None) -> str | None:
    """Return the first EA-typed code present in a derived required_scope dict,
    so we can auto-populate `audit_set.ea_code` when the user hasn't set one."""
    for entry in (required_scope or {}).values():
        if not isinstance(entry, dict):
            continue
        if entry.get("type") != "ea":
            continue
        codes = entry.get("codes") or []
        if codes:
            return codes[0]
    return None


def _derived_category_displays(required_scope: dict | None) -> tuple[str | None, str | None]:
    """Return display values for the legacy EA Category / Technical Area fields.

    `required_scope` is the authoritative machine-readable value. These strings
    are only for forms and UI cells that still expect top-level display fields.
    """
    categories: list[str] = []
    technical_areas: list[str] = []
    for iso, entry in (required_scope or {}).items():
        if not isinstance(entry, dict):
            continue
        codes = _unique_preserve([str(c) for c in (entry.get("codes") or [])])
        if not codes:
            continue
        scope_type = entry.get("type")
        value = ", ".join(codes)
        labelled = f"{iso}: {value}"
        if scope_type in ("food", "sector", "energy"):
            categories.append(labelled)
        elif scope_type in ("medical", "isms"):
            technical_areas.append(labelled)
    return (
        "; ".join(categories) if categories else None,
        "; ".join(technical_areas) if technical_areas else None,
    )


def _auto_populate_ea_fields(audit_set: AuditSet) -> None:
    """Populate `audit_set.ea_code` from required_scope when no manual code is set.
    Re-derives required_scope first if it is empty but scope + standards are
    available, so legacy audit sets created before auto-derive still benefit."""
    if (not audit_set.required_scope) and audit_set.standards and (audit_set.scope_en or audit_set.scope_tr):
        try:
            audit_set.required_scope = derive_required_scope(
                standards=audit_set.standards or [],
                scope_tr=audit_set.scope_tr,
                scope_en=audit_set.scope_en,
                ea_code=audit_set.ea_code,
                application_data=audit_set.application_data,
            )
        except Exception as exc:                                     # pragma: no cover
            logger.warning("[AuditSet] auto-derive in _auto_populate_ea_fields failed: %s", exc)
            return
    if not audit_set.ea_code:
        inferred = _first_ea_code_from_scope(audit_set.required_scope)
        if inferred:
            audit_set.ea_code = inferred
    derived_category, derived_technical_area = _derived_category_displays(audit_set.required_scope)
    if not audit_set.ea_category and derived_category:
        audit_set.ea_category = derived_category
    if not audit_set.ea_technical_area and derived_technical_area:
        audit_set.ea_technical_area = derived_technical_area


def derive_required_scope(
    standards: list[str],
    scope_tr: str | None,
    scope_en: str | None,
    ea_code: str | None,
    application_data: dict | None = None,
) -> dict:
    """
    Derive per-standard required scope codes from the client's scope text.

    Returns a dict keyed by the ISO standard name:
      {"ISO 22000": {"type": "food", "codes": ["CI", "CIV"]}, ...}
    """
    haystack = f"{scope_tr or ''} {scope_en or ''}".lower()
    app_data = application_data or {}
    result: dict = {}

    for abbr in (standards or []):
        iso = _CODE_TO_ISO.get(abbr, abbr)
        norm = iso.lower().replace("iso ", "").replace(" ", "")

        if "22000" in norm or "fssc" in norm:
            explicit = _as_list(app_data.get("fsms_food_chain_categories"))
            codes = explicit or [
                c for c, kws in _FOOD_CHAIN_KW.items()
                if any(kw in haystack for kw in kws)
            ]
            result[iso] = {"type": "food", "codes": codes}

        elif "13485" in norm:
            codes = [c for c, kws in _MEDICAL_TA_KW.items() if any(kw in haystack for kw in kws)]
            result[iso] = {"type": "medical", "codes": codes}

        elif "37001" in norm or "37301" in norm:
            sector = "Private"
            for s, kws in _SECTOR_KW.items():
                if any(kw in haystack for kw in kws):
                    sector = s
                    break
            result[iso] = {"type": "sector", "codes": [sector]}

        elif "50001" in norm:
            complexity = _derive_energy_complexity(app_data, haystack)
            result[iso] = {"type": "energy", "codes": [complexity]}

        elif "27001" in norm:
            technical_area = app_data.get("isms_technical_area") or _infer_isms_technical_area(haystack)
            result[iso] = {
                "type": "isms",
                "codes": [technical_area] if technical_area else [],
            }

        elif any(n in norm for n in ("9001", "14001", "45001")):
            # Use stored ea_code if available, otherwise infer from scope text
            if ea_code:
                codes = _split_ea_codes(ea_code)
            else:
                codes = [
                    ea for ea, kws in _SCOPE_TO_EA_KW.items()
                    if any(kw in haystack for kw in kws)
                ]

            # ── Select the correct per-standard EA risk table ──────────────────
            if "9001" in norm:
                ea_table = _QMS_EA_RISK
            elif "14001" in norm:
                ea_table = _EMS_EA_RISK
            elif "45001" in norm:
                ea_table = _OHSMS_EA_RISK
            else:
                ea_table = {}   # ISO 27001 — no EA-table; fall through to keywords

            risk = "Medium"  # IAF-recommended default when sector is unclassified

            # Step 1: EA-code lookup (most reliable — planner-set code)
            if codes and ea_table:
                try:
                    ea_int = int(codes[0].strip().upper().replace("EA", "").replace(" ", ""))
                    risk = ea_table.get(ea_int, "Medium")
                except (ValueError, AttributeError):
                    pass  # malformed ea_code — fall through

            # Step 2: Sub-sector keyword override (e.g. tanning within EA 4)
            # Can upgrade a Medium EA code to High based on specific process keywords
            std_key = norm.replace("iso", "").replace(" ", "")
            for (kws, override) in _EA_SUBSECTOR_HIGH_KW.get(std_key, []):
                if any(kw in haystack for kw in kws):
                    risk = override
                    break

            # Step 3: Keyword fallback when no EA code was set
            if not ea_code:
                if "9001" in norm or "27001" in norm:
                    # For QMS/ISMS use the QMS keyword lists
                    if any(kw in haystack for kw in _RISK_HIGH_KW):
                        risk = "High"
                    elif any(kw in haystack for kw in _RISK_LOW_KW):
                        risk = "Low"
                else:
                    # For EMS/OH&SMS without EA code, use conservative keyword scan
                    # Tanning/dyeing → High; everything else stays Medium
                    high_process_kw = ("tanning", "tannery", "tabakhane", "deri işleme",
                                       "dyeing", "boyama", "chemical production",
                                       "kimyasal üretim", "mining", "maden")
                    low_service_kw = ("education", "finance", "insurance", "software",
                                      "hotel", "restaurant")
                    if any(kw in haystack for kw in high_process_kw):
                        risk = "High"
                    elif any(kw in haystack for kw in low_service_kw):
                        risk = "Low"

            result[iso] = {"type": "ea", "codes": codes, "risk": risk}

    logger.info("[AuditSet] derive_required_scope → %s", result)
    return result


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _next_plan_number(db: Session) -> int:
    """Return COALESCE(MAX(plan_number), 1599) + 1 — first call yields 1600."""
    result = db.query(func.coalesce(func.max(AuditSet.plan_number), 1599)).scalar()
    return int(result) + 1


def _run_calculation(audit_set: AuditSet) -> dict | None:
    """
    Bridge: map AuditSet fields → ExtractedFormData → calculate() → dict.
    Returns the full CalculationResult as a plain dict, or None on failure.
    """
    try:
        from calculator.engine import calculate
        from calculator.models import ExtractedFormData, SiteInfo, StandardClassification

        standards = [_CODE_TO_ISO.get(s, s) for s in (audit_set.standards or [])]
        if not standards:
            return None

        # ── Personnel — IAF MD5 EPS bridge ──────────────────────────────────────
        p = audit_set.personnel or {}
        full_time      = int(p.get("full_time", 0))
        part_time      = int(p.get("part_time", 0))
        subcontractors = int(p.get("subcontractors", 0))
        seasonal       = int(p.get("seasonal", 0))
        unskilled      = int(p.get("unskilled", 0))

        # Read FTE conversion factors from application_data (defaults are IAF MD5-aligned)
        app_data = audit_set.application_data or {}
        pt_factor               = float(app_data.get("part_time_fte_factor", 0.5))
        subcontractors_in_scope = bool(app_data.get("subcontractors_in_scope", True))

        # Convert part-time to FTE equivalent; subcontractors only counted when in scope
        pt_fte             = int(math.ceil(part_time * pt_factor))
        sub_count          = subcontractors if subcontractors_in_scope else 0
        total_employees    = full_time + pt_fte + sub_count + seasonal + unskilled

        repetitive_roles     = p.get("repetitive_roles", [])
        repetitive_employees = sum(r.get("employee_count", 0) for r in repetitive_roles)
        office_employees     = max(0, total_employees - repetitive_employees)

        # ── Integration level (count YES booleans) ────────────────────────
        il = audit_set.integration_level or {}
        integration_yes_count = sum(1 for v in il.values() if v)

        # ── Sites → SiteInfo list (for the engine's multi-site logic) ─────
        sites_raw = audit_set.sites or []
        sites = [
            SiteInfo(
                name=s.get("name", ""),
                address=s.get("address", ""),
                process_description=s.get("process", ""),
                employee_count=s.get("employee_count", 0),
            )
            for s in sites_raw
            # Note: allow sites with 0 employees through — CB can see them;
            # the engine's own _lookup_for_eps call only adds time when > 0.
        ]

        # ── EnMS energy data (ISO 50001) ─────────────────────────────────────────
        # Priority 1: explicit form data in application_data (most accurate)
        # Priority 2: legacy sites[0].energy_tj (backward compat for existing audit sets)
        annual_energy_tj = num_energy_types = num_seus = None
        if app_data.get("enms_annual_energy_tj") is not None:
            annual_energy_tj = float(app_data["enms_annual_energy_tj"])
            num_energy_types = app_data.get("enms_num_energy_types")
            num_seus         = app_data.get("enms_num_seus")
        else:
            for s in sites_raw:
                if s.get("energy_tj") is not None:
                    annual_energy_tj  = float(s["energy_tj"])
                    num_energy_types  = s.get("energy_types")
                    num_seus          = s.get("seu_count")
                    break

        # ── Default sector classifications (Medium) ───────────────────────
        classifications = [
            StandardClassification(
                standard=iso_name,
                sector_name="Unknown",
                category="Medium",
            )
            for iso_name in standards
        ]

        # ── Food chain categories (ISO 22000 / FSSC 22000) ───────────────────────
        # Priority 1: explicit categories from application form (most precise)
        # Priority 2: keyword-derived categories from required_scope (for legacy sets)
        food_cats: list[str] = []
        if app_data.get("fsms_food_chain_categories"):
            food_cats = list(app_data["fsms_food_chain_categories"])
        else:
            rs = getattr(audit_set, "required_scope", None) or {}
            for _iso_name, entry in rs.items():
                if not isinstance(entry, dict):
                    continue
                if entry.get("type") == "food":
                    food_cats.extend(entry.get("codes", []) or [])

        form_data = ExtractedFormData(
            org_name=audit_set.company_name or "",
            standards=standards,
            audit_type=audit_set.audit_type or "Initial",
            scope=audit_set.scope_en or audit_set.scope_tr or "",
            total_employees=total_employees,
            office_employees=office_employees,
            repetitive_employees=repetitive_employees,
            subcontractors=subcontractors,
            seasonal_employees=seasonal,
            sites=sites,
            integration_yes_count=integration_yes_count,
            classifications=classifications,
            annual_energy_tj=annual_energy_tj,
            num_energy_types=num_energy_types,
            num_seus=num_seus,
            scope_integration_level=getattr(audit_set, "scope_integration_level", None),
            food_chain_categories=food_cats,
            haccp_studies=int(app_data.get("fsms_haccp_studies") or 0) or None,
            fsms_offsite_storage_count=int(app_data.get("fsms_offsite_storage_count", 0)),
            fsms_separate_head_office=bool(app_data.get("fsms_separate_head_office", False)),
            fsms_fssc22000=bool(app_data.get("fsms_fssc22000", False)),
        )

        result = calculate(form_data)
        return result.model_dump()

    except Exception as exc:
        logger.warning("[AuditSet] Calculation failed for id=%s: %s", getattr(audit_set, "id", "?"), exc)
        return None


def _writeback_personnel_split(audit_set: AuditSet) -> None:
    """Merge derived office_employees + repetitive_employees back into the
    personnel JSON so downstream document generation can read them directly.
    Uses the same FTE derivation as _run_calculation (pt_factor, subcontractors_in_scope)."""
    p = dict(audit_set.personnel or {})
    app_data = audit_set.application_data or {}

    full_time      = int(p.get("full_time", 0))
    part_time      = int(p.get("part_time", 0))
    subcontractors = int(p.get("subcontractors", 0))
    seasonal       = int(p.get("seasonal", 0))
    unskilled      = int(p.get("unskilled", 0))

    pt_factor               = float(app_data.get("part_time_fte_factor", 0.5))
    subcontractors_in_scope = bool(app_data.get("subcontractors_in_scope", True))

    pt_fte    = int(math.ceil(part_time * pt_factor))
    sub_count = subcontractors if subcontractors_in_scope else 0

    total_employees      = full_time + pt_fte + sub_count + seasonal + unskilled
    repetitive_roles     = p.get("repetitive_roles", [])
    repetitive_employees = sum(r.get("employee_count", 0) for r in repetitive_roles)
    office_employees     = max(0, total_employees - repetitive_employees)

    p["office_employees"]     = office_employees
    p["repetitive_employees"] = repetitive_employees
    audit_set.personnel = p
    flag_modified(audit_set, "personnel")


def _create_auto_stages(db: Session, audit_set: AuditSet, result: dict | None) -> None:
    """Insert auto-generated AuditSetStage rows based on audit_type."""
    audit_type = (audit_set.audit_type or "initial").lower()

    if audit_type == "initial":
        stage_defs = [
            ("stage_1", 1, result.get("final_ph1") if result else None),
            ("stage_2", 2, result.get("final_ph2") if result else None),
        ]
    elif audit_type.startswith("surveillance"):  # surveillance_1, surveillance_2, surveillance
        stage_defs = [
            ("surveillance", 1, result.get("final_surv1") if result else None),
        ]
    elif audit_type == "recertification":
        stage_defs = [
            ("recertification", 1, result.get("final_recert") if result else None),
        ]
    elif audit_type == "special":  # single special-purpose visit
        stage_defs = [
            ("stage_1", 1, result.get("final_total") if result else None),
        ]
    else:
        logger.warning(
            "[AuditSet] Unknown audit_type=%r for id=%s — defaulting to stage_1 + stage_2",
            audit_type, getattr(audit_set, "id", "?"),
        )
        stage_defs = [
            ("stage_1", 1, result.get("final_ph1") if result else None),
            ("stage_2", 2, result.get("final_ph2") if result else None),
        ]

    for stage_type, order, audit_days in stage_defs:
        db.add(AuditSetStage(
            id=str(uuid.uuid4()),
            audit_set_id=audit_set.id,
            stage_type=stage_type,
            stage_order=order,
            audit_days=audit_days,
        ))


# ---------------------------------------------------------------------------
# Public CRUD functions
# ---------------------------------------------------------------------------

def create_audit_set(db: Session, data: AuditSetCreateSchema) -> AuditSet:
    """Create a new AuditSet, run the calculator, auto-create stages. Returns persisted row."""
    # Default the spoken audit language from the company's country if not supplied.
    if not data.audit_language:
        data.audit_language = COUNTRY_LANGUAGE.get(data.country, "English")

    audit_set = AuditSet(
        id=str(uuid.uuid4()),
        plan_number=_next_plan_number(db),
        client_reference=(data.client_reference or None),
        status="draft",
        company_name=data.company_name,
        company_address=data.company_address,
        country=data.country,
        city=data.city,
        phone=data.phone,
        email=data.email,
        website=data.website,
        representative=data.representative,
        standards=data.standards,
        audit_type=data.audit_type,
        is_transfer=data.is_transfer,
        cycle_number=data.cycle_number,
        accreditation_body=data.accreditation_body,
        scope_tr=data.scope_tr,
        scope_en=data.scope_en,
        non_applicable_clauses=data.non_applicable_clauses,
        personnel=data.personnel.model_dump(),
        sites=[s.model_dump() for s in data.sites],
        integration_level=data.integration_level.model_dump(),
        certification_fee=data.certification_fee,
        surveillance_fee=data.surveillance_fee,
        currency=data.currency or "USD",
        ea_code=data.ea_code,
        ea_category=data.ea_category,
        ea_technical_area=data.ea_technical_area,
        audit_language=data.audit_language,
        document_language=data.document_language or "turkish",
        application_data=data.application_data.model_dump() if data.application_data else None,
    )
    db.add(audit_set)
    db.flush()  # populate audit_set.id before child rows

    # 2A — Derive scope_integration_level from boolean fields BEFORE calculation
    # so the engine applies the correct IAF MD 11 rate on creation.
    il = audit_set.integration_level or {}
    yes_count = sum(1 for v in il.values() if v is True)
    if yes_count <= 1:
        audit_set.scope_integration_level = "Low"
    elif yes_count <= 3:
        audit_set.scope_integration_level = "Medium"
    else:
        audit_set.scope_integration_level = "High"

    # 2B — Derive required_scope BEFORE calculation so food chain categories
    # (and any other scope-driven inputs) reach the engine on the first pass.
    audit_set.required_scope = derive_required_scope(
        standards=audit_set.standards or [],
        scope_tr=audit_set.scope_tr,
        scope_en=audit_set.scope_en,
        ea_code=audit_set.ea_code,
        application_data=audit_set.application_data,
    )

    result = _run_calculation(audit_set)
    if result:
        audit_set.man_day_result = result
        audit_set.effective_employees = int(round(result.get("eps", 0)))
        audit_set.risk_category = (
            result["standard_results"][0].get("category", "").upper()
            if result.get("standard_results") else None
        )
        _writeback_personnel_split(audit_set)

    # Auto-populate top-level ea_code from the derived scope so EA/IAF Code
    # never renders "None" in FR.223/FR.224 even when the user skipped the
    # explicit "derive scope" step.
    _auto_populate_ea_fields(audit_set)

    _create_auto_stages(db, audit_set, result)
    db.commit()
    db.refresh(audit_set)
    logger.info("[AuditSet] Created id=%s plan_number=%s", audit_set.id, audit_set.plan_number)
    return audit_set


def get_audit_set(db: Session, audit_set_id: str) -> AuditSet | None:
    """Return AuditSet by ID (including archived), or None."""
    return db.query(AuditSet).filter(AuditSet.id == audit_set_id).first()


def quick_calculate(db: Session, audit_set_id: str, data: QuickCalcSchema) -> AuditSet | None:
    """
    Re-run the IAF MD 5 calculator for an audit set with updated personnel /
    integration data. Persists new man_day_result and updates existing stage
    audit_days. Returns the refreshed AuditSet, or None if not found.
    """
    audit_set = get_audit_set(db, audit_set_id)
    if not audit_set:
        return None

    # Patch the audit set with submitted data (in-memory only, not persisted directly)
    submitted_personnel = data.personnel.model_dump()
    total_submitted = sum(
        submitted_personnel.get(k, 0)
        for k in ("full_time", "part_time", "subcontractors", "seasonal", "unskilled")
    )
    if total_submitted > 0:
        # Only overwrite stored personnel when the caller explicitly supplies counts
        audit_set.personnel = submitted_personnel
        audit_set.integration_level = data.integration_level.model_dump()
    # else: use the existing stored personnel (integration level change, scope level change, etc.)

    if data.ea_code is not None:
        audit_set.ea_code = data.ea_code
    if data.ea_category is not None:
        audit_set.ea_category = data.ea_category
    if data.scope_integration_level is not None:
        audit_set.scope_integration_level = data.scope_integration_level

    # Ensure required_scope is populated before calculation so food chain
    # categories (ISO 22000 / FSSC) flow into the engine on legacy records.
    if not audit_set.required_scope:
        audit_set.required_scope = derive_required_scope(
            standards=audit_set.standards or [],
            scope_tr=audit_set.scope_tr,
            scope_en=audit_set.scope_en,
            ea_code=audit_set.ea_code,
            application_data=audit_set.application_data,
        )

    result = _run_calculation(audit_set)
    if not result:
        logger.warning("[AuditSet] quick_calculate: engine returned None for id=%s", audit_set_id)
        return audit_set  # return as-is without crashing

    audit_set.man_day_result = result
    audit_set.effective_employees = int(round(result.get("eps", 0)))
    audit_set.risk_category = (
        result["standard_results"][0].get("category", "").upper()
        if result.get("standard_results") else None
    )
    _writeback_personnel_split(audit_set)

    # Update stage audit_days to match new recommended days
    audit_type = (audit_set.audit_type or "initial").lower()
    stage_day_map: dict[str, float | None] = {}
    if audit_type == "initial":
        stage_day_map = {"stage_1": result.get("final_ph1"), "stage_2": result.get("final_ph2")}
    elif audit_type.startswith("surveillance"):  # surveillance_1, surveillance_2, surveillance
        stage_day_map = {"surveillance": result.get("final_surv1")}
    elif audit_type == "recertification":
        stage_day_map = {"recertification": result.get("final_recert")}
    elif audit_type == "special":
        stage_day_map = {"stage_1": result.get("final_total")}
    else:
        stage_day_map = {"stage_1": result.get("final_ph1"), "stage_2": result.get("final_ph2")}

    for stage in audit_set.stages:
        new_days = stage_day_map.get(stage.stage_type)
        if new_days is not None:
            stage.audit_days = new_days

    db.commit()
    db.refresh(audit_set)
    logger.info("[AuditSet] quick_calculate done for id=%s final_total=%s", audit_set_id, result.get("final_total"))
    return audit_set


def list_audit_sets(db: Session, status: str | None = None) -> list[AuditSet]:
    """Return all audit sets, newest first. Optionally filter by status."""
    q = db.query(AuditSet)
    if status:
        q = q.filter(AuditSet.status == status)
    return q.order_by(AuditSet.created_at.desc()).all()


def update_planning(
    db: Session,
    audit_set_id: str,
    data: AuditSetUpdatePlanningSchema,
) -> AuditSet | None:
    """
    Update EA classification, fees, and stage assignments.
    Creates a stage row if no matching stage_type + stage_order exists.
    Advances status from "draft" to "planning" on first call.
    Returns None if audit_set_id is not found.
    """
    audit_set = get_audit_set(db, audit_set_id)
    if not audit_set:
        return None

    # ── Stage ordering: Stage 1 end MUST be strictly before Stage 2 start ──
    s1 = next((s for s in data.stages if s.stage_type == "stage_1"), None)
    s2 = next((s for s in data.stages if s.stage_type == "stage_2"), None)
    if s1 and s2 and s1.audit_date_end and s2.audit_date_start:
        if s1.audit_date_end >= s2.audit_date_start:
            from fastapi import HTTPException
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Stage 1 end date ({s1.audit_date_end}) must be strictly before "
                    f"Stage 2 start date ({s2.audit_date_start})."
                ),
            )

    # Update top-level fields only when provided, so partial saves (e.g. a
    # stage-only or fees-only PUT) don't wipe previously-set values.
    if data.ea_code is not None:
        audit_set.ea_code = data.ea_code
    if data.ea_category is not None:
        audit_set.ea_category = data.ea_category
    if data.ea_technical_area is not None:
        audit_set.ea_technical_area = data.ea_technical_area
    if data.certification_fee is not None:
        audit_set.certification_fee = data.certification_fee
    if data.surveillance_fee is not None:
        audit_set.surveillance_fee = data.surveillance_fee
    if data.currency is not None:
        if data.currency not in ("USD", "EUR", "TRY"):
            from fastapi import HTTPException as _HTTPException
            raise _HTTPException(400, "currency must be one of: USD, EUR, TRY")
        audit_set.currency = data.currency
    # Persist optional company fields only when provided (don't wipe on stage-only saves)
    if data.representative is not None:
        audit_set.representative = data.representative
    if data.non_applicable_clauses is not None:
        audit_set.non_applicable_clauses = data.non_applicable_clauses
    if data.client_reference is not None:
        audit_set.client_reference = data.client_reference or None
    # Persist derived scope only when the caller provides it (don't wipe on stage-only saves)
    if data.required_scope is not None:
        audit_set.required_scope = data.required_scope
    if data.scope_integration_level is not None:
        audit_set.scope_integration_level = data.scope_integration_level
    if data.audit_language is not None:
        audit_set.audit_language = data.audit_language
    if data.document_language is not None:
        audit_set.document_language = data.document_language
    if data.application_date is not None:
        audit_set.application_date = data.application_date
    if data.application_data is not None:
        audit_set.application_data = data.application_data.model_dump()
        flag_modified(audit_set, "application_data")
    if data.transfer_reviewer_id is not None or data.transfer_reviewer_name is not None:
        _validate_transfer_reviewer_choice(audit_set, data.transfer_reviewer_id)
        audit_set.transfer_reviewer_id = data.transfer_reviewer_id or None
        audit_set.transfer_reviewer_name = data.transfer_reviewer_name or None

    # Upsert stages
    for stage_input in data.stages:
        existing = next(
            (s for s in audit_set.stages
             if s.stage_type == stage_input.stage_type
             and s.stage_order == stage_input.stage_order),
            None,
        )
        payload = dict(
            notification_date=stage_input.notification_date,
            audit_date_start=stage_input.audit_date_start,
            audit_date_end=stage_input.audit_date_end,
            lead_auditor_id=stage_input.lead_auditor_id,
            lead_auditor_name=stage_input.lead_auditor_name,
            auditors=[a.model_dump() for a in stage_input.auditors],
            technical_experts=[a.model_dump() for a in stage_input.technical_experts],
            observers=[a.model_dump() for a in stage_input.observers],
            trainees= [a.model_dump() for a in stage_input.trainees],
            ik_experts=[a.model_dump() for a in stage_input.ik_experts],
            evaluators=[a.model_dump() for a in stage_input.evaluators],
            audit_days=stage_input.audit_days,
            status=stage_input.status,
        )
        if existing:
            for k, v in payload.items():
                setattr(existing, k, v)
        else:
            db.add(AuditSetStage(
                id=str(uuid.uuid4()),
                audit_set_id=audit_set.id,
                stage_type=stage_input.stage_type,
                stage_order=stage_input.stage_order,
                **payload,
            ))

    # Portal 64 — persist committee_members snapshot when provided.
    # Validation (no-overlap, coverage) is done upstream in the router.
    # flag_modified is required for JSON columns so SQLAlchemy detects the
    # change even when replacing the entire value (not just mutating in-place).
    if data.committee_members is not None:
        audit_set.committee_members = data.committee_members
        flag_modified(audit_set, "committee_members")
        _validate_transfer_reviewer_choice(audit_set, audit_set.transfer_reviewer_id)

    _validate_transfer_reviewer_choice(audit_set, audit_set.transfer_reviewer_id)

    # Auto-populate ea_code (and required_scope on legacy records) so
    # documents stop showing "None" for EA/IAF Code. The user's manual
    # ea_code from the payload wins because that branch runs above.
    _auto_populate_ea_fields(audit_set)

    if audit_set.status == "draft":
        audit_set.status = "planning"

    db.commit()
    db.refresh(audit_set)
    logger.info("[AuditSet] Planning updated id=%s", audit_set.id)
    return audit_set


def derive_and_save_scope(
    db: Session,
    audit_set_id: str,
) -> AuditSet | None:
    """
    Run keyword-based scope derivation against the stored scope text and
    save the result to audit_set.required_scope.  Returns None if not found.
    """
    audit_set = get_audit_set(db, audit_set_id)
    if not audit_set:
        return None

    scoped = derive_required_scope(
        standards=audit_set.standards or [],
        scope_tr=audit_set.scope_tr,
        scope_en=audit_set.scope_en,
        ea_code=audit_set.ea_code,
        application_data=audit_set.application_data,
    )
    audit_set.required_scope = scoped
    db.commit()
    db.refresh(audit_set)
    logger.info("[AuditSet] Scope derived and saved id=%s → %s", audit_set.id, scoped)
    return audit_set


# ---------------------------------------------------------------------------
# Certificate management
# ---------------------------------------------------------------------------

def _add_certificate_years(issued: date, years: int = 3) -> date:
    """Return the certificate expiry date, handling leap-day issue dates."""
    try:
        return issued.replace(year=issued.year + years)
    except ValueError:
        return issued.replace(year=issued.year + years, day=28)


def _derive_certificate_issue_date(
    db: Session,
    audit_set: AuditSet,
    fallback_date: date | None = None,
) -> date:
    """Best available issue date for rows that are already certified."""
    certificate_doc = (
        db.query(AuditSetSharedDocument)
        .filter_by(audit_set_id=audit_set.id, document_type="certificate")
        .order_by(
            AuditSetSharedDocument.released_at.desc().nullslast(),
            AuditSetSharedDocument.created_at.desc(),
        )
        .first()
    )
    if certificate_doc:
        issued_at = certificate_doc.released_at or certificate_doc.created_at
        if issued_at:
            return issued_at.date()

    certified_event = (
        db.query(AuditSetStatusEvent)
        .filter_by(audit_set_id=audit_set.id, to_status="certified")
        .order_by(AuditSetStatusEvent.triggered_at.desc())
        .first()
    )
    if certified_event and certified_event.triggered_at:
        return certified_event.triggered_at.date()

    return fallback_date or date.today()


def ensure_cert_dates_for_certified(
    db: Session,
    audit_sets: list[AuditSet] | None = None,
    fallback_date: date | None = None,
) -> bool:
    """
    Certified/continued clients must have certificate dates so planner, CRM,
    and dashboard lists can show them as valid certificates.
    """
    targets = audit_sets
    if targets is None:
        targets = (
            db.query(AuditSet)
            .filter(AuditSet.status != "archived")
            .filter(AuditSet.workflow_status == "certified")
            .filter(
                or_(
                    AuditSet.cert_issued_date.is_(None),
                    AuditSet.cert_expiry_date.is_(None),
                    AuditSet.cert_status.is_(None),
                )
            )
            .all()
        )

    changed = False
    for audit_set in targets:
        if audit_set.workflow_status != "certified":
            continue
        if audit_set.cert_issued_date and audit_set.cert_expiry_date and audit_set.cert_status:
            continue

        issued = audit_set.cert_issued_date or _derive_certificate_issue_date(
            db, audit_set, fallback_date=fallback_date,
        )
        audit_set.cert_issued_date = issued
        if audit_set.cert_expiry_date is None:
            audit_set.cert_expiry_date = _add_certificate_years(issued)
        audit_set.cert_status = audit_set.compute_cert_status()
        changed = True

    return changed

def update_cert_dates(
    db: Session,
    audit_set_id: str,
    data: AuditSetCertUpdateSchema,
) -> AuditSet | None:
    """
    Update certificate issued/expiry dates and recompute cert_status.
    If cert_expiry_date is omitted but cert_issued_date is provided,
    auto-sets expiry to exactly 3 calendar years after issue.
    """
    audit_set = get_audit_set(db, audit_set_id)
    if not audit_set:
        return None

    if data.cert_issued_date is not None:
        audit_set.cert_issued_date = data.cert_issued_date

    if data.cert_expiry_date is not None:
        audit_set.cert_expiry_date = data.cert_expiry_date
    elif data.cert_issued_date is not None and audit_set.cert_expiry_date is None:
        # Auto-set to 3 calendar years from issue date
        audit_set.cert_expiry_date = _add_certificate_years(data.cert_issued_date)

    audit_set.cert_status = audit_set.compute_cert_status()
    db.commit()
    db.refresh(audit_set)
    logger.info("[AuditSet] Cert dates updated id=%s status=%s", audit_set.id, audit_set.cert_status)
    return audit_set


# ---------------------------------------------------------------------------
# Dashboard helpers
# ---------------------------------------------------------------------------

def _count_file_jobs(filename: str) -> int:
    """Count job directories containing `filename` whose state is not terminal."""
    from config.settings import get_settings
    base = Path(get_settings().storage_base_path)
    if not base.exists():
        return 0
    count = 0
    for job_dir in base.iterdir():
        if not job_dir.is_dir():
            continue
        status_file = job_dir / filename
        if not status_file.exists():
            continue
        try:
            data = json.loads(status_file.read_text(encoding="utf-8"))
            if data.get("state") not in ("COMPLETE", "FAILED"):
                count += 1
        except Exception:
            pass
    return count


def get_dashboard_stats(db: Session) -> dict:
    """Return aggregate counts for the dashboard stats cards."""
    if ensure_cert_dates_for_certified(db):
        db.commit()

    total_plans = (
        db.query(func.count(AuditSet.id))
        .filter(AuditSet.status != "archived")
        .scalar() or 0
    )
    active_certs = (
        db.query(func.count(AuditSet.id))
        .filter(AuditSet.cert_status == "active")
        .scalar() or 0
    )
    approaching = (
        db.query(func.count(AuditSet.id))
        .filter(AuditSet.cert_status == "approaching_expiry")
        .scalar() or 0
    )
    expired = (
        db.query(func.count(AuditSet.id))
        .filter(AuditSet.cert_status == "expired")
        .scalar() or 0
    )
    open_jobs       = _count_file_jobs("status.json")
    pending_reviews = _count_file_jobs("review_status.json")

    return {
        "total_plans":          total_plans,
        "active_certificates":  active_certs,
        "approaching_expiry":   approaching,
        "expired":              expired,
        "open_jobs":            open_jobs,
        "pending_reviews":      pending_reviews,
    }


def list_clients(
    db: Session,
    search: str | None = None,
    standard: str | None = None,
    cert_status: str | None = None,
    audit_type: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[AuditSet]:
    """
    Return audit sets with stages eagerly loaded, ordered newest-first.
    Excludes archived records. Applies AND filters for every non-None param.
    """
    if ensure_cert_dates_for_certified(db):
        db.commit()

    q = (
        db.query(AuditSet)
        .options(selectinload(AuditSet.stages))
        .filter(AuditSet.status != "archived")
    )
    if search:
        q = q.filter(or_(
            AuditSet.company_name.ilike(f"%{search}%"),
            AuditSet.client_reference.ilike(f"%{search}%"),
        ))
    if standard:
        # standards is stored as JSON text in SQLite; match the quoted value
        q = q.filter(cast(AuditSet.standards, String).like(f'%"{standard}"%'))
    if cert_status:
        q = q.filter(AuditSet.cert_status == cert_status)
    if audit_type:
        q = q.filter(AuditSet.audit_type == audit_type)
    return q.order_by(AuditSet.created_at.desc()).limit(limit).offset(offset).all()
