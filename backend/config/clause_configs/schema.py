"""
BATUHAN — Clause Config Schema
Pydantic models for per-standard clause applicability configuration.
"""

from enum import Enum
from typing import Optional
from pydantic import BaseModel


class Applicability(str, Enum):
    ALWAYS = "always_applicable"
    SCOPE_CONDITIONAL = "scope_conditional"
    OPTIONAL = "optional"
    NEVER = "never_applicable"


class ClauseConfig(BaseModel):
    clause_id: str          # e.g. "8.3", "A.5.1"
    title: str
    applicability: Applicability
    condition: Optional[str] = None   # only when scope_conditional; plain English rule
    notes: Optional[str] = None


class StandardClauseConfig(BaseModel):
    standard_code: str      # e.g. "QMS", "ISMS"
    standard_name: str      # e.g. "ISO 9001:2015"
    clauses: list[ClauseConfig]
