"""Tests for app/core/exports.py. Terms are invented words, never golden-set terms."""
import io
import sys
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))

from core import exports  # noqa: E402

CAMPAIGN = "Camp X"
ROWS = [
    # Month, Term, Ad group, Intent stage, Decision, Reason, Clicks, Cost
    ("August 2026", "quillon login", "Group 1", "navigational", "block", "Login.", 5, 7.33),
    ("September 2026", "quillon login", "Group 1", "navigational", "block", "Login.", 2, 1.10),
    ("August 2026", "Quillon Login", "Group 2", "navigational", "block", "Login.", 1, 0.50),
    ("August 2026", "zorbix reader", "Group 1", "transactional", "target", "Fits.", 3, 10.25),
    ("September 2026", "zorbix reader", "Group 1", "transactional", "target", "Fits.", 2, 4.10),
    ("August 2026", "zorbix reader", "Group 2", "transactional", "target", "Fits.", 1, 1.15),
    ("August 2026", "flarnet guide", "Group 2", "informational", "monitor", "Learning.", 4, 2.02),
    ("September 2026", "flarnet guide", "Group 1", "informational", "monitor", "Learning.", 6, 3.03),
    ("September 2026", "vexmo hub", "Group 2", "", "error", "No valid answer after one retry.", 1, 0.99),
]


def table():
    return pd.DataFrame(ROWS, columns=["Month", "Term", "Ad group", "Intent stage", "Decision", "Reason", "Clicks",
                                       "Cost"])


def round_trip(frame):
    return pd.read_csv(io.BytesIO(exports.to_csv(frame)))


class Negatives(unittest.TestCase):
    def test_one_row_per_distinct_block_term(self):
        out = exports.negatives(table(), CAMPAIGN)
        self.assertEqual(list(out.columns), ["Campaign", "Keyword", "Match type"])
        self.assertEqual(out.to_dict("records"),
                         [{"Campaign": CAMPAIGN, "Keyword": "quillon login", "Match type": "negative exact"}])

    def test_follows_a_changed_decision_and_skips_errors(self):
        t = table()
        t.loc[t["Term"] == "flarnet guide", "Decision"] = "block"
        self.assertEqual(list(exports.negatives(t, CAMPAIGN)["Keyword"]), ["quillon login", "flarnet guide"])
        self.assertNotIn("vexmo hub", list(exports.negatives(t, CAMPAIGN)["Keyword"]))

    def test_empty_list_keeps_its_columns(self):
        t = table()
        out = exports.negatives(t[t["Decision"] != "block"], CAMPAIGN)
        self.assertEqual((len(out), list(out.columns)), (0, ["Campaign", "Keyword", "Match type"]))


class NewKeywords(unittest.TestCase):
    def test_one_row_per_distinct_term_per_ad_group(self):
        out = exports.new_keywords(table(), CAMPAIGN)
        self.assertEqual(list(out.columns), ["Campaign", "Ad group", "Keyword", "Match type"])
        self.assertEqual(out.to_dict("records"), [
            {"Campaign": CAMPAIGN, "Ad group": "Group 1", "Keyword": "zorbix reader", "Match type": "exact"},
            {"Campaign": CAMPAIGN, "Ad group": "Group 2", "Keyword": "zorbix reader", "Match type": "exact"},
        ])

    def test_no_error_rows(self):
        t = table()
        self.assertNotIn("vexmo hub", list(exports.new_keywords(t, CAMPAIGN)["Keyword"]))


class Watchlist(unittest.TestCase):
    def test_one_row_per_term_with_metrics_summed_across_months(self):
        out = exports.watchlist(table())
        self.assertEqual(list(out.columns), ["Search term", "Ad group", "Intent stage", "Reason", "Clicks", "Cost"])
        self.assertEqual(out.to_dict("records"), [{
            "Search term": "flarnet guide", "Ad group": "Group 2; Group 1", "Intent stage": "informational",
            "Reason": "Learning.", "Clicks": 10, "Cost": 5.05,
        }])

    def test_no_error_rows_and_empty_list_keeps_its_columns(self):
        t = table()
        t = t[t["Decision"].isin(["error", "block"])]
        out = exports.watchlist(t)
        self.assertEqual((len(out), list(out.columns)), (0, exports.WATCHLIST_COLUMNS))


def with_rows(rows):
    return pd.DataFrame([("August 2026", term, group, "transactional", decision, "Invented.", 1, 1.00)
                         for term, group, decision in rows], columns=table().columns)


class TermKey(unittest.TestCase):
    """ß and ss fold to the same key in triage, so they are one term in every list."""

    def test_sharp_s_pair_is_one_row_in_each_list(self):
        for decision, build in (("block", lambda t: exports.negatives(t, CAMPAIGN)),
                                ("target", lambda t: exports.new_keywords(t, CAMPAIGN)),
                                ("monitor", exports.watchlist)):
            out = build(with_rows([("zorbix straße", "Group 1", decision), ("zorbix strasse", "Group 1", decision)]))
            self.assertEqual(len(out), 1, decision)


class Notation(unittest.TestCase):
    """Quotes and brackets are match-type notation in Editor; with Match type set they would conflict."""

    def test_quotes_and_brackets_are_removed_and_spaces_collapsed(self):
        t = with_rows([('"zorbix reader"', "Group 1", "block"), ("[quillon  pos]", "Group 1", "block"),
                       ('flarnet "best" guide', "Group 1", "target"), ("[vexmo] [hub]", "Group 2", "target")])
        self.assertEqual(list(exports.negatives(t, CAMPAIGN)["Keyword"]), ["zorbix reader", "quillon pos"])
        self.assertEqual(list(exports.new_keywords(t, CAMPAIGN)["Keyword"]), ["flarnet best guide", "vexmo hub"])

    def test_a_term_empty_after_cleaning_is_left_out(self):
        t = with_rows([('""', "Group 1", "block"), ("[ ]", "Group 1", "target"), ("zorbix reader", "Group 1", "target")])
        self.assertEqual(len(exports.negatives(t, CAMPAIGN)), 0)
        self.assertEqual(list(exports.new_keywords(t, CAMPAIGN)["Keyword"]), ["zorbix reader"])

    def test_spellings_that_clean_to_one_keyword_are_one_row(self):
        t = with_rows([('"zorbix reader"', "Group 1", "block"), ("zorbix reader", "Group 1", "block")])
        self.assertEqual(len(exports.negatives(t, CAMPAIGN)), 1)


class Conflicts(unittest.TestCase):
    """Two terms that clean to one keyword under different decisions go in neither Editor file."""

    def pair(self):
        return with_rows([('"zorbix reader"', "Group 1", "block"), ("zorbix reader", "Group 1", "target"),
                          ("quillon pos", "Group 1", "target")])

    def test_pair_is_in_neither_file_and_listed_as_a_conflict(self):
        t = self.pair()
        self.assertEqual(len(exports.negatives(t, CAMPAIGN)), 0)
        self.assertEqual(list(exports.new_keywords(t, CAMPAIGN)["Keyword"]), ["quillon pos"])
        self.assertEqual(exports.conflicts(t).to_dict("records"), [
            {"Keyword": "zorbix reader", "Search term": '"zorbix reader"', "Decision": "block"},
            {"Keyword": "zorbix reader", "Search term": "zorbix reader", "Decision": "target"},
        ])

    def test_no_conflict_when_the_decisions_agree(self):
        t = with_rows([('"zorbix reader"', "Group 1", "block"), ("zorbix reader", "Group 2", "block")])
        self.assertEqual(len(exports.conflicts(t)), 0)
        self.assertEqual(list(exports.negatives(t, CAMPAIGN)["Keyword"]), ["zorbix reader"])
        self.assertEqual(list(exports.conflicts(t).columns), exports.CONFLICT_COLUMNS)


class EmptyMonitorTerm(unittest.TestCase):
    def test_a_monitor_term_of_only_quotes_and_brackets_is_left_out(self):
        t = with_rows([('"[]"', "Group 1", "monitor"), ("flarnet guide", "Group 1", "monitor")])
        self.assertEqual(list(exports.watchlist(t)["Search term"]), ["flarnet guide"])


class Csv(unittest.TestCase):
    def test_header_is_the_first_row_with_the_exact_column_names(self):
        for frame, columns in ((exports.negatives(table(), CAMPAIGN), exports.NEGATIVE_COLUMNS),
                               (exports.new_keywords(table(), CAMPAIGN), exports.KEYWORD_COLUMNS),
                               (exports.watchlist(table()), exports.WATCHLIST_COLUMNS)):
            text = exports.to_csv(frame).decode("utf-8")
            self.assertEqual(text.splitlines()[0], ",".join(columns))
            self.assertEqual(len(round_trip(frame)), len(frame))


if __name__ == "__main__":
    unittest.main()
