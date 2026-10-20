"""Tests for the account context block in app/core/context.py. Terms are invented words, never golden-set terms."""
import sys
import unittest
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(APP))

from core.context import LABELS, build_context  # noqa: E402

PROFILE = "# Zorbix Widgets (invented)\n\n- What it sells: invented widgets."


class Context(unittest.TestCase):
    def labels(self):
        return LABELS.read_text(encoding="utf-8").strip()

    def test_a_picked_campaign_keeps_the_campaign_section(self):
        self.assertEqual(build_context(PROFILE, " Camp A "), (
            "# Business profile\n\n"
            f"{PROFILE}\n\n"
            "# Campaign\n\n"
            "Every decision is for this campaign only: Camp A\n\n"
            f"{self.labels()}\n"
        ))

    def test_no_campaign_leaves_the_campaign_section_out(self):
        for campaign in ("", "   "):
            context = build_context(PROFILE, campaign)
            self.assertEqual(context, f"# Business profile\n\n{PROFILE}\n\n{self.labels()}\n")
            self.assertNotIn("# Campaign", context)
            self.assertNotIn("campaign only:", context)


if __name__ == "__main__":
    unittest.main()
