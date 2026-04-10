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

RULES — FOLLOW EXACTLY:
1. Time format: "HH.MM – HH.MM" (dot separator, en-dash, 24-hour).
   CORRECT: "09.00 – 10.00", "13.00 – 14.00", "14.30 – 15.30"
   WRONG:   "0900 – 1000", "09:00 – 10:00", "9.00 – 10.00"
2. Working day: 09.00 to approximately 17.00.
   Every day MUST include ONE lunch break slot:
     time="13.00 – 14.00", is_break=true, standard="", clauses="", activity="Lunch Break", auditors="".
   Lunch is ALWAYS exactly 60 minutes. The slot immediately after lunch MUST start at 14.00.
3. Day 1 ONLY starts with an Opening Meeting:
     time="09.00 – 09.30", is_break=false, standard="", clauses="", activity="Opening Meeting", auditors=<whole-team string>.
4. The LAST day ends with ONLY a Closing Meeting (~30 min):
     standard="", clauses="", activity="Closing Meeting", auditors=<whole-team string>.
   DO NOT add "Write Draft Report", "Wash-up Meeting", or any similar internal slot.
   The 20% reporting deduction already accounts for report-writing time.
5. Intermediate days (not the last day): end with the last audit clause slot only.
   No Wash-up Meeting, no extra slots.
6. CONTINUITY — critical: the schedule must be fully continuous with NO gaps.
   The start time of every slot must exactly equal the end time of the preceding slot
   within each auditor's own track. Every minute of each auditor's day must be accounted for.
7. CLAUSE NON-REPETITION — critical: every clause must appear EXACTLY ONCE across the
   entire schedule. NEVER re-audit a clause that has already been scheduled.
   If all required clauses are covered before the final day ends, fill remaining audit time
   with clearly labelled activities such as:
     "Production Floor Walkthrough", "Document Review and Records Verification",
     "Site Tour", or "Observation of Operations"
   NEVER fill spare time by repeating any previously scheduled clause.
8. CLAUSE GROUPING — critical: always group related sub-clauses of the same section into
   one slot. Target 2–4 clauses per slot. NEVER put a single sub-clause alone in a slot
   unless it genuinely requires a full slot (e.g. a complex operational clause).
   CORRECT:   slot → clauses="7.3-7.4", next slot → clauses="7.5-7.6"
   WRONG:     slot → clauses="7.3", next slot → clauses="7.4", next → clauses="7.5"
9. INTEGRATED AUDIT STRATEGY — two modes, chosen by the INSTRUCTIONS block:
   a) SIMULTANEOUS MODE (few days): audit shared clause numbers once for ALL standards
      in the same slot. The Standard field must list every applicable standard
      (e.g. "ISO 14001:2015\nISO 45001:2018"). Standard-specific clauses get their own
      slot with only that standard in the Standard field.
   b) BLOCK MODE (many days): dedicate consecutive day blocks to each standard.
      Complete all of Standard A's clauses first, then Standard B's, etc.
      The first day of each NEW standard block gets its own Opening Meeting + Site Tour,
      just like Day 1. Auditors field on those meetings = <whole-team string>.
10. AUDITOR TRACKS — critical:
    a) Each auditor runs their OWN independent track. Parallel tracks do NOT need to share
       the same time boundaries — each track's slots are continuous within themselves.
    b) Trainee Auditor (TA) is ALWAYS on the Lead Auditor's (LA) track — never alone.
    c) Auditor (A) always runs an independent track.
    d) Whole-team slots (Opening/Closing Meeting, Site Tour, block-transition Opening Meeting):
       all auditors appear together using the WHOLE-TEAM STRING provided in INSTRUCTIONS.
    e) Per-track auditor strings:
       - LA alone or LA+TA: use exactly the TRACK STRING provided in INSTRUCTIONS.
       - A alone: use exactly the TRACK STRING provided in INSTRUCTIONS.
    f) NEVER write only the abbreviation alone (e.g. never just "LA" or "A").
11. STANDARD FIELD in slots:
    - Single-standard audit: always that standard's name.
    - Integrated audit, simultaneous mode: list all standards that apply to the clause(s)
      in that slot, separated by newline (e.g. "ISO 14001:2015\nISO 45001:2018").
    - Opening Meeting, Closing Meeting, Site Tour, walkthroughs: standard="" clauses="".
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
          "time": "09.00 – 09.30",
          "is_break": false,
          "standard": "",
          "clauses": "",
          "activity": "Opening Meeting",
          "auditors": "<whole-team string>"
        }
      ]
    }
  ]
}
"""


# ---------------------------------------------------------------------------
# Day-count helper
# ---------------------------------------------------------------------------

def _count_audit_days(dates_str: str) -> int:
    """
    Estimate the number of calendar audit days from the raw date string.

    Handles formats like:
      "27-28.09.2025"               → 2
      "08-09.10.2025"               → 2
      "18,20,21,22,23.12.2025"      → 5
      "13,14.12.2025"               → 2
      "04-05.09.2025"               → 2
    """
    # Comma-separated list: count tokens
    parts = [p.strip() for p in re.split(r"[,;]", dates_str) if p.strip()]
    if len(parts) > 1:
        return len(parts)
    # Day range like "27-28": second number minus first + 1
    m = re.search(r"\b(\d{1,2})-(\d{1,2})\b", dates_str)
    if m:
        d1, d2 = int(m.group(1)), int(m.group(2))
        if d2 > d1:
            return d2 - d1 + 1
    return 1


# ---------------------------------------------------------------------------
# Auditor track builder
# ---------------------------------------------------------------------------

def _build_auditor_tracks(ctx: AuditPlanContext) -> tuple[str, str, str]:
    """
    Derive three strings consumed by the Claude prompt:

    Returns:
        track_summary  — one line per parallel track, describing who runs it
        whole_team_str — the string to use in Opening/Closing/whole-team slots
        strategy_note  — additional note for Claude about LA+TA pairing
    """
    la_list  = [a for a in ctx.auditors if a.name and "lead"     in a.role.lower()]
    a_list   = [a for a in ctx.auditors if a.name and a.role.lower().strip() == "auditor"]
    ta_list  = [a for a in ctx.auditors if a.name and "trainee"  in a.role.lower()]
    te_list  = [a for a in ctx.auditors if a.name and "technical" in a.role.lower()]

    tracks: list[str] = []

    # LA track (TA always joins LA if present)
    for la in la_list:
        la_str = f"{la.name} (LA)"
        if ta_list:
            ta_part = " & ".join(f"{ta.name} (TA)" for ta in ta_list)
            tracks.append(f"  LA track: {la_str} & {ta_part}")
        else:
            tracks.append(f"  LA track: {la_str}")

    # Independent A tracks
    for a in a_list:
        tracks.append(f"  A track:  {a.name} (A)")

    # TE tracks (independent)
    for te in te_list:
        tracks.append(f"  TE track: {te.name} (TE)")

    track_summary = "\n".join(tracks) if tracks else "  (single auditor — no parallel tracks)"

    # Whole-team string — format differs by team size
    all_parts: list[str] = []
    for la in la_list:
        all_parts.append(f"{la.name} (LA)")
    for a in a_list:
        all_parts.append(f"{a.name} (A)")
    for ta in ta_list:
        all_parts.append(f"{ta.name} (TA)")
    for te in te_list:
        all_parts.append(f"{te.name} (TE)")

    if len(all_parts) == 0:
        whole_team_str = "(unknown) (LA)"
    elif len(all_parts) == 1:
        whole_team_str = all_parts[0]
    elif len(all_parts) == 2:
        # "Name (LA)\n& Name (A)"
        whole_team_str = f"{all_parts[0]}\\n& {all_parts[1]}"
    else:
        # "Name (LA),\nName (A) & Name (TA)"
        whole_team_str = f"{all_parts[0]},\\n{' & '.join(all_parts[1:])}"

    strategy_note = (
        "TA is always on the same track as LA — never assign TA to a slot alone. "
        "Each A runs their own independent parallel track."
    )

    return track_summary, whole_team_str, strategy_note


# ---------------------------------------------------------------------------
# Time normalisation helper
# ---------------------------------------------------------------------------

def _normalise_time(raw: str) -> str:
    """
    Convert any time range string returned by Claude into the canonical
    "HH.MM – HH.MM" format (dot separator, en-dash, two-digit hours and minutes).

    Handles inputs like: "0900 – 1030", "09:00 – 10:30", "09.00-10.30", "9.00 – 10.30"
    Returns the original string unchanged if it cannot be parsed.
    """
    # Match one or two time tokens separated by a dash/en-dash (with optional spaces)
    pattern = re.compile(
        r"(\d{1,2})[:.]?(\d{2})\s*[-\u2013]+\s*(\d{1,2})[:.]?(\d{2})"
    )
    m = pattern.search(raw)
    if m:
        h1, m1, h2, m2 = m.group(1), m.group(2), m.group(3), m.group(4)
        return f"{int(h1):02d}.{m1} \u2013 {int(h2):02d}.{m2}"
    return raw


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

    # Build auditor tracks and whole-team string
    track_summary, whole_team_str, strategy_note = _build_auditor_tracks(ctx)

    # Determine integrated audit strategy (block vs simultaneous)
    total_days   = _count_audit_days(ctx.audit_dates)
    num_stds     = len(ctx.standards)
    if num_stds >= 2 and total_days > 0:
        days_per_std = total_days / num_stds
        int_mode     = "BLOCK" if days_per_std > 2 else "SIMULTANEOUS"
    else:
        int_mode     = "SINGLE"  # not an integrated audit

    int_mode_instruction = {
        "SIMULTANEOUS": (
            "INTEGRATED MODE: SIMULTANEOUS — audit shared clause numbers together for all "
            "standards in the same slot. Standard field = all applicable standards, newline-separated. "
            "Standard-specific clauses get their own slot showing only that standard."
        ),
        "BLOCK": (
            f"INTEGRATED MODE: BLOCK — cover each standard in its own day block. "
            f"Complete ALL clauses for {ctx.standards[0] if ctx.standards else 'Standard A'} first, "
            f"then ALL clauses for the remaining standard(s). "
            "The FIRST day of each new standard block gets its own Opening Meeting (09.00–09.30) "
            f"and Site Tour (09.30–10.00), auditors=\"{whole_team_str}\", standard=\"\", clauses=\"\"."
        ),
        "SINGLE": "Single standard audit — no integration strategy needed.",
    }[int_mode]

    # Build site list
    site_lines = [f"  Day site option: {s.address} — {s.process}" for s in ctx.sites]
    site_summary = "\n".join(site_lines) if site_lines else f"  HQ: {ctx.address}"

    user_message = f"""Generate a complete audit schedule for the following audit.

ORGANISATION: {ctx.org_name}
ADDRESS / HQ: {ctx.address}
STANDARD(S): {ctx.standards_raw}
AUDIT TYPE: {ctx.audit_type_raw} (mapped to: {ctx.audit_type})
AUDIT DATE(S): {ctx.audit_dates}  [{total_days} day(s) total]
EFFECTIVE EMPLOYEES: {ctx.num_employees}
AUDIT DURATION: {ctx.audit_time}
SHIFT NUMBER: {ctx.shift_number}
LANGUAGE: {ctx.language}
SCOPE: {ctx.scope}
NOT APPLICABLE CLAUSES: {ctx.not_applicable}

AUDIT TEAM TRACKS (use EXACTLY these strings in auditor fields):
{track_summary}
  Whole-team string (Opening/Closing/Site Tour): "{whole_team_str}"
  Note: {strategy_note}

SITES:
{site_summary}

CLAUSES TO AUDIT (from FR.222 — do not change):
{clause_summary}

INSTRUCTIONS:
- Parse "{ctx.audit_dates}" → {total_days} day(s). Create one "days" entry per calendar day.
- Day 1: first slot = Opening Meeting (09.00–09.30, auditors="{whole_team_str}").
- Every day: one Lunch Break — is_break=true, time="13.00 – 14.00" (60 min), activity="Lunch Break".
  The slot after lunch MUST start at 14.00.
- Last day: final slot = Closing Meeting (~30 min, auditors="{whole_team_str}").
  NO Write Draft Report. NO Wash-up Meeting.
- Intermediate days: end with the last audit clause slot only.
- {int_mode_instruction}
- Each auditor track is INDEPENDENT — tracks do not have to share time boundaries.
  Slots within each track must be continuous (each slot's start = that track's previous slot's end).
  Only whole-team slots (Opening/Closing Meeting, Site Tour) synchronise all tracks.
- Every clause must appear EXACTLY ONCE. Fill spare time with "Production Floor Walkthrough"
  or "Document Review and Records Verification" — never re-audit a covered clause.
- Group sub-clauses: never one sub-clause alone in a slot unless it genuinely needs a full slot.
- Site for each day: use HQ address unless additional sites are listed above.
- Time format: "HH.MM – HH.MM" (dot separator). Example: "09.00 – 10.30".
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
                time=_normalise_time(s.get("time", "")),
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
