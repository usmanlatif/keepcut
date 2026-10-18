"""Build the account context block every model call starts with (PRD M1).

The block is profile, campaign, then app/data/labels.md verbatim (label definitions, boundary rules,
tie-breakers and the intent stages). The "What the model sees" panel prints it unchanged.
"""
from pathlib import Path

LABELS = Path(__file__).resolve().parents[1] / "data" / "labels.md"


def build_context(profile: str, campaign: str) -> str:
    labels = LABELS.read_text(encoding="utf-8").strip()
    return (
        "# Business profile\n\n"
        f"{profile.strip()}\n\n"
        "# Campaign\n\n"
        f"Every decision is for this campaign only: {campaign.strip()}\n\n"
        f"{labels}\n"
    )
