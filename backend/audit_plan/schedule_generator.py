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
# Role → abbreviation map (used when building the auditor reference block)
# ---------------------------------------------------------------------------

_ROLE_ABBREV: dict[str, str] = {
    "lead auditor":     "LA",
    "auditor":          "A",
    "trainee auditor":  "TA",
    "technical expert": "TE",
    "technical experts":"TE",
    "observer":         "Obs",
}


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """You are an ISO audit planning expert. You generate precise, realistic
hourly audit schedules for ISO management system audits.

RULES — FOLLOW EXACTLY:
1. Time format: "HHMM – HHMM" (no colon, en-dash, 24-hour). Example: "0900 – 1000".
2. Working day: 0900 to approximately 1700.
   Every day MUST include one lunch break slot:
     time="1300 – 1330", is_break=true, standard="", clauses="", activity="Lunch Break", auditors="".
3. Day 1 ONLY starts with an Opening Meeting: time="0900 – 0930", standard="", clauses="",
   activity="Opening Meeting", auditors="ALL".
4. The LAST day ends with ONLY a Closing Meeting (~30 min), standard="", clauses="",
   activity="Closing Meeting", auditors="ALL".
   DO NOT add "Write Draft Report", "Wash-up Meeting", or any similar internal slot.
   The 20% reporting deduction already accounts for report-writing time.
5. Intermediate days (not the last day): end with the last audit clause slot.
   No Wash-up Meeting, no extra slots.
6. Use parallel rows when 2+ auditors audit different clauses simultaneously (same time, different row).
7. Distribute ALL listed clauses. Do NOT skip any clause group.
8. CLAUSE GROUPING — critical: always group related sub-clauses of the same section into
   one slot. Target 2–4 clauses per slot. NEVER put a single sub-clause alone in a slot
   unless it genuinely requires a full slot (e.g. a complex operational clause).
   CORRECT:   slot → clauses="7.3-7.4", next slot → clauses="7.5-7.6"
   WRONG:     slot → clauses="7.3", next slot → clauses="7.4", next → clauses="7.5"
9. For integrated audits (multiple standards), interleave the standards logically per day.
10. AUDITOR FIELD — critical: always write "Full Name (ABBREV)" — use the exact names and
    abbreviations from the AUDIT TEAM list provided. Example: "Hasan Eryılmaz (LA)".
    For whole-team rows (Opening/Closing Meeting, Site Tour): write "ALL".
    NEVER write only the abbreviation alone (e.g. never just "LA").
11. For Opening Meeting, Closing Meeting, Site Tour rows: standard="", clauses="".
12. For break rows (is_break=true): standard="", clauses="", activity="Lunch Break", auditors="".

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
          "time": "0900 – 0930",
          "is_break": false,
          "standard": "",
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

    # Build auditor list in "Full Name (ABBREV)" format so Claude copies it verbatim
    auditor_lines: list[str] = []
    for a in ctx.auditors:
        if not a.name:
            continue
        abbrev = _ROLE_ABBREV.get(a.role.lower().strip(), "A")
        auditor_lines.append(f"  {a.name} ({abbrev})")
    auditor_summary = "\n".join(auditor_lines) if auditor_lines else "  (unknown) (LA)"

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
- Parse "{ctx.audit_dates}" to count calendar days; create one "days" entry per day.
- Day 1: first slot = Opening Meeting (0900–0930, auditors="ALL").
- Every day: include a Lunch Break slot (is_break=true, time="1300 – 1330", activity="Lunch Break").
- Last day: final slot = Closing Meeting (~30 min, auditors="ALL"). NO Write Draft Report. NO Wash-up Meeting.
- Intermediate days: end with the last audit clause slot only.
- Distribute all clauses. Group sub-clauses: never one sub-clause alone in a slot.
- If 2+ auditors: create parallel rows (same time, different clauses, different auditors).
- Site for each day: use HQ address unless additional sites are listed above.
- Auditor field: ALWAYS "Full Name (ABBREV)" from the AUDIT TEAM list. NEVER abbreviation alone.
- Return ONLY valid JSON."""

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
