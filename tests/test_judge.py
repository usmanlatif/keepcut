"""Tests for evaluation/judge_summary.py with a fake call. The fixture is invented; terms are made-up words."""
import csv
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from evaluation import judge_summary  # noqa: E402

CONTEXT = "# Business profile\n\nZorbix sells widgets.\n"
FIGS = json.dumps({"total_spend": "1,234.56", "new_keywords": {"count": "3"}})
NOTE = "SENTINEL-NOTE-qwv"
# id, the verdict the fake judge gives (read from the summary), Usman's label.
# Usman PASS: judge PASS, PASS, UNKNOWN -> TPR 2 of 3. Usman FAIL: judge FAIL, UNKNOWN, PASS -> TNR 1 of 3.
FIXTURE = [("1", "PASS", "PASS"), ("2", "PASS", "PASS"), ("3", "UNKNOWN", "PASS"),
           ("4", "FAIL", "FAIL"), ("5", "BROKEN", "FAIL"), ("6", "PASS", "FAIL")]
FIELDS = ("id", "variant", "figures", "summary", "recommendations", "figure_check", "usman_label", "usman_note")


def fixture_rows():
    return [{"id": i, "variant": f"variant {i}", "figures": FIGS, "summary": f"Spend was 1,234.56. JUDGE={verdict}.",
             "recommendations": "Add the zorbix keyword.", "figure_check": "pass", "usman_label": label,
             "usman_note": NOTE} for i, verdict, label in FIXTURE]


def write_fixture(directory: Path, rows, name="2026-10-19-summary-labels.csv") -> Path:
    path = directory / name
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return path


def reply(verdict, supported=True):
    return json.dumps({"evidence": [{"quote": "Spend was 1,234.56.", "figure": "total_spend: 1,234.56",
                                     "supported": supported}], "verdict": verdict})


class FakeJudge:
    """llm.complete's signature. Answers with the verdict planted in the summary; BROKEN replies are never valid."""

    def __init__(self):
        self.messages = []

    def __call__(self, messages, **options):
        self.messages.append(messages)
        user = messages[1]["content"]
        verdict = user.split("JUDGE=")[1].split(".")[0]
        if verdict == "BROKEN":
            return "not json", {"prompt": 10, "completion": 2}
        if verdict == "UNKNOWN":
            return json.dumps({"evidence": [], "verdict": "UNKNOWN"}), {"prompt": 10, "completion": 2}
        return reply(verdict, supported=verdict == "PASS"), {"prompt": 10, "completion": 2}


class MetricTests(unittest.TestCase):
    def setUp(self):
        self.fake = FakeJudge()
        self.rows, self.counter, _ = judge_summary.run_judge(fixture_rows(), CONTEXT, call=self.fake)

    def test_tpr_and_tnr_by_hand(self):
        m = judge_summary.metrics(self.rows)
        # Usman PASS rows 1, 2, 3: judge PASS on 1 and 2, UNKNOWN on 3.
        self.assertEqual((m["tpr"]["hits"], m["tpr"]["total"]), (2, 3))
        self.assertAlmostEqual(m["tpr"]["rate"], 2 / 3)
        # Usman FAIL rows 4, 5, 6: judge FAIL on 4, UNKNOWN on 5 (two broken replies), PASS on 6.
        self.assertEqual((m["tnr"]["hits"], m["tnr"]["total"]), (1, 3))
        self.assertAlmostEqual(m["tnr"]["rate"], 1 / 3)

    def test_unknown_counts_as_wrong_and_is_reported_alone(self):
        m = judge_summary.metrics(self.rows)
        self.assertEqual((m["tpr"]["unknown"], m["tnr"]["unknown"], m["unknown"]), (1, 1, 2))
        by_id = {r["id"]: r for r in self.rows}
        self.assertEqual((by_id["3"]["agree"], by_id["5"]["agree"]), ("no", "no"))

    def test_invalid_reply_is_retried_once_then_unknown(self):
        row5 = next(r for r in self.rows if r["id"] == "5")
        self.assertEqual(row5["verdict"], "UNKNOWN")
        self.assertIn("after one retry", row5["error"])
        self.assertEqual(self.counter.calls, 7)  # six rows, one retry for row 5

    def test_empty_class_is_na(self):
        only_pass = [r for r in self.rows if r["usman_label"] == "PASS"]
        m = judge_summary.metrics(only_pass)
        self.assertIsNone(m["tnr"]["rate"])
        self.assertEqual(judge_summary.shown(m["tnr"]), "n/a")
        self.assertEqual(judge_summary.shown(m["tpr"]), "0.67")

    def test_calls_use_temperature_zero_and_json_mode(self):
        self.assertEqual(judge_summary.OPTIONS, {"temperature": 0, "response_format": {"type": "json_object"}})


class LabelLeakTests(unittest.TestCase):
    def test_human_label_and_note_never_reach_the_prompt(self):
        fake = FakeJudge()
        judge_summary.run_judge(fixture_rows(), CONTEXT, call=fake)
        sent = json.dumps(fake.messages)
        self.assertNotIn(NOTE, sent)
        self.assertNotIn("usman", sent.lower())
        # Flipping the label leaves the messages unchanged, so the label cannot be in them.
        row = fixture_rows()[0]
        flipped = {**row, "usman_label": "FAIL", "usman_note": "other"}
        self.assertEqual(judge_summary.judge_messages(row, CONTEXT), judge_summary.judge_messages(flipped, CONTEXT))

    def test_context_figures_summary_and_recommendations_reach_the_prompt(self):
        system, user = judge_summary.judge_messages(fixture_rows()[0], CONTEXT)
        self.assertIn("Zorbix sells widgets.", system["content"])
        self.assertNotIn("{context}", system["content"])
        for text in ("1,234.56", "JUDGE=PASS", "Add the zorbix keyword."):
            self.assertIn(text, user["content"])


class RefusalTests(unittest.TestCase):
    def test_missing_label_refuses(self):
        rows = fixture_rows()
        rows[2]["usman_label"] = ""
        with tempfile.TemporaryDirectory() as tmp:
            path = write_fixture(Path(tmp), rows)
            with self.assertRaisesRegex(ValueError, "id 3"):
                judge_summary.load_labels(path)

    def test_label_outside_pass_fail_refuses(self):
        rows = fixture_rows()
        rows[0]["usman_label"] = "maybe"
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "id 1"):
                judge_summary.load_labels(write_fixture(Path(tmp), rows))

    def test_main_refuses_before_any_call(self):
        rows = fixture_rows()
        rows[4]["usman_label"] = ""
        with tempfile.TemporaryDirectory() as tmp:
            path = write_fixture(Path(tmp), rows)
            with mock.patch.object(judge_summary, "newest_labels", return_value=path), \
                    mock.patch.object(judge_summary, "run_judge") as run:
                self.assertEqual(judge_summary.main([]), 2)
        run.assert_not_called()


class ContractTests(unittest.TestCase):
    def test_verdict_must_follow_evidence(self):
        self.assertIsNone(judge_summary.check(reply("PASS", supported=False))[0])
        self.assertIsNone(judge_summary.check(reply("FAIL", supported=True))[0])
        self.assertIsNone(judge_summary.check(json.dumps({"evidence": [], "verdict": "PASS"}))[0])
        self.assertIsNotNone(judge_summary.check(json.dumps({"evidence": [], "verdict": "UNKNOWN"}))[0])
        self.assertIsNone(judge_summary.check(json.dumps({"evidence": [], "verdict": "MAYBE"}))[0])


class FileTests(unittest.TestCase):
    def test_newest_labels_reads_date_then_suffix(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            for name in ("2026-10-18-summary-labels.csv", "2026-10-19-summary-labels.csv",
                         "2026-10-19-2-summary-labels.csv", "2026-10-19-summary-check.md"):
                (d / name).write_text("", encoding="utf-8")
            self.assertEqual(judge_summary.newest_labels(d).name, "2026-10-19-2-summary-labels.csv")

    def test_results_never_overwrite_and_carry_the_record(self):
        fake = FakeJudge()
        rows, counter, seconds = judge_summary.run_judge(fixture_rows(), CONTEXT, call=fake)
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            args = (rows, counter, seconds, "abc123", True, "2026-10-20", "labels.csv", "p" * 64, "r" * 64, "l" * 64)
            first = judge_summary.write_results(*args, directory=d)
            second = judge_summary.write_results(*args, directory=d)
            self.assertEqual([p.name for p in first], ["2026-10-20-judge.md", "2026-10-20-judge.csv"])
            self.assertEqual([p.name for p in second], ["2026-10-20-2-judge.md", "2026-10-20-2-judge.csv"])
            md = first[0].read_text(encoding="utf-8")
            for text in ("`abc123`", "dirty: yes", "p" * 64, "l" * 64, "| 0.67 | 2 of 3 | 1 |",
                         f"Judge runner: `evaluation/judge_summary.py`, SHA-256 `{'r' * 64}`.",
                         "| 0.33 | 1 of 3 | 1 |", "UNKNOWN verdicts: 2 of 6."):
                self.assertIn(text, md)
            with first[1].open(encoding="utf-8", newline="") as handle:
                saved = list(csv.DictReader(handle))
            self.assertEqual([(r["verdict"], r["usman_label"]) for r in saved],
                             [("PASS", "PASS"), ("PASS", "PASS"), ("UNKNOWN", "PASS"),
                              ("FAIL", "FAIL"), ("UNKNOWN", "FAIL"), ("PASS", "FAIL")])
            self.assertTrue(json.loads(saved[0]["evidence"])[0]["supported"])


class IdentityTests(unittest.TestCase):
    def test_uncommitted_change_to_the_runner_sets_dirty(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            git = lambda *a: subprocess.run(["git", *a], cwd=root, check=True, capture_output=True)
            git("init", "-q")
            for name in ("app/main.py", "evaluation/judge_prompt.md", "evaluation/judge_summary.py"):
                (root / name).parent.mkdir(parents=True, exist_ok=True)
                (root / name).write_text("x\n", encoding="utf-8")
            git("add", ".")
            git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "base")
            self.assertFalse(judge_summary.dirty(root))
            (root / "evaluation/judge_summary.py").write_text("changed rate formula\n", encoding="utf-8")
            self.assertTrue(judge_summary.dirty(root))

    def test_runner_hash_is_this_file(self):
        self.assertEqual(judge_summary.RUNNER, ROOT / "evaluation" / "judge_summary.py")


if __name__ == "__main__":
    unittest.main()
