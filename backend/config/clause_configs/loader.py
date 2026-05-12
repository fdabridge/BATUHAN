"""
BATUHAN — Clause Config Loader
Reads per-standard clause applicability JSON files and exposes helper
functions used by the pipeline to determine which clauses are in scope.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from config.clause_configs.schema import (
    Applicability,
    ClauseConfig,
    StandardClauseConfig,
)

logger = logging.getLogger(__name__)

# All supported standard codes — must match ISOStandard enum values in schemas/models.py
_ALL_STANDARD_CODES: list[str] = [
    "QMS",
    "EMS",
    "OHSMS",
    "FSMS",
    "MDQMS",
    "ISMS",
    "ABMS",
    "ENMS",
]

_CONFIG_DIR = Path(__file__).parent


def load_clause_config(standard_code: str) -> StandardClauseConfig:
    """
    Load the clause applicability config for a single standard.

    Reads backend/config/clause_configs/{standard_code.lower()}.json and
    parses it into a StandardClauseConfig instance.

    Args:
        standard_code: One of the 8 supported codes (e.g. "QMS", "ISMS").

    Returns:
        Parsed StandardClauseConfig.

    Raises:
        FileNotFoundError: If the JSON file does not exist yet.
        ValueError: If the JSON is malformed or fails Pydantic validation.
    """
    json_path = _CONFIG_DIR / f"{standard_code.lower()}.json"
    if not json_path.exists():
        raise FileNotFoundError(
            f"Clause config not found for standard '{standard_code}': {json_path}\n"
            "Create the JSON file before calling load_clause_config()."
        )
    try:
        raw = json_path.read_text(encoding="utf-8")
        data = json.loads(raw)
        config = StandardClauseConfig.model_validate(data)
        logger.debug(
            "[ClauseConfig] Loaded %d clauses for %s from %s",
            len(config.clauses), standard_code, json_path.name,
        )
        return config
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"Invalid JSON in clause config for '{standard_code}': {exc}"
        ) from exc
    except Exception as exc:
        raise ValueError(
            f"Failed to parse clause config for '{standard_code}': {exc}"
        ) from exc


def get_applicable_clauses(
    config: StandardClauseConfig,
    scope_text: str,
) -> list[ClauseConfig]:
    """
    Return all clauses that are applicable for a given audit scope.

    Rules (Step 0 will refine SCOPE_CONDITIONAL and OPTIONAL further):
      - ALWAYS            → included unconditionally
      - SCOPE_CONDITIONAL → included (Step 0 will evaluate condition against scope_text)
      - OPTIONAL          → included (Step 0 will decide based on scope_text)
      - NEVER             → excluded unconditionally

    Args:
        config:     The StandardClauseConfig for the chosen standard.
        scope_text: Free-text description of the auditee's scope of activities.

    Returns:
        List of ClauseConfig objects with applicability != NEVER.
    """
    applicable = [
        clause for clause in config.clauses
        if clause.applicability is not Applicability.NEVER
    ]
    logger.debug(
        "[ClauseConfig] %s: %d/%d clauses applicable (NEVER excluded: %d)",
        config.standard_code,
        len(applicable),
        len(config.clauses),
        len(config.clauses) - len(applicable),
    )
    return applicable


def get_mandatory_clause_ids(config: StandardClauseConfig) -> list[str]:
    """Returns clause_ids where applicability is ALWAYS or SCOPE_CONDITIONAL.
    These are the clauses the pipeline must cover. NEVER and OPTIONAL are excluded."""
    return [
        c.clause_id for c in config.clauses
        if c.applicability in (Applicability.ALWAYS, Applicability.SCOPE_CONDITIONAL)
    ]


def load_all_configs() -> dict[str, StandardClauseConfig]:
    """
    Attempt to load clause configs for all 8 supported standards.

    Standards whose JSON file does not yet exist are skipped with a warning
    rather than raising — this allows partial rollout as JSON files are added.

    Returns:
        Dict keyed by standard_code (e.g. {"QMS": StandardClauseConfig, ...}).
        Only standards with an existing JSON file are included.
    """
    configs: dict[str, StandardClauseConfig] = {}
    for code in _ALL_STANDARD_CODES:
        try:
            configs[code] = load_clause_config(code)
        except FileNotFoundError:
            logger.warning(
                "[ClauseConfig] No JSON file found for '%s' — skipping. "
                "Create backend/config/clause_configs/%s.json to enable.",
                code, code.lower(),
            )
        except ValueError as exc:
            logger.error(
                "[ClauseConfig] Failed to load config for '%s': %s", code, exc
            )
    logger.info(
        "[ClauseConfig] load_all_configs: loaded %d/%d standard configs.",
        len(configs), len(_ALL_STANDARD_CODES),
    )
    return configs
