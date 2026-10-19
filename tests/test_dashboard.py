"""Tests for app/core/dashboard.py. Terms are invented words, never golden-set terms."""
import sys
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from core import dashboard, exports  # noqa: E402

ROWS = [
    # Month, Term, Ad group, Intent stage, Decision, Clicks, Cost
    ("August 2026", "zorbix reader", "Group 1", "transactional", "target", 3, 10.25),
    ("September 2026", "zorbix reader", "Group 1", "transactional", "target", 2, 4.10),
    ("August 2026", "Zorbix Reader ", "Group 2", "transactional", "target", 1, 1.15),
    ("September 2026", "quillon login", "Group 1", "navigational", "block", 5, 7.33),
    ("August 2026", "flarnet guide", "Group 2", "informational", "monitor", 4, 2.02),
    ("September 2026", "vexmo hub", "Group 2", "", "error", 1, 0.99),
]


def table(rows=ROWS, month=True):
    frame = pd.DataFrame(rows, columns=["Month", "Term", "Ad group", "Intent stage", "Decision", "Clicks", "Cost"])
    return frame if month else frame.drop(columns="Month")


def totals(t):
    """The total of every dashboard table for t."""
    tables = [dashboard.spend_by_decision(t), dashboard.spend_by_intent(t), dashboard.spend_by_ad_group(t)]
    out = [round(float(f["Cost"].sum()), 2) for f in tables]
    out.append(round(float(dashboard.intent_by_decision(t).to_numpy().sum()), 2))
    months = dashboard.month_by_decision(t)
    if months is not None:
        out.append(round(float(months.to_numpy().sum()), 2))
    return out


class Totals(unittest.TestCase):
    def assert_all_total(self, t, tables):
        expected = round(float(t["Cost"].sum()), 2)
        self.assertEqual(dashboard.tiles(t)["total_spend"], expected)
        self.assertEqual(totals(t), [expected] * tables)

    def test_every_table_totals_the_cost_with_two_months(self):
        self.assert_all_total(table(), 5)

    def test_every_table_totals_the_cost_without_a_month_column(self):
        t = table(month=False)
        self.assertIsNone(dashboard.month_by_decision(t))
        self.assert_all_total(t, 4)

    def test_every_table_totals_the_cost_after_a_changed_decision(self):
        t = table()
        before = dashboard.spend_by_decision(t).set_index("Decision")["Cost"]
        t.loc[t["Term"] == "flarnet guide", "Decision"] = "block"
        after = dashboard.spend_by_decision(t).set_index("Decision")["Cost"]
        self.assertAlmostEqual(after["block"], before["block"] + 2.02)
        self.assertNotIn("monitor", after.index)
        self.assert_all_total(t, 5)


class Figures(unittest.TestCase):
    def test_tiles(self):
        self.assertEqual(dashboard.tiles(table()),
                         {"total_spend": 25.84, "blocked_spend": 7.33, "new_keywords": 1})

    def test_new_keywords_follow_a_changed_decision(self):
        t = table()
        t.loc[t["Term"] == "flarnet guide", "Decision"] = "target"
        self.assertEqual(dashboard.tiles(t)["new_keywords"], 2)

    def test_new_keywords_count_terms_as_triage_does(self):
        rows = [("August 2026", "zorbix straße", "Group 1", "transactional", "target", 1, 1.00),
                ("September 2026", "zorbix strasse", "Group 1", "transactional", "target", 1, 2.00)]
        self.assertEqual(dashboard.tiles(table(rows))["new_keywords"], 1)

    def test_new_keywords_tile_equals_the_new_keywords_file(self):
        rows = [("August 2026", "[ ]", "Group 1", "transactional", "target", 1, 1.00),
                ("August 2026", '"zorbix reader"', "Group 1", "transactional", "block", 1, 1.00),
                ("August 2026", "zorbix reader", "Group 1", "transactional", "target", 1, 1.00),
                ("August 2026", "quillon pos", "Group 1", "transactional", "target", 1, 1.00)]
        t = table(rows)
        self.assertEqual(dashboard.tiles(t)["new_keywords"], len(exports.new_keywords(t, "Camp X")))
        self.assertEqual(dashboard.tiles(t)["new_keywords"], 1)

    def test_error_rows_with_no_intent_stage_are_kept(self):
        intents = dashboard.spend_by_intent(table()).set_index("Intent stage")["Cost"]
        self.assertEqual(intents[dashboard.NO_INTENT], 0.99)
        self.assertEqual(list(intents.index), ["transactional", "informational", "navigational", "none"])

    def test_month_by_decision_is_in_calendar_order(self):
        months = dashboard.month_by_decision(table())
        self.assertEqual(list(months.index), ["August 2026", "September 2026"])
        self.assertEqual(months.loc["August 2026", "target"], 11.40)
        self.assertEqual(months.loc["September 2026", "block"], 7.33)
        self.assertEqual(months.loc["August 2026", "block"], 0.0)

    def test_intent_by_decision_cells(self):
        grid = dashboard.intent_by_decision(table())
        self.assertEqual(grid.loc["transactional", "target"], 15.50)
        self.assertEqual(grid.loc["none", "error"], 0.99)
        self.assertEqual(list(grid.columns), ["target", "block", "monitor", "error"])


if __name__ == "__main__":
    unittest.main()
