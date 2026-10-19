"""Tests for app/core/table.py. Terms are invented words, never golden-set terms."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from core.table import build_table  # noqa: E402

ROWS = [
    {"Month": "August 2026", "Search term": "zorbix login", "Campaign": "Camp X", "Ad group": "Group 1",
     "Clicks": 1, "Impr.": 10, "Cost": 2.0, "Conversions": 0.0},
    {"Month": "August 2026", "Search term": "quillon free", "Campaign": "Camp X", "Ad group": "Group 1",
     "Clicks": 2, "Impr.": 20, "Cost": 3.0, "Conversions": 0.0},
    {"Month": "September 2026", "Search term": "flarnet reader", "Campaign": "Camp X", "Ad group": "Group 2",
     "Clicks": 3, "Impr.": 30, "Cost": 4.0, "Conversions": 1.0},
]
RESULTS = [
    {"id": "t1", "term": "zorbix login", "intent": "navigational", "label": "block", "trigger": "login", "reason": "A."},
    {"id": "t2", "term": "quillon free", "intent": "informational", "label": "block", "trigger": "free", "reason": "B."},
    {"id": "t3", "term": "flarnet reader", "intent": "transactional", "label": "target", "trigger": "reader",
     "reason": "C."},
]
VERDICTS = {
    "t1": {"verdict": "challenge", "proposed_label": "monitor", "reason": "Could be a buyer."},
    "t2": {"verdict": "error", "reason": "No valid answer."},
    "t3": {"verdict": "challenge", "proposed_label": "block", "reason": "Not a block row."},
}


class BuildTableTests(unittest.TestCase):
    def test_columns_and_values(self):
        table = build_table(ROWS, RESULTS, True, VERDICTS)
        self.assertEqual(list(table.columns), ["Month", "Term", "Ad group", "Intent stage", "Decision", "Trigger",
                                               "Reason", "Reviewer", "Reviewer note", "Clicks", "Cost", "Conversions"])
        self.assertEqual(list(table["Decision"]), ["block", "block", "target"])
        self.assertEqual(list(table["Cost"]), [2.0, 3.0, 4.0])

    def test_reviewer_columns_read_only_block_rows(self):
        table = build_table(ROWS, RESULTS, True, VERDICTS)
        self.assertEqual(list(table["Reviewer"]), ["challenge", "error", ""])
        self.assertEqual(list(table["Reviewer note"]), ["monitor: Could be a buyer.", "No valid answer.", ""])

    def test_no_verdicts_leaves_reviewer_columns_empty(self):
        table = build_table(ROWS, RESULTS, True)
        self.assertEqual(list(table["Reviewer"]) + list(table["Reviewer note"]), [""] * 6)

    def test_month_dropped_without_a_month_column(self):
        self.assertNotIn("Month", build_table(ROWS, RESULTS, False, VERDICTS).columns)


if __name__ == "__main__":
    unittest.main()
