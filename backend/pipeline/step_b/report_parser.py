"""
BATUHAN — Step B: Report Parser
Parses the raw Claude Prompt B response into a validated GeneratedReport object.
Expected output format (per prompt_b.txt):

    Section Title:
    [Exact title from template]

    Content:
    [Well-written paragraph(s)]

    ---

Each section block is separated by '---' on its own line.
"""

from __future__ import annotations
import re
import logging
from schemas.models import GeneratedReport, ReportSection, ISOStandard, AuditStage

logger = logging.getLogger(__name__)

# Markers for weak-evidence phrasing (injected by Prompt B when evidence is poor)
WEAK_EVIDENCE_PHRASES = [
    "limited documented evidence",
    "the available evidence indicates",
    "based on the documented information provided",
    "was not observed",
    "not clearly evidenced",
    "insufficient evidence",
    "no evidence",
    "could not be confirmed",
]

PLACEHOLDER_PATTERNS = [
    re.compile(r"\[.*?\]"),        # [placeholder]
    re.compile(r"\{.*?\}"),        # {placeholder}
    re.compile(r"<.*?>"),          # <placeholder>
    re.compile(r"INSERT\s+HERE", re.IGNORECASE),
    re.compile(r"TO\s+BE\s+COMPLETED", re.IGNORECASE),
    re.compile(r"TBD", re.IGNORECASE),
    re.compile(r"N/A\s+\(placeholder\)", re.IGNORECASE),
]


def _has_placeholder(text: str) -> bool:
    return any(p.search(text) for p in PLACEHOLDER_PATTERNS)


def _is_weak_section(content: str) -> bool:
    lower = content.lower()
    return any(phrase in lower for phrase in WEAK_EVIDENCE_PHRASES)


def _strip_markdown(text: str) -> str:
    """
    Remove common markdown formatting characters from a single line so that
    label-matching regexes work regardless of how Claude wraps them.

    Handles:
      **Section Title:**  →  Section Title:
      ## Section Title:   →  Section Title:
      __Content:__        →  Content:
      `Section Title:`    →  Section Title:
    """
    # Strip leading heading markers (# ## ### …)
    text = re.sub(r"^#+\s*", "", text)
    # Strip surrounding bold/italic/code markers (* ** _ __ `)
    text = re.sub(r"[*_`]+", "", text)
    return text.strip()


def _split_blocks(raw_output: str) -> list[str]:
    """Split the raw output into individual section blocks by '---' separator."""
    # 1. Strip markdown code fences the model may wrap everything in
    raw_output = re.sub(r"^```[a-z]*\n?", "", raw_output.strip(), flags=re.IGNORECASE)
    raw_output = re.sub(r"\n?```$", "", raw_output.strip(), flags=re.IGNORECASE)

    # 2. Normalise line endings
    raw_output = raw_output.replace("\r\n", "\n").replace("\r", "\n")

    # 3. Ensure every standalone '---' line is surrounded by newlines so the
    #    split regex can find it even at the very start/end of the response.
    raw_output = re.sub(r"(?<!\n)(^|\n)\s*---\s*(\n|$)(?!\n)",
                        "\n\n---\n\n", raw_output, flags=re.MULTILINE)

    # 4. Split on '---' standing alone on a line
    blocks = re.split(r"\n\s*---\s*\n", raw_output)
    return [b.strip() for b in blocks if b.strip()]


def _parse_block(block: str) -> tuple[str, str] | None:
    """
    Parse a single section block.
    Returns (title, content) or None if unparseable.

    Handles both:
      Section Title:\n[title]\n\nContent:\n[content]
    and the inline form:
      Section Title: [title]
    """
    title: str = ""
    content: str = ""

    lines = block.splitlines()
    mode = None  # "title" | "content"
    title_lines: list[str] = []
    content_lines: list[str] = []

    for line in lines:
        stripped = line.strip()
        # Strip markdown formatting before label-matching so that
        # "**Section Title:**", "## Content:", etc. all match correctly.
        cleaned = _strip_markdown(stripped)
        if re.match(r"^Section\s+Title\s*:", cleaned, re.IGNORECASE):
            mode = "title"
            # Inline: "Section Title: The actual title"
            inline = re.sub(r"^Section\s+Title\s*:\s*", "", cleaned, flags=re.IGNORECASE).strip()
            if inline:
                title_lines.append(inline)
        elif re.match(r"^Content\s*:", cleaned, re.IGNORECASE):
            mode = "content"
            inline = re.sub(r"^Content\s*:\s*", "", cleaned, flags=re.IGNORECASE).strip()
            if inline:
                content_lines.append(inline)
        elif mode == "title":
            if stripped:
                title_lines.append(stripped)
        elif mode == "content":
            content_lines.append(line)  # preserve original spacing for content

    title = " ".join(title_lines).strip()
    content = "\n".join(content_lines).strip()

    if not title or not content:
        return None
    return title, content


def parse_report_output(
    raw_output: str,
    job_id: str,
    standards: list[ISOStandard],
    stage: AuditStage,
    expected_titles: list[str] | None = None,
) -> GeneratedReport:
    """
    Parse the raw Prompt B response into a GeneratedReport.

    Args:
        raw_output:      Full Claude response text.
        job_id:          Current job ID.
        standards:       Selected ISO standard(s).
        stage:           Audit stage.
        expected_titles: Ordered list of section titles from the template (for ordering).

    Raises:
        ValueError: If the output is empty or no sections could be parsed.
    """
    if not raw_output or not raw_output.strip():
        raise ValueError("Prompt B returned empty output. Cannot proceed.")

    blocks = _split_blocks(raw_output)
    if not blocks:
        raise ValueError(
            "Prompt B output has no recognisable section blocks (missing '---' separators)."
        )

    sections: list[ReportSection] = []
    for i, block in enumerate(blocks):
        parsed = _parse_block(block)
        if parsed is None:
            logger.warning(f"[Step B] Could not parse block {i + 1}. Skipping.")
            continue
        title, content = parsed
        has_weak = _is_weak_section(content)
        has_placeholder = _has_placeholder(content)
        if has_placeholder:
            logger.warning(
                f"[Step B] Section '{title}' contains placeholder text. "
                "Flagging for retry."
            )
        # Determine order index: match against expected_titles if provided
        order_index = i
        if expected_titles:
            for idx, expected in enumerate(expected_titles):
                if expected.strip().lower() == title.strip().lower():
                    order_index = idx
                    break

        sections.append(ReportSection(
            title=title,
            content=content,
            order_index=order_index,
            has_weak_evidence=has_weak,
        ))

    if not sections:
        raise ValueError(
            "Prompt B output could not be parsed into any report sections. "
            "Response may be malformed."
        )

    # Sort by order_index to respect template order
    sections.sort(key=lambda s: s.order_index)

    logger.info(
        f"[Step B] Parsed {len(sections)} sections "
        f"({sum(1 for s in sections if s.has_weak_evidence)} with weak evidence)."
    )

    return GeneratedReport(
        job_id=job_id,
        standards=standards,
        stage=stage,
        sections=sections,
        raw_output=raw_output,
    )

