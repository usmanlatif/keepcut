"""M2 scorer checks with invented terms only; never open the protected golden set."""
import csv
import hashlib
import io
import json
import re
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from copy import deepcopy
from html import unescape
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from evaluation import score  # noqa: E402

# Six invented terms, two examples of each decision. No production data is read.
FIXTURE = [
    {"id": str(i), "search_term": term, "label": label, "trigger": term.split()[0],
     "labeled_by": "fixture", "date": "2026-01-01", "note": ""}
    for i, (term, label) in enumerate([
        ("zorbix wand", "target"), ("quillon prism", "target"),
        ("flarnet hatch", "block"), ("glimvox spool", "block"),
        ("plimzor orb", "monitor"), ("nuvvix lens", "monitor"),
    ], 1)
]
PREDICTIONS = [
    ["target", "block", "block", "error", "monitor", "target"],
    ["target", "block", "block", "block", "monitor", "monitor"],
    ["target", "block", "block", "block", "target", "monitor"],
]
SOURCE_NAMES = ("app/prompts/triage.md", "app/data/labels.md", "app/data/business_profile.md",
                "app/core/triage.py", "app/core/context.py", "app/core/llm.py",
                "evaluation/score.py", "evaluation/golden_set.csv")
METADATA = {"dirty": True, "model": "invented-model", "sha256": {name: "1" * 64 for name in SOURCE_NAMES}}


class FakeTriage:
    def __init__(self, predictions=PREDICTIONS):
        self.predictions = iter(predictions)
        self.requests = []

    def __call__(self, terms, context):
        self.requests.append((terms[:], context))
        labels = next(self.predictions)
        rows = [{"id": f"t{i}", "term": term,
                 "intent": "" if label == "error" else "commercial", "label": label,
                 "trigger": "" if label == "error" else (f"  {term.upper()}  " if i == 1 else term.split()[0]),
                 "reason": "Invented reason."}
                for i, (term, label) in enumerate(zip(terms, labels), 1)]
        return SimpleNamespace(rows=rows, prompt_tokens=100, completion_tokens=25,
                               seconds=1.5, calls=2, errors=["synthetic diagnostic"])


def fake_runs(predictions=PREDICTIONS, fixture=FIXTURE):
    return score.evaluate(fixture, "Invented context", triage_fn=FakeTriage(predictions))


class Scoring(unittest.TestCase):
    def test_confusion_and_precision_recall_by_hand(self):
        fake = FakeTriage()
        runs = score.evaluate(FIXTURE, "Invented context", triage_fn=fake)
        self.assertEqual(len(fake.requests), 3)
        self.assertEqual(fake.requests, [([r["search_term"] for r in FIXTURE], "Invented context")] * 3)
        run = runs[0]
        self.assertEqual(run["matrix"], {
            "target": {"target": 1, "block": 1, "monitor": 0, "error": 0},
            "block": {"target": 0, "block": 1, "monitor": 0, "error": 1},
            "monitor": {"target": 1, "block": 0, "monitor": 1, "error": 0},
        })
        # P: target=1/2, block=1/2, monitor=1/1. R: each=1/2.
        # The block error is a false negative; it cannot disappear from recall.
        m = run["metrics"]
        for label, precision in (("target", 1/2), ("block", 1/2), ("monitor", 1)):
            self.assertEqual(m[f"{label} precision"], precision)
            self.assertEqual(m[f"{label} recall"], 1/2)
        self.assertAlmostEqual(m["macro precision"], 2/3)
        self.assertEqual(m["macro recall"], 1/2)
        self.assertEqual(m["monitor share"], 1/6)
        self.assertEqual(m["whole-term triggers"], 1)
        self.assertEqual(m["intent commercial share"], 5/6)
        self.assertEqual(m["intent missing share"], 1/6)
        self.assertEqual({key: m[key] for key in ("errors", "calls", "prompt tokens", "completion tokens", "total tokens", "seconds")},
                         {"errors": 1, "calls": 2, "prompt tokens": 100, "completion tokens": 25, "total tokens": 125, "seconds": 1.5})
        self.assertEqual([r["id"] for r in run["rows"]], [r["id"] for r in FIXTURE])

    def test_never_predicted_class_is_na_not_zero(self):
        labels = ["target", "block", "block", "error", "block", "target"]
        runs = fake_runs([labels] * 3)
        m = runs[0]["metrics"]
        self.assertIsNone(m["monitor precision"])
        self.assertEqual(m["monitor recall"], 0)
        self.assertIsNone(m["macro precision"])
        self.assertEqual(score.format_metric("monitor precision", m["monitor precision"]), "n/a")
        self.assertIsNone(score.aggregate(runs)["metrics"]["macro precision"]["mean"])

    def test_means_ranges_consistency_and_pass3_by_hand(self):
        runs = fake_runs()
        summary = score.aggregate(runs)
        # Block P = 1/2, 2/3, 2/3. Block R = 1/2, 1, 1.
        self.assertEqual(summary["metrics"]["block precision"]["min"], 1/2)
        self.assertEqual(summary["metrics"]["block precision"]["max"], 2/3)
        self.assertAlmostEqual(summary["metrics"]["block precision"]["mean"], 11/18)
        self.assertAlmostEqual(summary["metrics"]["block recall"]["mean"], 5/6)
        self.assertAlmostEqual(summary["metrics"]["monitor share"]["mean"], 2/9)
        # ids 1,2,3 are consistent, but id 2 is consistently wrong.
        self.assertEqual(summary["consistency"], 3/6)
        self.assertEqual(summary["pass3"], 2/6)
        line = score.one_line("fake-v1", summary, runs, dirty=True)
        self.assertIn("fake-v1 | block precision 61.11% (50.00% to 66.67%)", line)
        self.assertIn("seconds/run [1.50, 1.50, 1.50]", line)
        self.assertIn("dirty: yes", line)
        self.assertIn("dirty: no", score.one_line("fake-v1", summary, runs, dirty=False))
        self.assertEqual(len(line.splitlines()), 1)

    def test_repeated_errors_are_neither_consistent_nor_correct(self):
        summary = score.aggregate(fake_runs([["error"] * 6] * 3))
        self.assertEqual(summary["consistency"], 0)
        self.assertEqual(summary["pass3"], 0)
        self.assertEqual(summary["metrics"]["macro recall"]["mean"], 0)

    def test_undefined_run_is_not_omitted_from_mean(self):
        predictions = deepcopy(PREDICTIONS)
        predictions[1] = ["target"] * 6
        summary = score.aggregate(fake_runs(predictions))
        self.assertEqual(summary["metrics"]["block precision"], {"mean": None, "min": None, "max": None})

    def test_app_triage_integration_with_fake_model_call(self):
        def call(messages, **options):
            pairs = re.findall(r'<term id="([^"]+)">(.*?)</term>', messages[1]["content"])
            return json.dumps({"results": [{"id": tid, "label": "target", "intent": "commercial",
                                            "trigger": unescape(term).split()[0], "reason": "Invented reason."}
                                           for tid, term in pairs]}), {"prompt": 12, "completion": 6}

        def fake_model_triage(terms, context):
            return score.triage(terms, context, call=call)

        context = score.build_context("Zorbix makes invented wands.", "Fixture campaign")
        runs = score.evaluate(FIXTURE, context, triage_fn=fake_model_triage)
        self.assertEqual([r["label"] for r in runs[0]["rows"]], ["target"] * 6)
        self.assertEqual(runs[0]["metrics"]["calls"], 1)
        self.assertEqual(runs[0]["metrics"]["total tokens"], 18)

    def test_invalid_model_label_retries_to_error_and_is_scored_as_wrong(self):
        calls = []
        labels = {r["search_term"]: r["label"] for r in FIXTURE}

        def call(messages, **options):
            pairs = re.findall(r'<term id="([^"]+)">(.*?)</term>', messages[1]["content"])
            calls.append([tid for tid, term in pairs])
            results = []
            for tid, escaped in pairs:
                term = unescape(escaped)
                # First term fails both attempts. Second term is a wrong valid block.
                label = ("outside-the-set" if term == FIXTURE[0]["search_term"] else
                         "block" if term == FIXTURE[1]["search_term"] else labels[term])
                results.append({"id": tid, "label": label, "intent": "commercial",
                                "trigger": term.split()[0], "reason": "Invented reason."})
            return json.dumps({"results": results}), {"prompt": 12, "completion": 6}

        def fake_model_triage(terms, context):
            return score.triage(terms, context, call=call)

        with patch.object(score.triage_module.time, "perf_counter", side_effect=[0, 1.5, 10, 12, 20, 22.5]):
            runs = score.evaluate(FIXTURE, "Invented context", triage_fn=fake_model_triage)
        self.assertEqual(len(calls), 6)  # initial batch and retry in every run
        self.assertEqual(calls[1::2], [["t1"]] * 3)
        expected = {
            "target precision": None, "target recall": 0,
            "block precision": 2/3, "block recall": 1,
            "monitor precision": 1, "monitor recall": 1,
            "macro precision": None, "macro recall": 2/3,
            "monitor share": 1/3, "whole-term triggers": 0,
            "intent transactional share": 0, "intent commercial share": 5/6,
            "intent informational share": 0, "intent navigational share": 0,
            "intent missing share": 1/6,
            "prompt tokens": 24, "completion tokens": 12, "total tokens": 36,
            "calls": 2, "seconds": 2, "errors": 1, "validation/call diagnostics": 4,
        }
        self.assertEqual(len(expected), 22)
        for run, seconds in zip(runs, (1.5, 2, 2.5)):
            self.assertEqual(run["rows"][0]["label"], "error")
            self.assertEqual(run["matrix"], {
                "target": {"target": 0, "block": 1, "monitor": 0, "error": 1},
                "block": {"target": 0, "block": 2, "monitor": 0, "error": 0},
                "monitor": {"target": 0, "block": 0, "monitor": 2, "error": 0},
            })
            # No target predictions: precision is n/a; both target rows count as wrong.
            self.assertEqual(run["metrics"], {**expected, "seconds": seconds})
        summary = score.aggregate(runs)
        self.assertEqual(summary["metrics"], {
            **{key: {"mean": value, "min": value, "max": value} for key, value in expected.items()},
            "seconds": {"mean": 2, "min": 1.5, "max": 2.5},
        })
        self.assertEqual(summary["consistency"], 5/6)  # repeated error excluded
        self.assertEqual(summary["pass3"], 4/6)  # repeated error and wrong block excluded


class ReadingSheet(unittest.TestCase):
    def test_wrong_first_then_seeded_correct_and_other_runs_by_id(self):
        runs = fake_runs()
        runs[1]["rows"].reverse()  # joining other runs must use id, not position
        sheet, count = score.reading_sheet(runs, size=4)
        # Wrong ids 2,4,6 plus seed-42 choice from correct ids 1,3,5: id 5.
        self.assertEqual(count, 3)
        self.assertEqual([r["id"] for r in sheet], ["2", "4", "5", "6"])
        self.assertEqual(sheet[1]["label"], "error")
        self.assertEqual(sheet[1]["label_run2"], "block")
        self.assertEqual(sheet[2]["label_run3"], "target")
        self.assertTrue(all(r["note"] == "" for r in sheet))
        self.assertEqual(sheet, score.reading_sheet(runs, size=4)[0])

    def expanded(self, wrong):
        # Expand the invented fixture to test the actual 20-row cutoff.
        fixture = [{**FIXTURE[(i - 1) % 6], "id": str(i), "search_term": f"zorbix invented {i}"}
                   for i in range(1, 41)]
        labels = ["error" if i < wrong else row["label"] for i, row in enumerate(fixture)]
        return fake_runs([labels] * 3, fixture)

    def test_twenty_rows_include_all_errors_then_correct(self):
        runs = self.expanded(3)
        sheet, count = score.reading_sheet(runs)
        self.assertEqual(count, 3)
        self.assertEqual(len(sheet), 20)
        self.assertEqual(len({r["id"] for r in sheet}), 20)
        self.assertTrue({"1", "2", "3"} <= {r["id"] for r in sheet})
        self.assertEqual(sum(r["label"] == r["golden_label"] for r in sheet), 17)
        self.assertEqual([int(r["id"]) for r in sheet], sorted(int(r["id"]) for r in sheet))

    def test_more_than_twenty_errors_uses_first_twenty_and_discloses(self):
        runs = self.expanded(25)
        sheet, count = score.reading_sheet(runs)
        self.assertEqual(count, 25)
        self.assertEqual([r["id"] for r in sheet], [str(i) for i in range(1, 21)])
        report = score.score_markdown("fake", "abc123", runs, score.aggregate(runs), count, "2026-01-01", METADATA)
        self.assertIn("25 wrong/error rows, more than 20", report)
        self.assertIn("first 20 wrong/error rows by id", report)


class FilesAndCLI(unittest.TestCase):
    def test_scorer_and_golden_hashes_use_only_bytes_and_report_only_digests(self):
        runs = fake_runs()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            directory = root / "evaluation"
            directory.mkdir()
            paths = (directory / "score.py", directory / "golden_set.csv")
            # Invented bytes only. The BOM must be included in the CSV digest.
            contents = (b"# Invented scorer.\r\n", b"\xef\xbb\xbf\xff\x00invented bytes")
            for path, content in zip(paths, contents):
                path.write_bytes(content)
            expected = {name: hashlib.sha256(content).hexdigest()
                        for name, content in zip(SOURCE_NAMES[-2:], contents)}
            with patch.object(score, "source_paths", return_value=paths), \
                 patch.object(score.subprocess, "check_output", return_value=""), \
                 patch.object(Path, "read_text", side_effect=AssertionError("Hashing must not decode text")), \
                 patch.object(csv, "DictReader", side_effect=AssertionError("Hashing must not parse CSV")), \
                 redirect_stdout(io.StringIO()) as out, redirect_stderr(io.StringIO()) as err:
                metadata = score.working_tree_metadata(root)
            self.assertEqual(metadata["sha256"], expected)
            self.assertEqual(set(metadata), {"dirty", "model", "sha256"})
            self.assertEqual(out.getvalue(), "")
            self.assertEqual(err.getvalue(), "")
            report = score.score_markdown("fake", "abc123", runs, score.aggregate(runs), 3, "2026-01-01", metadata)
            for name, digest in expected.items():
                self.assertIn(f"| `{name}` | `{digest}` |", report)
            self.assertNotIn("invented bytes", report)
            self.assertEqual([path.read_bytes() for path in paths], list(contents))

    def test_class_counts_and_one_error_recall_change_follow_golden_labels(self):
        fixture = deepcopy(FIXTURE)
        for row, label in zip(fixture, ("target", "block", "block", "monitor", "monitor", "monitor")):
            row["label"] = label
        for labels, sentences in (
            ([row["label"] for row in fixture], (
                "The target class has 1 row, so one error changes its recall by 100.00 percentage points.",
                "The block class has 2 rows, so one error changes its recall by 50.00 percentage points.",
                "The monitor class has 3 rows, so one error changes its recall by 33.33 percentage points.",
            )),
            (["target"] * 6, (
                "The target class has 6 rows, so one error changes its recall by 16.67 percentage points.",
                "The block class has 0 rows, so its recall and the change from one error are n/a.",
                "The monitor class has 0 rows, so its recall and the change from one error are n/a.",
            )),
        ):
            with self.subTest(labels=labels):
                for row, label in zip(fixture, labels):
                    row["label"] = label
                runs = fake_runs(fixture=fixture)
                report = score.score_markdown("fake", "abc123", runs, score.aggregate(runs), 3, "2026-01-01", METADATA)
                for sentence in sentences:
                    self.assertIn(sentence, report)

    def test_bom_fixture_read_is_read_only_and_schema_checked(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "invented.csv"
            with path.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=score.GOLDEN_FIELDS)
                writer.writeheader()
                writer.writerows(FIXTURE)
            before = path.read_bytes()
            self.assertEqual(score.read_golden(path, expected_rows=6), FIXTURE)
            self.assertEqual(path.read_bytes(), before)
            with self.assertRaisesRegex(ValueError, "Expected 40"):
                score.read_golden(path)

    def test_no_overwrite_when_any_artifact_exists(self):
        runs = fake_runs()
        for tail in ("runs.csv", "score.md", "read20.csv"):
            with self.subTest(tail=tail), tempfile.TemporaryDirectory() as tmp:
                directory = Path(tmp)
                existing = directory / f"2026-01-01-fake-{tail}"
                existing.write_text("keep me", encoding="utf-8")
                paths = score.write_results(directory, "2026-01-01", "fake", runs, "abc123", METADATA)
                self.assertTrue(all("fake-2-" in p.name for p in paths))
                self.assertEqual(existing.read_text(), "keep me")
                again = score.write_results(directory, "2026-01-01", "fake", runs, "abc123", METADATA)
                self.assertTrue(all("fake-3-" in p.name for p in again))
                self.assertEqual(len(list(directory.iterdir())), 7)

    def test_failed_staging_reservation_or_rename_leaves_no_files_or_consumed_name(self):
        runs = fake_runs()
        for failure in ("csv-first", "csv-second", "markdown", "reservation", "rename"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as tmp:
                directory = Path(tmp)
                original_rows = csv.DictWriter.writerows
                original_open = Path.open
                original_replace = Path.replace
                counters = {"csv": 0, "reservation": 0, "rename": 0}

                def writerows(writer, rows):
                    original_rows(writer, rows)
                    counters["csv"] += 1
                    if counters["csv"] == (1 if failure == "csv-first" else 2):
                        raise OSError("Synthetic write failure")

                def open_file(path, mode="r", *args, **kwargs):
                    if mode == "x":
                        counters["reservation"] += 1
                        if counters["reservation"] == 2:
                            raise OSError("Synthetic reservation failure")
                    return original_open(path, mode, *args, **kwargs)

                def replace_file(source, destination):
                    counters["rename"] += 1
                    if counters["rename"] == 1:
                        # All three staged files are complete before the first publication.
                        self.assertEqual(len(list(source.parent.iterdir())), 3)
                        self.assertTrue(all(p.stat().st_size > 0 for p in source.parent.iterdir()))
                    if counters["rename"] == 2:
                        raise OSError("Synthetic rename failure")
                    return original_replace(source, destination)

                if failure.startswith("csv"):
                    patched = patch.object(csv.DictWriter, "writerows", writerows)
                elif failure == "markdown":
                    patched = patch.object(Path, "write_text", side_effect=OSError("Synthetic write failure"))
                elif failure == "reservation":
                    patched = patch.object(Path, "open", open_file)
                else:
                    patched = patch.object(Path, "replace", replace_file)
                with patched, self.assertRaises(OSError):
                    score.write_results(directory, "2026-01-01", "fake", runs, "abc123", METADATA)
                self.assertEqual(list(directory.iterdir()), [])
                paths = score.write_results(directory, "2026-01-01", "fake", runs, "abc123", METADATA)
                self.assertEqual([p.name for p in paths],
                                 [f"2026-01-01-fake-{tail}" for tail in ("runs.csv", "score.md", "read20.csv")])

    def test_artifact_columns_counts_and_score_tables(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = score.write_results(Path(tmp), "2026-01-01", "fake", fake_runs(), "abc123", METADATA)
            for path, fields, count in ((paths[0], score.RUN_FIELDS, 18), (paths[2], score.READ_FIELDS, 6)):
                with path.open(encoding="utf-8", newline="") as handle:
                    reader = csv.DictReader(handle)
                    self.assertEqual(reader.fieldnames, list(fields))
                    self.assertEqual(len(list(reader)), count)
            report = paths[1].read_text()
            self.assertIn("Git commit: `abc123`", report)
            self.assertIn("dirty: yes", report)
            self.assertIn("only uncommitted changes under `app/`", report)
            self.assertIn("Model: `invented-model`", report)
            for name, digest in METADATA["sha256"].items():
                self.assertIn(f"| `{name}` | `{digest}` |", report)
            self.assertIn("any error breaks consistency", report)
            self.assertIn("| block | 0 | 1 | 0 | 1 |", report)
            self.assertIn("| block precision | 61.11% | 50.00% | 66.67% |", report)
            self.assertIn("Cost is unavailable", report)

    def test_main_wires_profile_campaign_and_three_artifacts_without_model(self):
        runs = fake_runs()
        paths = tuple(ROOT / "evaluation" / "results" / f"fake-{tail}" for tail in ("runs.csv", "score.md", "read20.csv"))
        with patch.object(score, "read_golden", return_value=FIXTURE) as read, \
             patch.object(score, "evaluate", return_value=runs) as evaluate, \
             patch.object(score, "write_results", return_value=paths) as write, \
             patch.object(score, "working_tree_metadata", return_value=METADATA) as metadata, \
             patch.object(score.subprocess, "check_output", return_value="abc123\n"), \
             redirect_stdout(io.StringIO()) as out:
            self.assertEqual(score.main(["--version", "fake-v1"]), 0)
        read.assert_called_once_with(ROOT / "evaluation" / "golden_set.csv")
        self.assertEqual(evaluate.call_args.args[0], FIXTURE)
        context = evaluate.call_args.args[1]
        self.assertEqual(context, score.build_context((score.APP / "data" / "business_profile.md").read_text(encoding="utf-8"), "Plover Generic Search"))
        metadata.assert_called_once_with()
        self.assertEqual(write.call_args.args[2:], ("fake-v1", runs, "abc123", METADATA))
        lines = out.getvalue().splitlines()
        self.assertEqual(lines[:3], [str(p.relative_to(ROOT)) for p in paths])
        self.assertEqual(lines[-1], score.one_line("fake-v1", score.aggregate(runs), runs, dirty=True))

    def test_metadata_hashes_exact_bytes_and_detects_dirty_status(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = ([b"abc", b"", b"hello"] * 2) + [b"abc", b""]
            expected = [
                "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
                "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
                "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824",
            ] * 2
            expected += expected[:2]
            for name, content in zip(SOURCE_NAMES, data):
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
            paths = tuple(root / name for name in SOURCE_NAMES)
            for status in ("", " M app/core/triage.py\n", "?? app/data/invented.md\n"):
                with self.subTest(status=status), patch.object(score.subprocess, "check_output", return_value=status) as git, \
                     patch.object(score, "source_paths", return_value=paths):
                    metadata = score.working_tree_metadata(root)
                self.assertEqual(metadata["dirty"], bool(status))
                self.assertEqual(metadata["sha256"], dict(zip(SOURCE_NAMES, expected)))
                git.assert_called_once_with(["git", "status", "--porcelain", "--untracked-files=all", "--", "app/"], cwd=root, text=True)

    def test_hash_paths_follow_app_constants_and_loaded_modules(self):
        self.assertEqual(tuple(p.relative_to(ROOT).as_posix() for p in score.source_paths()), SOURCE_NAMES)
        with patch.object(score.triage_module, "PROMPT", ROOT / "app/prompts/invented.md"), \
             patch.object(score.context_module, "LABELS", ROOT / "app/data/invented.md"):
            self.assertEqual(score.source_paths()[:2],
                             (ROOT / "app/prompts/invented.md", ROOT / "app/data/invented.md"))
        self.assertEqual(score.source_paths()[2], score.PROFILE)
        self.assertEqual(score.source_paths()[3:6], (Path(score.triage_module.__file__),
                                                  Path(score.context_module.__file__), Path(score.llm_module.__file__)))
        self.assertEqual(score.source_paths()[6:], (Path(score.__file__).resolve(), score.GOLDEN))

    def test_result_files_do_not_make_app_dirty_but_app_changes_do(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            subprocess.run(["git", "init", "--quiet", str(root)], check=True)
            results = root / "evaluation/results"
            results.mkdir(parents=True)
            (results / "invented-score.md").write_text("Invented result.", encoding="utf-8")
            # Source hashing is covered separately; this exercises the real Git path filter.
            with patch.object(score, "source_paths", return_value=()):
                self.assertFalse(score.working_tree_metadata(root)["dirty"])
                (root / "app").mkdir()
                (root / "app/invented.py").write_text("# Invented app change\n", encoding="utf-8")
                self.assertTrue(score.working_tree_metadata(root)["dirty"])

    def test_model_metadata_matches_app_environment_override_and_fallback(self):
        with patch.object(score.subprocess, "check_output", return_value=""), \
             patch.object(score, "source_paths", return_value=()):
            for model in (None, "", "invented-override"):
                env = {} if model is None else {"LLM_MODEL": model}
                with self.subTest(model=model), patch.dict(score.os.environ, env, clear=True):
                    metadata = score.working_tree_metadata()
                self.assertEqual(metadata["model"], model or score.llm_module.DEFAULT_MODEL)

    def test_invalid_version_is_rejected(self):
        for version in ("../outside", "a/b", "", "v1\nextra"):
            with self.subTest(version=version), self.assertRaises(ValueError):
                score.validate_version(version)


if __name__ == "__main__":
    unittest.main()
