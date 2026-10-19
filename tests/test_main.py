"""Tests for the screen in app/main.py with Streamlit's AppTest. Triage and the reviewer run their real code with
fake model calls, so no model is reached. Terms are invented words, never golden-set terms."""
import json
import re
import sys
import unittest
from html import unescape
from pathlib import Path
from unittest import mock

import pandas as pd
from streamlit.testing.v1 import AppTest

APP = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(APP))

import core.reviewer  # noqa: E402
import core.triage  # noqa: E402
from core.edits import apply_decision_edits  # noqa: E402

TAG = re.compile(r'<term id="([^"]+)">(.*?)</term>')
REAL_TRIAGE_REPORT = core.triage.triage_report
REAL_REVIEW = core.reviewer.review

TWO_CAMPAIGNS = (
    "Search term,Campaign,Ad group,Clicks,Impr.,Cost,Conversions\n"
    "zorbix card reader,Camp B,Group 1,1,10,2.00,0\n"
    "quillon pos system,Camp A,Group 2,2,20,3.00,1\n"
    "flarnet payment gateway,Camp B,Group 1,3,30,4.00,0\n"
)

THREE_BLOCKS = (
    "Search term,Campaign,Ad group,Clicks,Impr.,Cost,Conversions\n"
    "zorbix login,Camp C,Group 1,1,10,2.00,0\n"
    "quillon careers,Camp C,Group 1,2,20,3.00,0\n"
    "flarnet free,Camp C,Group 2,3,30,4.00,0\n"
    "vexmo reader,Camp C,Group 2,4,40,5.00,1\n"
)


def monitor_everything(messages, **options):
    """Answers every term as monitor, triggered by its first word."""
    pairs = [(tid, unescape(term)) for tid, term in TAG.findall(messages[1]["content"])]
    results = [{"id": tid, "intent": "commercial", "label": "monitor", "trigger": term.split()[0],
                "reason": "Invented reason."} for tid, term in pairs]
    return json.dumps({"results": results}), {}


def block_three_words(messages, **options):
    """Blocks terms ending in login, careers or free, triggered by that word; monitors the rest."""
    pairs = [(tid, unescape(term)) for tid, term in TAG.findall(messages[1]["content"])]
    results = [{"id": tid, "intent": "navigational",
                "label": "block" if term.split()[-1] in ("login", "careers", "free") else "monitor",
                "trigger": term.split()[-1], "reason": "Invented reason."} for tid, term in pairs]
    return json.dumps({"results": results}), {}


def challenge_careers(messages, **options):
    """Challenges the careers term, gives login a bad verdict (so it ends as error), agrees with the rest."""
    results = []
    for tid, term in TAG.findall(messages[1]["content"]):
        if "careers" in term:
            results.append({"id": tid, "verdict": "challenge", "proposed_label": "monitor", "reason": "Invented."})
        elif "login" in term:
            results.append({"id": tid, "verdict": "maybe", "proposed_label": "block", "reason": "Invented."})
        else:
            results.append({"id": tid, "verdict": "agree", "proposed_label": "block", "reason": "Invented."})
    return json.dumps({"results": results}), {}


class Screen(unittest.TestCase):
    def setUp(self):
        self.reviewed = []  # the terms sent to each review

        self.triage_call = monitor_everything
        self.checked = []  # the rows sent to each reviewer run

        def fake_triage_report(rows, context, progress=None):
            self.reviewed.append([r["Search term"] for r in rows])
            return REAL_TRIAGE_REPORT(rows, context, call=self.triage_call, progress=progress)

        def fake_review(rows, context, progress=None):
            self.checked.append(rows)
            return REAL_REVIEW(rows, context, call=challenge_careers, progress=progress)

        for target, fake in (("core.triage.triage_report", fake_triage_report), ("core.reviewer.review", fake_review)):
            patcher = mock.patch(target, fake)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.at = AppTest.from_file(str(APP / "main.py"), default_timeout=10).run()
        self.at.text_area(key="paste").input(TWO_CAMPAIGNS).run()

    def pick(self, campaign):
        self.at.selectbox(key="campaign_pick").select(campaign).run()

    def review(self):
        next(b for b in self.at.button if b.label == "Review terms").click().run()

    def counts(self):
        return next((c.value for c in self.at.caption if c.value.startswith("target:")), None)

    def notice(self):
        return any("review the terms again" in w.value for w in self.at.warning)

    def not_reviewed(self):
        return any(i.value == "Run the review to see the table." for i in self.at.info)

    def test_each_campaign_shows_only_its_own_review_and_keeps_its_edits(self):
        self.pick("Camp B")
        self.review()
        self.assertEqual(self.reviewed, [["zorbix card reader", "flarnet payment gateway"]])
        self.assertEqual(self.counts(), "target: 0  ·  block: 0  ·  monitor: 2  ·  error: 0")

        self.pick("Camp A")
        self.assertIsNone(self.counts())
        self.assertTrue(self.not_reviewed())
        self.assertFalse(self.notice())

        self.review()
        self.assertEqual(self.reviewed[-1], ["quillon pos system"])
        self.assertEqual(self.counts(), "target: 0  ·  block: 0  ·  monitor: 1  ·  error: 0")

        # A manual edit lands in the campaign's own table (what the editor's on_change writes)
        table = self.at.session_state["reviews"]["Camp B"]["table"]
        table.loc[table["Term"] == "flarnet payment gateway", "Decision"] = "block"
        self.pick("Camp B")
        self.assertEqual(self.counts(), "target: 0  ·  block: 1  ·  monitor: 1  ·  error: 0")
        self.pick("Camp A")
        self.assertEqual(self.counts(), "target: 0  ·  block: 0  ·  monitor: 1  ·  error: 0")
        self.assertEqual(len(self.reviewed), 2)

    def table(self):
        return self.at.session_state["reviews"]["Camp C"]["table"]

    def test_reviewer_columns_challenged_filter_and_caption(self):
        self.triage_call = block_three_words
        self.at.text_area(key="paste").input(THREE_BLOCKS).run()
        self.review()
        self.assertEqual(len(self.checked), 1)

        table = self.table()
        columns = list(table.columns)
        self.assertEqual(columns[columns.index("Reason") + 1:columns.index("Reason") + 3], ["Reviewer", "Reviewer note"])
        by_term = table.set_index("Term")
        self.assertEqual(by_term.loc["quillon careers", "Reviewer"], "challenge")
        self.assertEqual(by_term.loc["quillon careers", "Reviewer note"], "monitor: Invented.")
        self.assertEqual(by_term.loc["flarnet free", "Reviewer"], "agree")
        self.assertEqual(by_term.loc["zorbix login", "Reviewer"], "error")
        self.assertEqual(by_term.loc["vexmo reader", "Reviewer"], "")
        self.assertEqual(by_term.loc["vexmo reader", "Reviewer note"], "")

        run_caption = next(c.value for c in self.at.caption if "distinct terms" in c.value)
        self.assertIn("Reviewer: 2 model calls", run_caption)  # first call, then the retry of the bad verdict
        self.assertIn("1 challenges", run_caption)

        self.assertEqual(len(self.at.session_state["view_index"]), 4)
        self.at.checkbox(key="challenged_only").check().run()
        self.assertEqual([table.loc[i, "Term"] for i in self.at.session_state["view_index"]], ["quillon careers"])

    def test_changing_a_decision_does_not_rerun_the_reviewer(self):
        self.triage_call = block_three_words
        self.at.text_area(key="paste").input(THREE_BLOCKS).run()
        self.review()
        table = self.table()
        table.loc[table["Term"] == "quillon careers", "Decision"] = "monitor"
        self.at.run()
        self.assertEqual(len(self.checked), 1)
        self.assertEqual(self.table().set_index("Term").loc["quillon careers", "Reviewer"], "challenge")

    def test_review_again_notice_follows_each_campaigns_own_review(self):
        self.pick("Camp B")
        self.review()
        self.assertFalse(self.notice())

        profile = next(t for t in self.at.text_area if t.label == "Business profile")
        profile.input(profile.value + "\n- Invented extra line.").run()
        self.assertTrue(self.notice())
        self.assertEqual(self.counts(), "target: 0  ·  block: 0  ·  monitor: 2  ·  error: 0")

        self.pick("Camp A")
        self.assertFalse(self.notice())
        self.assertTrue(self.not_reviewed())

        self.pick("Camp B")
        self.assertTrue(self.notice())
        self.review()
        self.assertFalse(self.notice())


class DecisionEdits(unittest.TestCase):
    """The mapping apply_edits uses, tested directly: an edit by view position lands on its full-table row."""

    def test_filtered_view_edit_changes_the_right_row_and_no_other(self):
        table = pd.DataFrame({
            "Term": ["zorbix login", "quillon reader", "flarnet careers", "vexmo free", "trellan fees"],
            "Decision": ["block", "target", "block", "block", "monitor"],
            "Reviewer": ["agree", "", "challenge", "challenge", ""],
        }, index=[10, 11, 12, 13, 14])
        # The screen's filters: decision block only, and "Challenged only"
        view = table[table["Decision"].isin(["block"])]
        view = view[view["Reviewer"] == "challenge"]
        view_index = list(view.index)
        self.assertEqual(view_index, [12, 13])

        updated = apply_decision_edits(table, view_index, {1: {"Decision": "monitor"}})
        expected = table.copy()
        expected.loc[13, "Decision"] = "monitor"  # view row 1 is full-table row 13, the fourth row
        pd.testing.assert_frame_equal(updated, expected)
        self.assertEqual(table.loc[13, "Decision"], "block")  # the input is not changed in place

    def test_edits_to_other_columns_are_ignored(self):
        table = pd.DataFrame({"Term": ["zorbix login"], "Decision": ["block"]}, index=[5])
        updated = apply_decision_edits(table, [5], {0: {"Term": "invented"}})
        pd.testing.assert_frame_equal(updated, table)


if __name__ == "__main__":
    unittest.main()
