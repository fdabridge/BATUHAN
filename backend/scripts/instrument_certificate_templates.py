"""Build immutable certificate templates from the approved IFC references.

The source files remain untouched. Only mapped text nodes in word/document.xml
are replaced with compact Certiva tokens; drawings, fonts, images, anchors,
relationships, styles, and every other package part are preserved.
"""
from __future__ import annotations

import argparse
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET


W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
W = {"w": W_NS}

OUTPUT_DIR = Path(__file__).resolve().parents[1] / "audit_set" / "certificate_templates"


SPECS = {
    "QMS": {
        "source": "HANTECH_2026_ENG_DRAFT.docx",
        "paragraphs": {
            "[[COMPANY]]": [6], "[[ADDRESS]]": [8], "[[STANDARD]]": [12],
            "[[SCOPE]]": [14], "[[INITIAL_DATE]]": [23, 36],
            "[[ISSUE_DATE]]": [25, 38], "[[REVISION]]": [27, 40],
            "[[VALIDITY_DATE]]": [29, 42], "[[EXPIRY_DATE]]": [31, 44],
            "[[CERTIFICATE_NO]]": [33, 46],
        },
    },
    "EMS": {
        "source": "HANTECH_2026_ENG_DRAFT_14001.docx",
        "paragraphs": {
            "[[COMPANY]]": [6], "[[ADDRESS]]": [8], "[[STANDARD]]": [12],
            "[[SCOPE]]": [14], "[[INITIAL_DATE]]": [23, 36],
            "[[ISSUE_DATE]]": [25, 38], "[[REVISION]]": [27, 40],
            "[[VALIDITY_DATE]]": [29, 42], "[[EXPIRY_DATE]]": [31, 44],
            "[[CERTIFICATE_NO]]": [33, 46],
        },
    },
    "ISMS": {
        "source": "HANTECH_2026_ENG_DRAFT_27001.docx",
        "paragraphs": {
            "[[COMPANY]]": [4], "[[ADDRESS]]": [6], "[[STANDARD]]": [10],
            "[[SCOPE]]": [12], "[[INITIAL_DATE]]": [22, 37],
            "[[ISSUE_DATE]]": [24, 39], "[[REVISION]]": [26, 41],
            "[[VALIDITY_DATE]]": [28, 43], "[[EXPIRY_DATE]]": [30, 45],
            "[[CERTIFICATE_NO]]": [33, 48], "[[SOA]]": [34, 49],
        },
    },
    # The supplied filename says 37001, but its visible standard is ISO 22000.
    "FSMS": {
        "source": "HANTECH_2026_ENG_DRAFT_37001.docx",
        "paragraphs": {
            "[[COMPANY]]": [4], "[[ADDRESS]]": [6], "[[STANDARD]]": [10],
            "[[SCOPE]]": [12], "[[CATEGORY]]": [13],
            "[[INITIAL_DATE]]": [23, 36], "[[ISSUE_DATE]]": [25, 38],
            "[[REVISION]]": [27, 40], "[[VALIDITY_DATE]]": [29, 42],
            "[[EXPIRY_DATE]]": [31, 44], "[[CERTIFICATE_NO]]": [33, 46],
        },
    },
    "ABMS": {
        "source": "HANTECH_2026_ENG_DRAFT_37001RE.docx",
        "paragraphs": {
            "[[COMPANY]]": [4], "[[ADDRESS]]": [6], "[[STANDARD]]": [10],
            "[[SCOPE]]": [12], "[[INITIAL_DATE]]": [22, 35],
            "[[ISSUE_DATE]]": [24, 37], "[[REVISION]]": [26, 39],
            "[[VALIDITY_DATE]]": [28, 41], "[[EXPIRY_DATE]]": [30, 43],
            "[[CERTIFICATE_NO]]": [32, 45],
        },
    },
    "OHSMS": {
        "source": "HANTECH_2026_ENG_DRAFT_45001.docx",
        "paragraphs": {
            "[[COMPANY]]": [6], "[[ADDRESS]]": [8], "[[STANDARD]]": [12],
            "[[SCOPE]]": [14], "[[INITIAL_DATE]]": [24, 37],
            "[[ISSUE_DATE]]": [26, 39], "[[REVISION]]": [28, 41],
            "[[VALIDITY_DATE]]": [30, 43], "[[EXPIRY_DATE]]": [32, 45],
            "[[CERTIFICATE_NO]]": [34, 47],
        },
    },
    "MDQMS": {
        "source": "MARAI_2026_DRAFT_13485.docx",
        "paragraphs": {
            "[[COMPANY]]": [6], "[[ADDRESS]]": [8], "[[STANDARD]]": [12],
            "[[SCOPE]]": [15], "[[ISSUE_DATE]]": [31],
            "[[REVISION]]": [32], "[[VALIDITY_DATE]]": [33],
            "[[EXPIRY_DATE]]": [34], "[[CERTIFICATE_NO]]": [35],
        },
        "exact": {"24.09.2025": "[[INITIAL_DATE]]"},
    },
    "ENMS": {
        "source": "PRDC_2026_50001_DRAFT.docx",
        "paragraphs": {
            "[[COMPANY]]": [4], "[[ADDRESS]]": [6], "[[STANDARD]]": [10],
            "[[SCOPE]]": [12], "": [13], "[[ISSUE_DATE]]": [31],
            "[[REVISION]]": [32], "[[VALIDITY_DATE]]": [33],
            "[[EXPIRY_DATE]]": [34], "[[CERTIFICATE_NO]]": [35],
        },
        "exact": {"29.10.2025": "[[INITIAL_DATE]]"},
    },
}


def _set_paragraph_text(paragraph: ET.Element, value: str) -> None:
    nodes = paragraph.findall(".//w:t", W)
    if not nodes:
        raise ValueError("Mapped certificate paragraph contains no text node")
    nodes[0].text = value
    for node in nodes[1:]:
        node.text = ""


def instrument(source: Path, output: Path, spec: dict) -> None:
    with zipfile.ZipFile(source) as source_zip:
        document_xml = ET.fromstring(source_zip.read("word/document.xml"))
        paragraphs = document_xml.findall(".//w:p", W)

        for token, indexes in spec["paragraphs"].items():
            for index in indexes:
                _set_paragraph_text(paragraphs[index], token)

        for original, token in spec.get("exact", {}).items():
            matches = [
                node for node in document_xml.findall(".//w:t", W)
                if (node.text or "") == original
            ]
            if len(matches) != 1:
                raise ValueError(
                    f"Expected exactly one {original!r} node in {source}, found {len(matches)}"
                )
            matches[0].text = token

        updated_xml = ET.tostring(document_xml, encoding="utf-8", xml_declaration=True)
        output.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(output, "w") as output_zip:
            for info in source_zip.infolist():
                content = updated_xml if info.filename == "word/document.xml" else source_zip.read(info)
                output_zip.writestr(info, content)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Instrument the approved IFC certificate reference DOCX files.",
    )
    parser.add_argument(
        "--source-dir",
        type=Path,
        required=True,
        help="Directory containing the eight approved certificate reference files.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=OUTPUT_DIR,
        help="Destination for the mapped certificate templates.",
    )
    args = parser.parse_args()

    for standard, spec in SPECS.items():
        source = args.source_dir / spec["source"]
        if not source.exists():
            raise FileNotFoundError(source)
        instrument(source, args.output_dir / f"{standard}.docx", spec)
        print(f"Mapped {standard}: {source.name}")


if __name__ == "__main__":
    main()
