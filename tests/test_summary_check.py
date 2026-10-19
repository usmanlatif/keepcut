"""Tests for evaluation/summary_check.py with a fake write_summary. Terms are invented words, never golden-set terms."""
import csv
import sys
import tempfile
import unittest
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from evaluation import summary_check  # noqa: E402

ROWS = [
    # Month, Term, Ad group, Intent stage, Decision, Clicks, Cost
    ("August 2026", "zorbix reader", "Group 1", "transactional", "target", 1200, 1000.25),
    ("September 2026", "zorbix reader", "Group 1", "transactional", "target", 300, 400.10),
    ("August 2026", "quillon login", "Group 2", "navigational", "block", 5, 7.33),
    ("September 2026", "flarnet careers", "Group 2", "navigational", "block", 1, 3.10),
    ("August 2026", "flarnet guide", "Group 3", "informational", "monitor", 4, 2.02),
    ("September 2026", "flarnet guide", "Group 3", "informational", "monitor", 6, 5.50),
    ("September 2026", "vexmo hub", "Group 3", "", "error", 1, 0.99),
    ("August 2026", "plimzor orb", "Group 1", "commercial", "target", 9, 12.00),
]
FIGS = {"total_spend": "1,234.56", "share": "12%", "new_keywords": {"count": "3"}, "months": ["August 2026"]}


def table():
    return pd.DataFrame(ROWS, columns=["Month", "Term", "Ad group", "Intent stage", "Decision", "Clicks", "Cost"])


def result(summary, recommendations=("Add the keyword.",)):
    return {"summary": summary, "recommendations": list(recommendations)}


class FakeSummary:
    """write_summary's signature; quotes the total spend from the figures it is given."""

    def __init__(self):
        self.seen = []

    def __call__(self, figures, context, call=None):
        self.seen.append(figures)
        call([{"role": "user", "content": "x"}])
        return result(f"Spend was {figures['total_spend']}. Not enough data on trends.")


def fake_call(messages, **options):
    return "{}", {"prompt": 10, "completion": 2}


class NumberTests(unittest.TestCase):
    def test_extraction(self):
        self.assertEqual(summary_check.numbers("Spend 1,234.56; share 12%; 3 keywords."), ["1,234.56", "12%", "3"])

    def test_number_in_figures_passes(self):
        check = summary_check.check_summary(result("Spend was 1,234.56 in August 2026, 12% and 3."), FIGS)
        self.assertEqual(check["figure_check"], "pass")

    def test_number_not_in_figures_fails(self):
        check = summary_check.check_summary(result("Spend was 1234.56.", ["Cut 4 terms."]), FIGS)
        self.assertEqual(check["figure_check"], "fail")
        self.assertEqual(check["missing"], ["1234.56", "4"])

    def test_leading_dot_decimal_must_match(self):
        check = summary_check.check_summary(result("Spend rose .5%."), {"total_spend": "1,234.56"})
        self.assertEqual((check["figure_check"], check["missing"]), ("fail", [".5%"]))

    def test_minus_sign_is_kept(self):
        self.assertEqual(summary_check.numbers("Spend fell -1,234.56."), ["-1,234.56"])
        check = summary_check.check_summary(result("Spend fell -1,234.56."), {"total_spend": "1,234.56"})
        self.assertEqual((check["figure_check"], check["missing"]), ("fail", ["-1,234.56"]))

    def test_hyphens_between_words_and_numbers_are_not_minus_signs(self):
        self.assertEqual(summary_check.numbers("No month-over-month change."), [])
        self.assertEqual(summary_check.numbers("Expect 2-3 new terms."), ["2", "3"])

    def test_part_of_a_figure_is_not_the_figure(self):
        self.assertEqual(summary_check.check_summary(result("Spend was 234."), FIGS)["missing"], ["234"])

    def test_number_word_fails(self):
        check = summary_check.check_summary(result("Two ad groups increased."), FIGS)
        self.assertEqual(check["figure_check"], "fail")
        self.assertEqual(check["number_words"], ["Two"])

    def test_one_and_network_pass(self):
        check = summary_check.check_summary(result("This is one of the terms on the network."), FIGS)
        self.assertEqual((check["figure_check"], check["number_words"]), ("pass", []))

    def test_app_error_fails(self):
        check = summary_check.check_summary({"error": "No valid summary."}, FIGS)
        self.assertEqual((check["figure_check"], check["error"]), ("fail", "No valid summary."))


class VariantTests(unittest.TestCase):
    def test_kinds_and_count(self):
        names = [name for name, _ in summary_check.variants(table())]
        self.assertEqual(len(names), 20)
        self.assertEqual(names[:6], ["whole table", "ad group: Group 1", "ad group: Group 2", "ad group: Group 3",
                                     "month: August 2026", "month: September 2026"])
        self.assertTrue(all(n.startswith("random half") for n in names[6:]))

    def test_same_seed_same_variants(self):
        first, second = summary_check.variants(table()), summary_check.variants(table())
        self.assertEqual([n for n, _ in first], [n for n, _ in second])
        for (_, a), (_, b) in zip(first, second):
            pd.testing.assert_frame_equal(a, b)
        halves = {tuple(part["Cost"]) for name, part in first if name.startswith("random half")}
        self.assertGreater(len(halves), 1)

    def test_run_summaries_with_fake(self):
        fake = FakeSummary()
        rows, counter, _ = summary_check.run_summaries(summary_check.variants(table()), "context",
                                                       summary_fn=fake, call=fake_call)
        self.assertEqual(len(rows), 20)
        self.assertEqual((counter.calls, counter.prompt_tokens, counter.completion_tokens), (20, 200, 40))
        self.assertTrue(all(r["figure_check"] == "pass" for r in rows))
        self.assertEqual(fake.seen[0]["total_spend"], "1,431.29")


class TableTests(unittest.TestCase):
    def test_triage_table_is_the_apps_table(self):
        rows = [{"Month": "August 2026", "Search term": "zorbix reader", "Campaign": "Camp X", "Ad group": "Group 1",
                 "Clicks": 3, "Impr.": 30, "Cost": 4.5, "Conversions": 0.0}]
        triaged = [{"id": "t1", "term": "zorbix reader", "intent": "transactional", "label": "block",
                    "trigger": "zorbix", "reason": "Invented reason."}]
        fake = lambda rows, context: type("Result", (), {"rows": triaged})()
        table, _ = summary_check.triage_table(rows, True, "context", triage_fn=fake)
        pd.testing.assert_frame_equal(table, summary_check.build_table(rows, triaged, True))
        self.assertEqual(list(table.columns), ["Month", "Term", "Ad group", "Intent stage", "Decision", "Trigger",
                                               "Reason", "Reviewer", "Reviewer note", "Clicks", "Cost", "Conversions"])


class WriteTests(unittest.TestCase):
    def test_no_overwrite(self):
        fake = FakeSummary()
        rows, counter, seconds = summary_check.run_summaries(summary_check.variants(table()), "context",
                                                             summary_fn=fake, call=fake_call)
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            existing = directory / "2026-01-01-summary-check.md"
            existing.write_text("keep", encoding="utf-8")
            first = summary_check.write_results(rows, counter, seconds, "abc", False, "2026-01-01", "base.csv",
                                                directory)
            second = summary_check.write_results(rows, counter, seconds, "abc", True, "2026-01-01", "base.csv",
                                                 directory)
            self.assertEqual(existing.read_text(encoding="utf-8"), "keep")
            self.assertEqual([p.name for p in first], ["2026-01-01-2-summary-check.md", "2026-01-01-2-summary-labels.csv"])
            self.assertEqual([p.name for p in second], ["2026-01-01-3-summary-check.md", "2026-01-01-3-summary-labels.csv"])
            self.assertIn("Passed: 20 of 20", first[0].read_text(encoding="utf-8"))
            with first[1].open(encoding="utf-8", newline="") as handle:
                reader = csv.DictReader(handle)
                labels = list(reader)
            self.assertEqual(reader.fieldnames, list(summary_check.LABEL_FIELDS))
            self.assertEqual(len(labels), 20)
            self.assertTrue(all(r["usman_label"] == "" and r["usman_note"] == "" for r in labels))

    def test_base_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = summary_check.save_base(table(), "2026-01-01", Path(tmp))
            again = summary_check.save_base(table(), "2026-01-01", Path(tmp))
            self.assertNotEqual(path, again)
            loaded = summary_check.load_base(path)
        self.assertEqual(summary_check.figures(loaded), summary_check.figures(table()))


if __name__ == "__main__":
    unittest.main()
