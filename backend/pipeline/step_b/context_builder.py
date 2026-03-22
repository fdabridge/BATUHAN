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
STAGE 1 AUDIT FOCUS — Documentation & Readiness Review:
- Focus on whether the management system is documented and defined.
- Evaluate system design: are policies, objectives, procedures, and scope clearly established?
- Assess organisational understanding of the standard requirements.
- Review documented information: manuals, policies, procedures, records structures.
- Confirm the organisation is ready to proceed to Stage 2 implementation audit.
- Do NOT make conclusions about operational effectiveness (that is Stage 2 scope).
- Use cautious language where documentation is incomplete or unclear.
- Where documents are identified, reference them by name.
""".strip(),

    AuditStage.STAGE_2.value: """
STAGE 2 AUDIT FOCUS — Implementation & Effectiveness Review:
- Focus on whether the management system is implemented and operating effectively.
- Evaluate operational evidence: actual records, monitoring data, meeting minutes, audit results.
- Assess whether defined processes are being followed in practice.
- Look for evidence of continual improvement, corrective actions, and management engagement.
- Confirm conformance with all relevant clauses of the selected standard.
- Reference specific records, dates, and personnel roles where available in evidence.
- If implementation evidence is absent, clearly state that it was not observed.
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
    """Return the standard-specific instruction block for Prompt B."""
    return _STANDARD_INSTRUCTIONS.get(standard.value, f"Standard: {standard.value}")


# ---------------------------------------------------------------------------
# Prompt B context assembler
# ---------------------------------------------------------------------------

def build_prompt_b_context(
    standard: ISOStandard,
    stage: AuditStage,
    template_map: TemplateMap,
    style_guidance: StyleGuidance,
    evidence_text: str,
) -> dict[str, str]:
    """
    Return a dict of all template variable substitutions for prompt_b.txt:
        {standard}, {stage}, {stage_instructions}, {standard_instructions},
        {template_sections}, {extracted_evidence}, {style_guidance}
    """
    from parsers.template_parser import format_sections_for_prompt
    from parsers.style_extractor import format_style_guidance_for_prompt

    return {
        "standard": standard.value,
        "stage": stage.value,
        "stage_instructions": get_stage_instructions(stage),
        "standard_instructions": get_standard_instructions(standard),
        "template_sections": format_sections_for_prompt(template_map),
        "extracted_evidence": evidence_text,
        "style_guidance": format_style_guidance_for_prompt(style_guidance),
    }

