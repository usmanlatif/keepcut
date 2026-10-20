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
import streamlit as st
from streamlit.elements.progress import ProgressMixin
from streamlit.proto.WidgetStates_pb2 import WidgetState
from streamlit.testing.v1 import AppTest

APP = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(APP))

import core.reviewer  # noqa: E402
import core.summary  # noqa: E402
import core.triage  # noqa: E402
from core import dashboard, exports  # noqa: E402
from core.edits import apply_decision_edits  # noqa: E402

TAG = re.compile(r'<term id="([^"]+)">(.*?)</term>')
REAL_TRIAGE_REPORT = core.triage.triage_report
REAL_REVIEW = core.reviewer.review
REAL_WRITE_SUMMARY = core.summary.write_summary
REAL_ST_PROGRESS = st.progress
PROFILE = "# Zorbix Widgets (invented)\n\n- What it sells: invented widgets."

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
        self.at.text_area(key="profile").input(PROFILE).run()
        self.at.text_area(key="paste").input(TWO_CAMPAIGNS).run()

    def pick(self, campaign):
        self.at.selectbox(key="campaign_pick").select(campaign).run()

    def review(self):
        next(b for b in self.at.button if b.label == "Review terms").click().run()

    def counts(self):
        """The four decision cards in step 4, as "target: 0  ·  block: 0  ·  ..."; None when they are not shown."""
        cards = {m.label: m.value for m in self.at.metric if m.label in ("Target", "Block", "Monitor", "Error")}
        return "  ·  ".join(f"{d.lower()}: {cards[d]}" for d in ("Target", "Block", "Monitor", "Error")) if cards else None

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

        run_cards = {m.label: m.value for m in self.at.metric}
        self.assertEqual(run_cards["Reviewer calls"], "2")  # first call, then the retry of the bad verdict
        self.assertEqual(run_cards["Challenges"], "1")

        self.assertEqual(len(self.at.session_state["view_index"]), 4)
        self.at.checkbox(key="challenged_only").check().run()
        self.assertEqual([table.loc[i, "Term"] for i in self.at.session_state["view_index"]], ["quillon careers"])

    def test_an_edit_in_the_capitalized_decision_column_stores_lowercase(self):
        self.triage_call = block_three_words
        self.at.text_area(key="paste").input(THREE_BLOCKS).run()
        self.review()
        editor = next(d for d in self.at.dataframe if "editor_Camp C_" in d.proto.id)
        self.assertEqual(list(editor.value["Decision"]), ["Block", "Block", "Block", "Monitor"])  # shown capitalized
        # What the browser sends when the reviewer picks "Monitor" for view row 1 (quillon careers)
        edit = WidgetState(id=editor.proto.id, string_value=json.dumps(
            {"edited_rows": {"1": {"Decision": "Monitor"}}, "added_rows": [], "deleted_rows": []}))
        states = self.at._tree.get_widget_states()
        states.widgets.append(edit)
        self.at._run(states)
        by_term = self.table().set_index("Term")
        self.assertEqual(by_term.loc["quillon careers", "Decision"], "monitor")
        self.assertEqual(by_term.loc["zorbix login", "Decision"], "block")
        self.assertEqual(self.counts(), "target: 0  ·  block: 2  ·  monitor: 2  ·  error: 0")

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

        profile = self.at.text_area(key="profile")
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


def button(at, label):
    return next((b for b in at.button if b.label == label), None)


def steps(at):
    """The two setup steps' expanders, by key: (label, open)."""
    return {e.proto.id.rsplit("-", 2)[-2] + "-" + e.proto.id.rsplit("-", 1)[-1]: (e.label, e.proto.expanded)
            for e in at.expander if e.proto.id.endswith(("-step-1", "-step-2"))}


class EmptyStartAndDemo(unittest.TestCase):
    """The screen before anything is entered, and the one-click demo. No model is reached."""

    def setUp(self):
        self.reviewed = []

        def fake_triage_report(rows, context, progress=None):
            self.reviewed.append(rows)
            return REAL_TRIAGE_REPORT(rows, context, call=block_three_words, progress=progress)

        def fake_review(rows, context, progress=None):
            return REAL_REVIEW(rows, context, call=challenge_careers, progress=progress)

        self.progress_texts = []
        real_progress = ProgressMixin.progress

        def record_progress(dg, value, text=None, **options):
            self.progress_texts.append(text)
            return real_progress(dg, value, text=text, **options)

        def record_new_bar(value, text=None, **options):
            self.progress_texts.append(text)
            return REAL_ST_PROGRESS(value, text=text, **options)

        for target, fake in (("core.triage.triage_report", fake_triage_report), ("core.reviewer.review", fake_review),
                             ("streamlit.elements.progress.ProgressMixin.progress", record_progress),
                             ("streamlit.progress", record_new_bar)):
            patcher = mock.patch(target, fake)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.at = AppTest.from_file(str(APP / "main.py"), default_timeout=10).run()

    def review_disabled(self):
        return button(self.at, "Review terms").disabled

    def model_sees(self):
        return [c.value for c in self.at.code]

    def test_first_load_is_empty(self):
        profile = self.at.text_area(key="profile")
        self.assertEqual(profile.value, "")
        self.assertTrue(profile.placeholder.startswith("What you sell"))
        self.assertIsNone(self.at.session_state["raw"])
        self.assertEqual(len(self.at.selectbox), 0)
        self.assertEqual(self.model_sees(), [])
        self.assertTrue(any(c.value == "Nothing yet. Write a business profile first." for c in self.at.caption))
        self.assertTrue(self.review_disabled())
        self.assertEqual(len(self.at.text_input), 0)  # no Campaign field in step 1
        self.assertIsNone(button(self.at, "Load demo report"))
        self.assertEqual({k: v[1] for k, v in steps(self.at).items()}, {"step-1": True, "step-2": True})

    def test_review_needs_a_profile_and_a_chosen_campaign(self):
        self.at.text_area(key="paste").input(TWO_CAMPAIGNS).run()
        self.at.selectbox(key="campaign_pick").select("Camp B").run()
        self.assertTrue(self.review_disabled())  # campaign, no profile
        self.assertEqual(self.model_sees(), [])

        self.at.text_area(key="profile").input(PROFILE).run()
        self.assertFalse(self.review_disabled())
        [context] = self.model_sees()
        self.assertIn("Every decision is for this campaign only: Camp B", context)

        self.at.text_area(key="paste").input(THREE_BLOCKS.replace("Camp C", "Camp D") + TWO_CAMPAIGNS[60:]).run()
        self.assertIsNone(self.at.selectbox(key="campaign_pick").value)
        self.assertTrue(self.review_disabled())  # profile, no campaign chosen

    def test_demo_button_fills_profile_loads_small_report_and_picks_campaign(self):
        button(self.at, "Load demo: Plover Payments").click().run()
        self.assertEqual(self.at.text_area(key="profile").value,
                         (APP / "data" / "business_profile.md").read_text(encoding="utf-8"))
        self.assertIsNone(self.at.session_state["raw"])  # the profile only; the report is offered in step 2
        button(self.at, "Use demo file").click().run()
        self.assertEqual(self.at.session_state["raw"],
                         (APP / "data" / "demo" / "search_terms_demo_small.csv").read_bytes())
        self.assertEqual(self.at.selectbox(key="campaign_pick").value, "Plover Generic Search")
        self.assertEqual(self.reviewed, [])  # the review does not start
        self.assertFalse(self.review_disabled())
        [context] = self.model_sees()
        self.assertIn("Every decision is for this campaign only: Plover Generic Search", context)

    def test_demo_report_buttons_appear_only_after_the_demo_button(self):
        self.assertIsNone(button(self.at, "Use demo file"))
        self.assertIsNone(button(self.at, "Paste demo export"))
        button(self.at, "Load demo: Plover Payments").click().run()
        self.assertEqual(steps(self.at)["step-2"], ("**2. Report**", True))  # step 2 stays open for the report
        self.assertIsNotNone(button(self.at, "Use demo file"))
        self.assertIsNotNone(button(self.at, "Paste demo export"))

    def test_use_demo_file_loads_it_as_an_upload(self):
        button(self.at, "Load demo: Plover Payments").click().run()
        button(self.at, "Use demo file").click().run()
        self.assertEqual(self.at.session_state["source"], "search_terms_demo_small.csv")
        self.assertEqual(self.at.text_area(key="paste").value, "")
        self.assertEqual(self.at.selectbox(key="campaign_pick").value, "Plover Generic Search")
        self.assertTrue(any(c.value.startswith("Source: search_terms_demo_small.csv.") for c in self.at.caption))

    def test_paste_demo_export_fills_the_paste_box_and_loads_it_as_pasted_text(self):
        demo = (APP / "data" / "demo" / "search_terms_demo_small.csv").read_text(encoding="utf-8")
        button(self.at, "Load demo: Plover Payments").click().run()
        button(self.at, "Paste demo export").click().run()
        self.assertEqual(self.at.text_area(key="paste").value, demo)
        self.assertEqual(self.at.session_state["raw"], demo)
        self.assertEqual(self.at.session_state["source"], "pasted text")
        self.assertEqual(self.at.selectbox(key="campaign_pick").value, "Plover Generic Search")
        self.assertEqual(self.reviewed, [])
        self.assertFalse(self.review_disabled())

    def test_complete_steps_collapse_with_a_summary_and_reopen_on_click(self):
        button(self.at, "Load demo: Plover Payments").click().run()
        button(self.at, "Use demo file").click().run()
        self.assertEqual(steps(self.at), {
            "step-1": ("**1. Account** Plover Payments profile", False),
            "step-2": ("**2. Report** 80 terms, Plover Generic Search, Aug to Sep 2026", False),
        })
        # A click on the label opens the step (what the browser sends), and it stays open on the next run
        self.at.session_state["step-1"] = True
        self.at.session_state["open"]["step-1"] = True
        self.at.run()
        self.assertTrue(steps(self.at)["step-1"][1])
        self.assertFalse(steps(self.at)["step-2"][1])

        # Emptying the profile makes step 1 incomplete again: it stays open and loses its summary
        self.at.text_area(key="profile").input("").run()
        self.assertEqual(steps(self.at)["step-1"], ("**1. Account**", True))
        self.assertTrue(self.review_disabled())

    def test_progress_text_counts_calls_and_terms(self):
        text = "Search term,Campaign,Ad group,Clicks,Impr.,Cost,Conversions\n" + "".join(
            f"zorbix{i} {'login' if i < 3 else 'reader'},Camp E,Group 1,1,10,1.00,0\n" for i in range(25))
        self.at.text_area(key="profile").input(PROFILE).run()
        self.at.text_area(key="paste").input(text).run()
        button(self.at, "Review terms").click().run()
        self.assertEqual(self.progress_texts, [
            "Triage: 0 of 2 calls done, 25 terms",
            "Triage: 1 of 2 calls done, 25 terms",
            "Triage: 2 of 2 calls done, 25 terms",
            "Reviewer: 0 of 1 calls done, 3 blocks to check",
            "Reviewer: 1 of 1 calls done, 3 blocks to check",
        ])


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

    def test_an_edit_applies_to_every_row_of_the_term(self):
        table = pd.DataFrame({
            "Month": ["August 2026", "September 2026", "September 2026"],
            "Term": ["quillon reader", "quillon reader", "vexmo hub"],
            "Ad group": ["Group 1", "Group 1", "Group 2"],
            "Decision": ["target", "target", "monitor"],
            "Cost": [4.10, 2.35, 1.05],
        }, index=[20, 21, 22])
        # A filtered view that shows only September's row of the term
        view = table[table["Month"] == "September 2026"]
        view = view[view["Decision"] == "target"]
        self.assertEqual(list(view.index), [21])

        updated = apply_decision_edits(table, list(view.index), {0: {"Decision": "block"}})
        self.assertEqual(list(updated["Decision"]), ["block", "block", "monitor"])
        self.assertEqual(list(exports.negatives(updated, "Camp X")["Keyword"]), ["quillon reader"])
        self.assertEqual(len(exports.new_keywords(updated, "Camp X")), 0)
        expected = round(float(updated["Cost"].sum()), 2)
        for frame in (dashboard.spend_by_decision(updated), dashboard.spend_by_ad_group(updated)):
            self.assertEqual(round(float(frame["Cost"].sum()), 2), expected)
        for grid in (dashboard.month_by_decision(updated), dashboard.intent_by_decision(
                updated.assign(**{"Intent stage": "commercial"}))):
            self.assertEqual(round(float(grid.to_numpy().sum()), 2), expected)

    def test_an_edit_reaches_spellings_triage_counts_as_one_term(self):
        table = pd.DataFrame({"Term": ["zorbix straße", "Zorbix Strasse ", "zorbix strase"],
                              "Decision": ["target", "target", "target"]})
        updated = apply_decision_edits(table, [0, 1, 2], {0: {"Decision": "block"}})
        self.assertEqual(list(updated["Decision"]), ["block", "block", "target"])

    def test_edits_to_other_columns_are_ignored(self):
        table = pd.DataFrame({"Term": ["zorbix login"], "Decision": ["block"]}, index=[5])
        updated = apply_decision_edits(table, [5], {0: {"Term": "invented"}})
        pd.testing.assert_frame_equal(updated, table)


TWO_MONTHS = (
    "Month,Search term,Campaign,Ad group,Clicks,Impr.,Cost,Conversions\n"
    "August 2026,zorbix card reader,Camp M,Group 1,1,10,2.00,0\n"
    "September 2026,zorbix card reader,Camp M,Group 1,2,20,3.50,0\n"
    "September 2026,quillon pos system,Camp M,Group 2,3,30,4.25,1\n"
)


class DashboardAndApprove(unittest.TestCase):
    """Steps 5 and 6 on the screen, with every term answered as monitor by a fake triage call."""

    def setUp(self):
        def fake_triage_report(rows, context, progress=None):
            return REAL_TRIAGE_REPORT(rows, context, call=monitor_everything, progress=progress)

        def fake_review(rows, context, progress=None):
            return REAL_REVIEW(rows, context, call=challenge_careers, progress=progress)

        self.summary_replies = []  # what the fake summary call answers, in order; empty means a valid summary
        self.summary_figures = []

        def fake_summary_call(messages, **options):
            self.summary_figures.append(messages[1]["content"])
            if self.summary_replies:
                return self.summary_replies.pop(0), {}
            return json.dumps({"summary": "One. Two. Three. Four.", "recommendations": ["Invented."]}), {}

        def fake_write_summary(figures, context):
            return REAL_WRITE_SUMMARY(figures, context, call=fake_summary_call)

        for target, fake in (("core.triage.triage_report", fake_triage_report), ("core.reviewer.review", fake_review),
                             ("core.summary.write_summary", fake_write_summary)):
            patcher = mock.patch(target, fake)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.at = AppTest.from_file(str(APP / "main.py"), default_timeout=10).run()
        self.at.text_area(key="profile").input(PROFILE).run()
        self.at.text_area(key="paste").input(TWO_MONTHS).run()
        next(b for b in self.at.button if b.label == "Review terms").click().run()

    def table(self):
        return self.at.session_state["reviews"]["Camp M"]["table"]

    def metric(self, label):
        return next(m.value for m in self.at.metric if m.label == label)

    def downloads(self):
        return [d.proto.label for d in self.at.get("download_button")]

    def approve(self):
        next(b for b in self.at.button if b.label == "Approve and build outputs").click().run()

    def test_month_is_kept_and_the_tiles_follow_a_changed_decision(self):
        self.assertEqual(list(self.table().columns)[0], "Month")
        self.assertEqual(self.metric("Total spend"), "9.75")
        self.assertEqual(self.metric("Spend on blocked terms"), "0.00")
        self.assertEqual(self.metric("New keywords found"), "0")
        self.assertTrue(any(s.value == "Month over month spend by decision" for s in self.at.subheader))

        table = self.table()
        table.loc[table["Term"] == "zorbix card reader", "Decision"] = "block"
        table.loc[table["Term"] == "quillon pos system", "Decision"] = "target"
        self.at.run()
        self.assertEqual(self.metric("Spend on blocked terms"), "5.50")
        self.assertEqual(self.metric("New keywords found"), "1")

    def test_no_month_column_means_no_month_chart(self):
        self.at.text_area(key="paste").input(TWO_CAMPAIGNS).run()
        self.at.selectbox(key="campaign_pick").select("Camp B").run()
        next(b for b in self.at.button if b.label == "Review terms").click().run()
        self.assertNotIn("Month", self.at.session_state["reviews"]["Camp B"]["table"].columns)
        self.assertFalse(any(s.value == "Month over month spend by decision" for s in self.at.subheader))

    def test_a_conflict_is_listed_under_the_approve_button(self):
        def listed():
            return [d.value for d in self.at.dataframe if list(d.value.columns) == exports.CONFLICT_COLUMNS]

        self.assertEqual(listed(), [])
        table = self.table()
        table.loc[table["Term"] == "quillon pos system", ["Term", "Decision"]] = ['"zorbix card reader"', "block"]
        self.at.run()
        self.approve()
        [conflict] = listed()
        self.assertEqual(list(conflict["Search term"]), ["zorbix card reader", '"zorbix card reader"'])
        self.assertEqual(list(conflict["Decision"]), ["monitor", "block"])
        self.assertTrue(any("left out of the negatives" in w.value for w in self.at.warning))
        self.assertEqual(self.downloads(), ["Negatives (0 rows)", "New keywords (0 rows)", "Watchlist (1 rows)"])

    def test_summary_and_its_figures_appear_under_the_downloads_after_approval(self):
        self.assertFalse(any(s.value == "Weekly summary" for s in self.at.subheader))
        self.approve()
        self.assertTrue(any(s.value == "Weekly summary" for s in self.at.subheader))
        self.assertTrue(any(m.value == "One. Two. Three. Four." for m in self.at.markdown))
        self.assertEqual(len(self.summary_figures), 1)
        self.assertIn('"total_spend": "9.75"', self.summary_figures[0])
        self.assertTrue(any(e.label == "Figures the summary was written from" for e in self.at.expander))
        self.assertEqual(json.loads(self.at.json[0].proto.body)["total_spend"], "9.75")

    def test_a_bad_summary_is_retried_once_then_shown_as_an_error(self):
        self.summary_replies = ["not json", "still not json"]
        self.approve()
        self.assertEqual(len(self.summary_figures), 2)
        self.assertTrue(any("No valid summary after one retry" in e.value for e in self.at.error))
        self.assertFalse(any(m.value == "One. Two. Three. Four." for m in self.at.markdown))
        self.assertEqual(len(self.downloads()), 3)

    def test_downloads_appear_on_approval_and_hide_after_a_change(self):
        self.assertEqual(self.downloads(), [])
        self.approve()
        self.assertEqual(self.downloads(), ["Negatives (0 rows)", "New keywords (0 rows)", "Watchlist (2 rows)"])

        table = self.table()
        table.loc[table["Term"] == "zorbix card reader", "Decision"] = "block"
        self.at.run()
        self.assertEqual(self.downloads(), [])
        self.assertTrue(any("Approve again" in w.value for w in self.at.warning))

        self.approve()
        self.assertEqual(self.downloads(), ["Negatives (1 rows)", "New keywords (0 rows)", "Watchlist (1 rows)"])


if __name__ == "__main__":
    unittest.main()
