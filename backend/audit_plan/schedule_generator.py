"""
BATUHAN — Audit Plan: Schedule Generator
Calls Claude to produce a structured hourly schedule JSON from the template
context and the hardcoded CLAUSE_MAP.
"""

from __future__ import annotations
import json
import logging
import re
from dataclasses import dataclass, field

import anthropic

from config.settings import get_settings
from .clause_map import CLAUSE_MAP
from .template_reader import AuditPlanContext

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Output data structures
# ---------------------------------------------------------------------------

@dataclass
class Slot:
    time: str          # "0800 – 0900"  |  "Break (1200 – 1230)"
    is_break: bool
    standard: str      # "ISO 9001:2015" or "" for meetings/breaks
    clauses: str       # "4.1-4.2-4.3"  or ""
    activity: str      # "Opening Meeting" / process description
    auditors: str      # "Fadhil (LA), Zina (A)"  |  "ALL"


@dataclass
class DaySchedule:
    day_number: int
    date: str          # "27.09.2025"
    site: str          # site address for this day
    slots: list[Slot] = field(default_factory=list)


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """You are an ISO audit planning expert. You generate precise, realistic
hourly audit schedules for ISO management system audits.

RULES — READ CAREFULLY:
1. Time format: use "HHMM – HHMM" (no colon, en-dash, 24-hour). Example: "0800 – 0900".
2. Working day: 0800 to approximately 1600. Include a lunch break "Break (1200 – 1230)".
3. Every audit day starts with an Opening Meeting (0800 – 0830) ONLY on Day 1.
4. Every intermediate day ends with a Wash-up Meeting (~30 min).
5. The LAST day ends with: Write Draft Report (~30 min) then Closing Meeting (~30 min).
6. Use parallel rows when two auditors audit different clauses simultaneously (same time slot).
7. Distribute ALL required clauses across the available days. Do NOT skip any clause.
8. For integrated audits (multiple standards), interleave both standards per day logically.
9. Auditor abbreviations: Lead Auditor = LA, Auditor = A, Trainee Auditor = TA,
   Technical Expert = TE, Observer = Obs.
10. For Opening/Closing/Wash-up/Site Tour/Report writing rows: standard="" clauses="".
11. For break rows: set is_break=true, standard="" clauses="" activity="Lunch Break" auditors="".

OUTPUT: Return ONLY valid JSON — no markdown fences, no explanation.

Schema:
{
  "days": [
    {
      "day_number": 1,
      "date": "DD.MM.YYYY",
      "site": "full site address",
      "slots": [
        {
          "time": "0800 – 0830",
          "is_break": false,
          "standard": "ISO 9001:2015",
          "clauses": "",
          "activity": "Opening Meeting",
          "auditors": "ALL"
        }
      ]
    }
  ]
}
"""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def generate_schedule(ctx: AuditPlanContext) -> list[DaySchedule]:
    """
    Call Claude to generate a full audit schedule from the template context.

    Args:
        ctx: Parsed AuditPlanContext from the uploaded template.

    Returns:
        List of DaySchedule objects (one per audit day).

    Raises:
        ValueError: If Claude returns invalid JSON or the schedule is empty.
    """
    settings = get_settings()
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)

    # Build clause summary for all selected standards
    clause_blocks: list[str] = []
    for std in ctx.standards:
        clauses = CLAUSE_MAP.get(std, {}).get(ctx.audit_type, "")
        if clauses:
            clause_blocks.append(f"  {std} ({ctx.audit_type}): {clauses}")
    clause_summary = "\n".join(clause_blocks) if clause_blocks else "  (no matching clauses found)"

    # Build auditor list
    auditor_lines = [f"  {a.role}: {a.name}" for a in ctx.auditors if a.name]
    auditor_summary = "\n".join(auditor_lines) if auditor_lines else "  Lead Auditor: (unknown)"

    # Build site list
    site_lines = [f"  Day site option: {s.address} — {s.process}" for s in ctx.sites]
    site_summary = "\n".join(site_lines) if site_lines else f"  HQ: {ctx.address}"

    user_message = f"""Generate a complete audit schedule for the following audit.

ORGANISATION: {ctx.org_name}
ADDRESS / HQ: {ctx.address}
STANDARD(S): {ctx.standards_raw}
AUDIT TYPE: {ctx.audit_type_raw} (mapped to: {ctx.audit_type})
AUDIT DATE(S): {ctx.audit_dates}
EFFECTIVE EMPLOYEES: {ctx.num_employees}
AUDIT DURATION: {ctx.audit_time}
SHIFT NUMBER: {ctx.shift_number}
LANGUAGE: {ctx.language}
SCOPE: {ctx.scope}
NOT APPLICABLE CLAUSES: {ctx.not_applicable}

AUDIT TEAM:
{auditor_summary}

SITES:
{site_summary}

CLAUSES TO AUDIT (from FR.222 — do not change):
{clause_summary}

INSTRUCTIONS:
- Parse the audit date(s) string "{ctx.audit_dates}" to determine how many calendar days there are.
- Create one "days" entry per calendar day.
- Distribute all clauses evenly. Cover every listed clause at least once.
- If there are 2+ auditors, create parallel rows (same time, different clauses, different auditors).
- The site address for each day: use HQ address unless additional sites are listed above.
- Return ONLY the JSON schedule as specified."""

    logger.info(
        f"[AuditPlan] Calling Claude for schedule | org='{ctx.org_name}' "
        f"standards={ctx.standards} type='{ctx.audit_type}' dates='{ctx.audit_dates}'"
    )

    response = client.messages.create(
        model=settings.claude_model,
        max_tokens=4096,
        system=_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_message}],
    )

    raw = response.content[0].text.strip()
    logger.debug(f"[AuditPlan] Claude raw response ({len(raw)} chars): {raw[:400]}")

    # Strip markdown fences if present
    raw_clean = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
    raw_clean = re.sub(r"\s*```$", "", raw_clean, flags=re.IGNORECASE).strip()

    try:
        payload = json.loads(raw_clean)
    except json.JSONDecodeError as exc:
        logger.error(f"[AuditPlan] Claude returned invalid JSON: {exc}\nRaw: {raw[:600]}")
        raise ValueError(f"Claude returned invalid JSON: {exc}") from exc

    days_raw = payload.get("days", [])
    if not days_raw:
        raise ValueError("Claude returned an empty schedule (no days).")

    days: list[DaySchedule] = []
    for d in days_raw:
        slots: list[Slot] = []
        for s in d.get("slots", []):
            slots.append(Slot(
                time=s.get("time", ""),
                is_break=bool(s.get("is_break", False)),
                standard=s.get("standard", ""),
                clauses=s.get("clauses", ""),
                activity=s.get("activity", ""),
                auditors=s.get("auditors", ""),
            ))
        days.append(DaySchedule(
            day_number=int(d.get("day_number", len(days) + 1)),
            date=d.get("date", ""),
            site=d.get("site", ctx.address),
            slots=slots,
        ))

    logger.info(f"[AuditPlan] Schedule generated: {len(days)} day(s), "
                f"{sum(len(d.slots) for d in days)} total slots.")
    return days
