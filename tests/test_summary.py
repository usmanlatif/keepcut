"""Tests for app/core/summary.py with a fake model call. Terms are invented words, never golden-set terms."""
import json
import sys
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from core import summary  # noqa: E402
from core.context import build_context  # noqa: E402

CONTEXT = build_context("Zorbix Co sells zorbix readers.", "Camp X")
ROWS = [
    # Month, Term, Ad group, Intent stage, Decision, Clicks, Cost
    ("August 2026", "zorbix reader", "Group 1", "transactional", "target", 1200, 1000.25),
    ("September 2026", "zorbix reader", "Group 1", "transactional", "target", 300, 400.10),
    ("August 2026", "quillon login", "Group 2", "navigational", "block", 5, 7.33),
    ("September 2026", "Quillon Login", "Group 2", "navigational", "block", 2, 9.00),
    ("September 2026", "flarnet careers", "Group 2", "navigational", "block", 1, 3.10),
    ("August 2026", "flarnet guide", "Group 3", "informational", "monitor", 4, 2.02),
    ("September 2026", "flarnet guide", "Group 3", "informational", "monitor", 6, 5.50),
    ("September 2026", "vexmo hub", "Group 3", "", "error", 1, 0.99),
]

GOOD = {"summary": "Spend was 1,428.29. Blocked terms cost 19.43. One keyword was found. Not enough data on trends.",
        "recommendations": ["Add the new keyword."]}


def table(rows=ROWS):
    return pd.DataFrame(rows, columns=["Month", "Term", "Ad group", "Intent stage", "Decision", "Clicks", "Cost"])


def amount(text):
    return float(text.replace(",", ""))


class FakeCall:
    def __init__(self, *replies):
        self.replies = list(replies)
        self.requests = []

    def __call__(self, messages, **options):
        self.requests.append((messages, options))
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return (reply if isinstance(reply, str) else json.dumps(reply)), {}


class Figures(unittest.TestCase):
    def test_totals_equal_the_tables_cost(self):
        t = table()
        f = summary.figures(t)
        expected = round(float(t["Cost"].sum()), 2)
        self.assertEqual(f["total_spend"], "1,428.29")
        self.assertEqual(round(sum(map(amount, f["spend_by_decision"].values())), 2), expected)
        self.assertEqual(round(sum(map(amount, f["spend_by_intent_stage"].values())), 2), expected)

    def test_every_figure_is_a_formatted_string_and_the_table_is_json(self):
        f = summary.figures(table())
        self.assertEqual(f["spend_by_decision"],
                         {"target": "1,400.35", "block": "19.43", "monitor": "7.52", "error": "0.99"})
        self.assertEqual(f["top_blocked_terms_by_cost"],
                         [{"term": "quillon login", "cost": "16.33"}, {"term": "flarnet careers", "cost": "3.10"}])
        self.assertEqual(f["new_keywords"],
                         {"count": "1", "top_by_clicks": [{"keyword": "zorbix reader", "clicks": "1,500"}]})
        self.assertEqual(json.loads(json.dumps(f)), f)

    def test_rising_ad_groups_compare_the_latest_month_with_the_one_before(self):
        self.assertEqual(summary.figures(table())["ad_groups_rising_month_over_month"], [
            {"ad_group": "Group 2", "previous_month": "August 2026", "previous_spend": "7.33",
             "latest_month": "September 2026", "latest_spend": "12.10", "increase": "4.77"},
            {"ad_group": "Group 3", "previous_month": "August 2026", "previous_spend": "2.02",
             "latest_month": "September 2026", "latest_spend": "6.49", "increase": "4.47"},
        ])

    def test_one_month_gives_no_rising_ad_groups(self):
        one = table([r for r in ROWS if r[0] == "September 2026"])
        self.assertEqual(summary.figures(one)["ad_groups_rising_month_over_month"], [])
        self.assertEqual(summary.figures(one)["months"], ["September 2026"])

    def months(self, previous, latest):
        """The fixture with its two months renamed."""
        rename = {"August 2026": previous, "September 2026": latest}
        return summary.figures(table([(rename[r[0]],) + r[1:] for r in ROWS]))

    def test_months_with_a_gap_give_no_rising_ad_groups_and_a_note(self):
        f = self.months("August 2026", "October 2026")
        self.assertEqual(f["ad_groups_rising_month_over_month"], [])
        self.assertEqual(f["month_over_month_note"], "August 2026 and October 2026 are not consecutive months, "
                                                     "so month over month change is not reported.")

    def test_consecutive_months_give_rising_ad_groups_and_no_note(self):
        f = self.months("August 2026", "September 2026")
        self.assertEqual([g["ad_group"] for g in f["ad_groups_rising_month_over_month"]], ["Group 2", "Group 3"])
        self.assertEqual(f["month_over_month_note"], "")

    def test_december_and_january_are_consecutive(self):
        f = self.months("December 2025", "January 2026")
        self.assertEqual(f["months"], ["December 2025", "January 2026"])
        self.assertEqual([g["ad_group"] for g in f["ad_groups_rising_month_over_month"]], ["Group 2", "Group 3"])
        self.assertEqual(f["month_over_month_note"], "")

    def test_no_month_column_gives_no_rising_ad_groups(self):
        f = summary.figures(table().drop(columns="Month"))
        self.assertEqual((f["ad_groups_rising_month_over_month"], f["months"]), ([], []))

    def test_top_blocked_terms_stop_at_five(self):
        rows = [("August 2026", f"zorbix item{i} login", "Group 1", "navigational", "block", 1, float(i))
                for i in range(1, 8)]
        top = summary.figures(table(rows))["top_blocked_terms_by_cost"]
        self.assertEqual([t["cost"] for t in top], ["7.00", "6.00", "5.00", "4.00", "3.00"])


class WriteSummary(unittest.TestCase):
    def test_a_good_reply_is_returned_after_one_call(self):
        fake = FakeCall(GOOD)
        self.assertEqual(summary.write_summary(summary.figures(table()), CONTEXT, call=fake), GOOD)
        messages, options = fake.requests[0]
        self.assertEqual(options, {"temperature": 0, "response_format": {"type": "json_object"}})
        self.assertIn(CONTEXT.strip(), messages[0]["content"])
        self.assertIn('"total_spend": "1,428.29"', messages[1]["content"])

    def test_a_bad_reply_is_retried_once(self):
        fake = FakeCall({"summary": "Too short.", "recommendations": ["Do it."]}, GOOD)
        self.assertEqual(summary.write_summary({}, CONTEXT, call=fake), GOOD)
        self.assertEqual(len(fake.requests), 2)
        self.assertIn("1 sentences, not 4 to 6", fake.requests[1][0][-1]["content"])

    def test_two_bad_replies_return_an_error(self):
        fake = FakeCall("not json", {**GOOD, "recommendations": []})
        result = summary.write_summary({}, CONTEXT, call=fake)
        self.assertEqual(len(fake.requests), 2)
        self.assertEqual(list(result), ["error"])
        self.assertIn("not valid JSON", result["error"])
        self.assertIn("1 to 3 non-empty strings", result["error"])

    def test_a_failed_call_is_retried(self):
        fake = FakeCall(RuntimeError("proxy down"), GOOD)
        self.assertEqual(summary.write_summary({}, CONTEXT, call=fake), GOOD)

    def test_contract_checks(self):
        for bad in ([], {"summary": GOOD["summary"]}, {**GOOD, "recommendations": ["a", "b", "c", "d"]},
                    {**GOOD, "summary": "One. Two. Three. Four. Five. Six. Seven."}, {**GOOD, "recommendations": [" "]}):
            self.assertIsNone(summary.check(json.dumps(bad))[0], bad)
        self.assertEqual(summary.check(json.dumps(GOOD))[0], GOOD)


if __name__ == "__main__":
    unittest.main()
