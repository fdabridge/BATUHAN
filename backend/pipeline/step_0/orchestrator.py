"""
BATUHAN — Step 0 Orchestrator: Scope Analysis
For each selected standard, extracts the scope statement from the document
corpus and asks Claude which scope-conditional clauses apply.
Always-applicable clauses are included automatically without a Claude call.
"""

from __future__ import annotations
import json
import logging

import anthropic

from schemas.models import ScopeAnalysisResult, StandardScopeResult, ClauseApplicabilityDecision
from config.clause_configs.schema import StandardClauseConfig, Applicability

logger = logging.getLogger(__name__)


def run_step_0(
    document_corpus: str,
    clause_configs: dict[str, StandardClauseConfig],
    client: anthropic.Anthropic,
    model: str,
    max_tokens: int,
    temperature: float,
) -> ScopeAnalysisResult:
    """
    For each selected standard, extracts the scope statement from the corpus
    and asks Claude which scope_conditional clauses apply.
    Always-applicable clauses are included automatically without asking Claude.
    """
    scope_statement = _extract_scope_statement(document_corpus)
    standards_results: dict[str, StandardScopeResult] = {}

    for standard_code, config in clause_configs.items():
        always_ids = [
            c.clause_id for c in config.clauses
            if c.applicability == Applicability.ALWAYS
        ]
        conditional_clauses = [
            c for c in config.clauses
            if c.applicability == Applicability.SCOPE_CONDITIONAL
        ]
        never_ids = [
            c.clause_id for c in config.clauses
            if c.applicability == Applicability.NEVER
        ]

        # If no conditional clauses, no Claude call needed
        if not conditional_clauses:
            standards_results[standard_code] = StandardScopeResult(
                standard_code=standard_code,
                scope_statement=scope_statement,
                applicable_clause_ids=always_ids,
                excluded_clause_ids=never_ids,
                decisions=[],
            )
            continue

        # Build Claude prompt
        clauses_text = "\n".join([
            f"- {c.clause_id} | {c.title} | CONDITION: {c.condition}"
            for c in conditional_clauses
        ])

        prompt = f"""You are an ISO audit expert. Based on the company scope statement below, \
determine which clauses are applicable.

STANDARD: {config.standard_name}

COMPANY SCOPE STATEMENT:
{scope_statement}

CLAUSES TO EVALUATE (these are scope-conditional — evaluate each one):
{clauses_text}

For each clause, respond in this exact JSON format only. No prose, no explanation outside the JSON:

{{
  "decisions": [
    {{
      "clause_id": "X.X",
      "decision": "applicable",
      "reason": "one sentence reason"
    }},
    {{
      "clause_id": "X.X",
      "decision": "not_applicable",
      "reason": "one sentence reason"
    }}
  ]
}}"""

        try:
            response = client.messages.create(
                model=model,
                max_tokens=max_tokens,
                temperature=temperature,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = response.content[0].text.strip()
            parsed = json.loads(raw)
            decisions_raw = parsed.get("decisions", [])
        except Exception as e:
            logger.warning(
                f"Step 0 Claude call failed for {standard_code}: {e}. "
                "Defaulting all conditional clauses to applicable."
            )
            decisions_raw = [
                {
                    "clause_id": c.clause_id,
                    "decision": "applicable",
                    "reason": "Default — scope analysis failed",
                }
                for c in conditional_clauses
            ]

        decisions: list[ClauseApplicabilityDecision] = []
        applicable_conditional_ids: list[str] = []
        excluded_ids: list[str] = list(never_ids)

        clause_map = {c.clause_id: c for c in conditional_clauses}

        for d in decisions_raw:
            cid = d.get("clause_id", "")
            decision = d.get("decision", "applicable")
            reason = d.get("reason", "")
            clause = clause_map.get(cid)
            title = clause.title if clause else ""

            decisions.append(ClauseApplicabilityDecision(
                clause_id=cid,
                title=title,
                decision=decision,
                reason=reason,
            ))

            if decision == "not_applicable":
                excluded_ids.append(cid)
            else:
                applicable_conditional_ids.append(cid)

        # Any conditional clause not returned by Claude defaults to applicable
        returned_ids = {d.clause_id for d in decisions}
        for c in conditional_clauses:
            if c.clause_id not in returned_ids:
                applicable_conditional_ids.append(c.clause_id)
                logger.warning(
                    f"Step 0: {standard_code} clause {c.clause_id} "
                    "not returned by Claude — defaulting to applicable"
                )

        standards_results[standard_code] = StandardScopeResult(
            standard_code=standard_code,
            scope_statement=scope_statement,
            applicable_clause_ids=always_ids + applicable_conditional_ids,
            excluded_clause_ids=excluded_ids,
            decisions=decisions,
        )

        logger.info(
            f"Step 0 [{standard_code}]: "
            f"{len(always_ids + applicable_conditional_ids)} applicable, "
            f"{len(excluded_ids)} excluded"
        )

    return ScopeAnalysisResult(standards=standards_results)


def _extract_scope_statement(corpus: str) -> str:
    """
    Tries to find the scope statement in the document corpus.
    Looks for keywords: 'scope', 'kapsam', 'field of application'.
    Returns the surrounding context (up to 1500 chars) or first 1500 chars as fallback.
    """
    keywords = ["scope of certification", "scope of the", "kapsam", "field of application", "4.3"]
    lower = corpus.lower()
    for kw in keywords:
        idx = lower.find(kw)
        if idx != -1:
            start = max(0, idx - 100)
            end = min(len(corpus), idx + 1400)
            return corpus[start:end].strip()
    # Fallback: first 1500 chars
    return corpus[:1500].strip()
