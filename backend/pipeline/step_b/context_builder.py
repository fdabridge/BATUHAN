"""
BATUHAN — Step B: Context Builder (T16 + T17)
Builds the stage-specific and standard-specific instruction blocks
injected into Prompt B before sending to Claude.
"""

from __future__ import annotations
from schemas.models import ISOStandard, AuditStage, StyleGuidance, TemplateMap

# ---------------------------------------------------------------------------
# T16 — Stage-Specific Instructions
# ---------------------------------------------------------------------------

_STAGE_INSTRUCTIONS: dict[str, str] = {
    AuditStage.STAGE_1.value: """
STAGE 1 AUDIT — Documentation & Readiness Review (COMPLETED AND SUCCESSFUL):
- The Stage 1 audit has been completed. The organisation's management system documentation
  was reviewed and found to be adequately established and defined.
- Write findings that confirm the documentation reviewed: policies, objectives, procedures,
  scope, and records structures were all found to be in place.
- Reference specific document names from the evidence as proof of conformity.
- The conclusion must confirm the organisation is ready to proceed to Stage 2.
- Do NOT comment on operational effectiveness (that is Stage 2 scope).
- Do NOT use cautious or hedged language — the documentation review was satisfactory.
""".strip(),

    AuditStage.STAGE_2.value: """
STAGE 2 AUDIT — Implementation & Effectiveness Review (COMPLETED AND SUCCESSFUL):
- The Stage 2 audit has been completed. The management system was found to be implemented
  and operating effectively across all applicable clauses.
- Write findings that confirm what the auditor observed: processes are being followed,
  records demonstrate conformity, and continual improvement is evident.
- Reference specific records, dates, and personnel roles where present in the evidence.
- The conclusion must confirm conformance with all applicable clauses and recommend
  certification.
- Do NOT suggest that implementation evidence was absent — the audit confirmed conformity.
""".strip(),
}


def get_stage_instructions(stage: AuditStage) -> str:
    """Return the stage-specific instruction block for Prompt B."""
    return _STAGE_INSTRUCTIONS.get(stage.value, f"Stage: {stage.value}")


# ---------------------------------------------------------------------------
# T17 — Standard-Specific Instructions
# ---------------------------------------------------------------------------

_STANDARD_INSTRUCTIONS: dict[str, str] = {
    ISOStandard.QMS.value: """
ISO 9001 — Quality Management System:
- Focus on customer focus, process approach, and risk-based thinking.
- Reference quality objectives, customer satisfaction, and product/service conformity.
- Highlight documented quality policy, quality manual, and process interactions.
- Address nonconformity, corrective action, and continual improvement.
""".strip(),

    ISOStandard.EMS.value: """
ISO 14001 — Environmental Management System:
- Focus on environmental aspects, impacts, and compliance obligations.
- Reference environmental objectives, targets, and environmental policy.
- Address emergency preparedness, legal compliance, and monitoring of environmental performance.
- Highlight operational controls for significant environmental aspects.
""".strip(),

    ISOStandard.OHSMS.value: """
ISO 45001 — Occupational Health & Safety Management System:
- Focus on hazard identification, risk assessment, and incident investigation.
- Reference OH&S policy, objectives, and worker participation mechanisms.
- Address legal and regulatory compliance for health and safety.
- Highlight emergency preparedness, PPE controls, and contractor management.
""".strip(),

    ISOStandard.FSMS.value: """
ISO 22000 — Food Safety Management System:
- Focus on hazard analysis, HACCP principles, and prerequisite programmes.
- Reference food safety policy, food safety team, and food safety objectives.
- Address traceability, allergen management, and product recall procedures.
- Highlight monitoring of critical control points and corrective actions.
""".strip(),

    ISOStandard.MDQMS.value: """
ISO 13485 — Medical Device Quality Management System:
- Focus on regulatory compliance, product safety, and risk management.
- Reference design controls, validation records, and device history files.
- Address complaint handling, vigilance reporting, and post-market surveillance.
- Highlight traceability of medical devices and supplier qualification.
""".strip(),

    ISOStandard.ISMS.value: """
ISO 27001 — Information Security Management System:
- Focus on information security risk assessment and treatment.
- Reference information security policy, asset inventory, and access controls.
- Address incident management, business continuity, and supplier security.
- Highlight Statement of Applicability and security objectives.
""".strip(),

    ISOStandard.ABMS.value: """
ISO 37001 — Anti-Bribery Management System:
- Focus on anti-bribery policy, risk assessment, and due diligence procedures.
- Reference training records, conflict of interest declarations, and reporting channels.
- Address gifts, hospitality, and political contributions controls.
- Highlight top management commitment and anti-bribery compliance function.
""".strip(),

    ISOStandard.ENMS.value: """
ISO 50001 — Energy Management System:
- Focus on energy performance indicators, energy baseline, and energy objectives.
- Reference energy review, significant energy uses, and energy action plans.
- Address metering, monitoring, and measurement of energy consumption.
- Highlight procurement of energy-efficient products and services.
""".strip(),
}


def get_standard_instructions(standard: ISOStandard) -> str:
    """Return the standard-specific instruction block for a single standard."""
    return _STANDARD_INSTRUCTIONS.get(standard.value, f"Standard: {standard.value}")


def get_combined_standard_instructions(standards: list[ISOStandard]) -> str:
    """
    Return combined instruction blocks for all selected standards.
    For integrated audits this concatenates each standard's block so Claude
    knows the requirements of every selected standard simultaneously.
    """
    blocks = [get_standard_instructions(s) for s in standards]
    if len(blocks) == 1:
        return blocks[0]
    # Prefix each block with a clear separator so Claude distinguishes them
    labelled = []
    for s, block in zip(standards, blocks):
        labelled.append(f"--- {s.value} ---\n{block}")
    return "\n\n".join(labelled)


# ---------------------------------------------------------------------------
# Prompt B context assembler
# ---------------------------------------------------------------------------

def build_prompt_b_context(
    standards: list[ISOStandard],
    stage: AuditStage,
    template_map: TemplateMap,
    style_guidance: StyleGuidance,
    evidence_text: str,
) -> dict[str, str]:
    """
    Return a dict of all template variable substitutions for prompt_b.txt:
        {standard}, {stage}, {stage_instructions}, {standard_instructions},
        {template_sections}, {extracted_evidence}, {style_guidance}

    For integrated audits, {standard} is "QMS + EMS" and
    {standard_instructions} contains the blocks for ALL selected standards.
    """
    from parsers.template_parser import format_sections_for_prompt
    from parsers.style_extractor import format_style_guidance_for_prompt

    standards_label = " + ".join(s.value for s in standards)

    return {
        "standard": standards_label,
        "stage": stage.value,
        "stage_instructions": get_stage_instructions(stage),
        "standard_instructions": get_combined_standard_instructions(standards),
        "template_sections": format_sections_for_prompt(template_map),
        "extracted_evidence": evidence_text,
        "style_guidance": format_style_guidance_for_prompt(style_guidance),
    }

