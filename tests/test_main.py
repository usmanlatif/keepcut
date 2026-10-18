"""Tests for the screen in app/main.py with Streamlit's AppTest. Triage runs its real code with a fake model call,
so no model is reached. Terms are invented words, never golden-set terms."""
import json
import re
import sys
import unittest
from html import unescape
from pathlib import Path
from unittest import mock

from streamlit.testing.v1 import AppTest

APP = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(APP))

import core.triage  # noqa: E402

TAG = re.compile(r'<term id="([^"]+)">(.*?)</term>')
REAL_TRIAGE_REPORT = core.triage.triage_report

TWO_CAMPAIGNS = (
    "Search term,Campaign,Ad group,Clicks,Impr.,Cost,Conversions\n"
    "zorbix card reader,Camp B,Group 1,1,10,2.00,0\n"
    "quillon pos system,Camp A,Group 2,2,20,3.00,1\n"
    "flarnet payment gateway,Camp B,Group 1,3,30,4.00,0\n"
)


def monitor_everything(messages, **options):
    """Answers every term as monitor, triggered by its first word."""
    pairs = [(tid, unescape(term)) for tid, term in TAG.findall(messages[1]["content"])]
    results = [{"id": tid, "intent": "commercial", "label": "monitor", "trigger": term.split()[0],
                "reason": "Invented reason."} for tid, term in pairs]
    return json.dumps({"results": results}), {}


class Screen(unittest.TestCase):
    def setUp(self):
        self.reviewed = []  # the terms sent to each review

        def fake_triage_report(rows, context, progress=None):
            self.reviewed.append([r["Search term"] for r in rows])
            return REAL_TRIAGE_REPORT(rows, context, call=monitor_everything, progress=progress)

        patcher = mock.patch("core.triage.triage_report", fake_triage_report)
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


if __name__ == "__main__":
    unittest.main()
