import json
from pathlib import Path


def load_review_profile(accreditation_body: str) -> dict:
    """
    Loads the review rule profile for the given accreditation body.
    accreditation_body: "UAF" or "TURKAK"
    Returns the profile as a dict.
    Raises FileNotFoundError if profile does not exist.
    """
    key = accreditation_body.upper().replace("Ü", "U").replace("TÜRKAK", "TURKAK")
    path = Path(__file__).parent / f"{key.lower()}.json"
    if not path.exists():
        raise FileNotFoundError(
            f"No review profile found for accreditation body: {accreditation_body}. "
            f"Expected at {path}"
        )
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def list_available_profiles() -> list:
    """Returns list of available accreditation body codes."""
    return [
        p.stem.upper()
        for p in Path(__file__).parent.glob("*.json")
    ]
