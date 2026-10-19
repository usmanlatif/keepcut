"""Evaluate the app's M2 triage, without changing the app or the frozen labels."""
import argparse
import csv
import hashlib
import os
import random
import re
import statistics
import subprocess
import sys
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"
sys.path.insert(0, str(APP))

from core.context import build_context  # noqa: E402
from core.triage import triage  # noqa: E402
from core import context as context_module, llm as llm_module, triage as triage_module  # noqa: E402

LABELS = ("target", "block", "monitor")
DECISIONS = (*LABELS, "error")
INTENTS = ("transactional", "commercial", "informational", "navigational")
GOLDEN_FIELDS = ("id", "search_term", "label", "trigger", "labeled_by", "date", "note")
RUN_FIELDS = ("run", "id", "search_term", "golden_label", "golden_trigger",
              "intent", "label", "trigger", "reason")
READ_FIELDS = (*RUN_FIELDS[1:], "label_run2", "label_run3", "note")
SEED = 42
PROFILE = APP / "data" / "business_profile.md"
GOLDEN = ROOT / "evaluation" / "golden_set.csv"


def source_paths() -> tuple[Path, ...]:
    return (triage_module.PROMPT, context_module.LABELS, PROFILE,
            Path(triage_module.__file__), Path(context_module.__file__), Path(llm_module.__file__),
            Path(__file__).resolve(), GOLDEN)


def working_tree_metadata(root: Path = ROOT) -> dict:
    status = subprocess.check_output(
        ["git", "status", "--porcelain", "--untracked-files=all", "--", "app/"], cwd=root, text=True
    )
    return {"dirty": bool(status.strip()),
            "model": os.environ.get("LLM_MODEL") or llm_module.DEFAULT_MODEL,
            "sha256": {path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
                       for path in source_paths()}}


def read_golden(path: Path, expected_rows: int = 40) -> list[dict]:
    """Read only. Validation failures deliberately do not disclose source values."""
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != list(GOLDEN_FIELDS):
            raise ValueError("Golden-set columns do not match the required schema.")
        rows = list(reader)
    if len(rows) != expected_rows:
        raise ValueError(f"Expected {expected_rows} golden-set rows.")
    if any(set(row) != set(GOLDEN_FIELDS) or any(v is None for v in row.values())
           or not row["id"].strip() or not row["search_term"].strip()
           or row["label"] not in LABELS for row in rows):
        raise ValueError("Golden set contains an invalid row.")
    if len({row["id"] for row in rows}) != len(rows):
        raise ValueError("Golden-set ids must be unique.")
    return rows


def score_run(rows: list[dict], result) -> dict:
    matrix = {gold: {label: 0 for label in DECISIONS} for gold in LABELS}
    for row in rows:
        matrix[row["golden_label"]][row["label"]] += 1
    metrics = {}
    for label in LABELS:
        tp = matrix[label][label]
        predicted = sum(matrix[gold][label] for gold in LABELS)
        actual = sum(matrix[label].values())  # includes errors as false negatives
        metrics[f"{label} precision"] = tp / predicted if predicted else None
        metrics[f"{label} recall"] = tp / actual if actual else None
    for metric in ("precision", "recall"):
        values = [metrics[f"{label} {metric}"] for label in LABELS]
        metrics[f"macro {metric}"] = statistics.mean(values) if None not in values else None
    metrics["monitor share"] = sum(r["label"] == "monitor" for r in rows) / len(rows)
    metrics["whole-term triggers"] = sum(
        r["trigger"].strip().casefold() == r["search_term"].strip().casefold() for r in rows
    )
    for intent in INTENTS:
        metrics[f"intent {intent} share"] = sum(r["intent"] == intent for r in rows) / len(rows)
    metrics["intent missing share"] = sum(r["intent"] not in INTENTS for r in rows) / len(rows)
    metrics.update({
        "prompt tokens": result.prompt_tokens,
        "completion tokens": result.completion_tokens,
        "total tokens": result.prompt_tokens + result.completion_tokens,
        "calls": result.calls,
        "seconds": result.seconds,
        "errors": sum(r["label"] == "error" for r in rows),
        "validation/call diagnostics": len(result.errors),
    })
    return {"rows": rows, "matrix": matrix, "metrics": metrics}


def evaluate(golden: list[dict], context: str, triage_fn=triage) -> list[dict]:
    """Use the app's positional row contract; its internal ids are not golden ids."""
    terms = [row["search_term"] for row in golden]
    runs = []
    for run in range(1, 4):
        result = triage_fn(terms, context)
        if len(result.rows) != len(golden):
            raise ValueError("Triage returned the wrong number of rows.")
        rows = []
        for source, prediction in zip(golden, result.rows):
            if prediction.get("term") != source["search_term"]:
                raise ValueError("Triage row order does not match the input terms.")
            if prediction.get("label") not in DECISIONS:
                raise ValueError("Triage returned an unknown decision.")
            rows.append({
                "run": run, "id": source["id"], "search_term": source["search_term"],
                "golden_label": source["label"], "golden_trigger": source["trigger"],
                **{key: prediction[key] for key in ("intent", "label", "trigger", "reason")},
            })
        runs.append(score_run(rows, result))
    return runs


def aggregate(runs: list[dict]) -> dict:
    metrics = {}
    for key in runs[0]["metrics"]:
        values = [run["metrics"][key] for run in runs]
        # Never silently drop an undefined run from a three-run mean/range.
        metrics[key] = (dict.fromkeys(("mean", "min", "max")) if None in values else
                        {"mean": statistics.mean(values), "min": min(values), "max": max(values)})
    decisions = [{row["id"]: row["label"] for row in run["rows"]} for run in runs]
    n = len(runs[0]["rows"])
    consistency = sum(row["label"] in LABELS and len({d[row["id"]] for d in decisions}) == 1
                      for row in runs[0]["rows"]) / n
    pass3 = sum(all(d[row["id"]] == row["golden_label"] for d in decisions)
                for row in runs[0]["rows"]) / n
    return {"metrics": metrics, "consistency": consistency, "pass3": pass3}


def id_key(row: dict):
    """Sort numeric ids numerically; text ids lexically."""
    value = row["id"]
    return (0, int(value), value) if value.isdecimal() else (1, 0, value)


def reading_sheet(runs: list[dict], size: int = 20) -> tuple[list[dict], int]:
    first = sorted(runs[0]["rows"], key=id_key)
    wrong = [r for r in first if r["label"] != r["golden_label"]]
    correct = [r for r in first if r["label"] == r["golden_label"]]
    selected = wrong[:size]
    selected += random.Random(SEED).sample(correct, min(size - len(selected), len(correct)))
    other = [{r["id"]: r["label"] for r in run["rows"]} for run in runs[1:]]
    rows = [{**{key: row[key] for key in RUN_FIELDS[1:]},
             "label_run2": other[0][row["id"]], "label_run3": other[1][row["id"]], "note": ""}
            for row in sorted(selected, key=id_key)]
    return rows, len(wrong)


def percent(value) -> str:
    return "n/a" if value is None else f"{value:.2%}"


def format_metric(key: str, value) -> str:
    if "precision" in key or "recall" in key or "share" in key:
        return percent(value)
    return "n/a" if value is None else f"{value:.2f}"


def score_markdown(version: str, commit: str, runs: list[dict], summary: dict,
                   wrong_count: int, day: str, metadata: dict) -> str:
    class_counts = {label: sum(row["golden_label"] == label for row in runs[0]["rows"])
                    for label in LABELS}
    class_coverage = " ".join(
        (f"The {label} class has {count} {'row' if count == 1 else 'rows'}, so one error "
         f"changes its recall by {100 / count:.2f} percentage points.") if count else
        f"The {label} class has 0 rows, so its recall and the change from one error are n/a."
        for label, count in class_counts.items()
    )
    lines = [f"# M2 triage evaluation: {version}", "", f"Date: {day}",
             f"Git commit: `{commit}`", "", f"dirty: {'yes' if metadata['dirty'] else 'no'}", "",
             "Dirty status covers only uncommitted changes under `app/`.", "",
             f"Model: `{metadata['model']}`", "",
             "| Working-tree file | SHA-256 |", "| --- | --- |"]
    lines += [f"| `{name}` | `{digest}` |" for name, digest in metadata["sha256"].items()]
    lines += ["",
             "Evaluates the current working tree with the app's triage function and current prompt. "
             "The version name is a results label, not a prompt selector.", "",
             "Campaign: Plover Generic Search. Profile: `app/data/business_profile.md`.", "",
             "Errors count as wrong decisions and remain in recall and share denominators. "
             "Precision is n/a when a class is never predicted. Macro scores average all three classes; "
             "if any component is undefined, the macro is n/a. A three-run mean/range is n/a if any run "
             "is undefined. Consistency requires the same valid decision (target, block, or monitor) "
             "in all three runs; any error breaks consistency. pass^3 requires three correct decisions.", ""]
    for number, run in enumerate(runs, 1):
        lines += [f"## Run {number}", "", "Golden labels in rows; predicted decisions in columns.", "",
                  "| Golden label | target | block | monitor | error |", "| --- | ---: | ---: | ---: | ---: |"]
        for label in LABELS:
            lines.append(f"| {label} | " + " | ".join(str(run["matrix"][label][d]) for d in DECISIONS) + " |")
        lines += ["", "| Metric | Score |", "| --- | ---: |"]
        lines += [f"| {key} | {format_metric(key, value)} |" for key, value in run["metrics"].items()]
        lines.append("")
    lines += ["## Across three runs", "", "| Metric | Mean | Min | Max |", "| --- | ---: | ---: | ---: |"]
    for key, values in summary["metrics"].items():
        lines.append(f"| {key} | " + " | ".join(format_metric(key, values[k]) for k in ("mean", "min", "max")) + " |")
    lines += ["", f"Consistency: {percent(summary['consistency'])}.", "",
              f"pass^3: {percent(summary['pass3'])}.", "", "## Reading sheet", "",
              f"Run 1 has {wrong_count} wrong/error rows. All are included, then correct rows sampled "
              f"with seed {SEED} to reach 20, sorted by id."]
    if wrong_count > 20:
        lines[-1] = (f"Run 1 has {wrong_count} wrong/error rows, more than 20. "
                     "The sheet contains only the first 20 wrong/error rows by id; no correct rows were sampled.")
    lines += ["", "## Interpretation", "",
              "Whole-term triggers count predicted triggers equal to the search term after trimming spaces "
              "and ignoring case. Errors are final error rows; validation/call diagnostics also count "
              "problems encountered before retry recovery, without reproducing their text.", "",
              "Token counts, calls, and seconds come from app triage and include retries. "
              "Cost is unavailable: the app reports no monetary cost or proxy tariff.", "",
              "Coverage: 40 terms, one business, one model through the course proxy. "
              f"{class_coverage} "
              "Intent is reported as a distribution, not accuracy. Demo metrics are synthetic. "
              "This scores triage only; it does not test the reviewer, summary, or demo injection.", ""]
    return "\n".join(lines)


def validate_version(version: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,79}", version):
        raise ValueError("Version must be 1-80 letters, digits, dots, underscores, or hyphens, starting with a letter or digit.")
    return version


def write_results(directory: Path, day: str, version: str, runs: list[dict], commit: str,
                  metadata: dict) -> tuple[Path, ...]:
    """Stage all files, then publish a reserved set; roll back this run on failure."""
    validate_version(version)
    summary = aggregate(runs)
    sheet, wrong_count = reading_sheet(runs)
    markdown = score_markdown(version, commit, runs, summary, wrong_count, day, metadata)
    directory.mkdir(parents=True, exist_ok=True)
    tails = ("runs.csv", "score.md", "read20.csv")
    with TemporaryDirectory(prefix=".score-", dir=directory) as temporary:
        staged = tuple(Path(temporary) / tail for tail in tails)
        for path, fields, rows in ((staged[0], RUN_FIELDS, [r for run in runs for r in run["rows"]]),
                                  (staged[2], READ_FIELDS, sheet)):
            with path.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=fields)
                writer.writeheader()
                writer.writerows(rows)
        staged[1].write_text(markdown, encoding="utf-8")
        suffix = 1
        reserved = []
        try:
            while True:
                stem = f"{day}-{version}" + (f"-{suffix}" if suffix > 1 else "")
                paths = tuple(directory / f"{stem}-{tail}" for tail in tails)
                try:
                    for path in paths:
                        # Reserve only after staging succeeds; never replace another run's file.
                        handle = path.open("x", encoding="utf-8")
                        reserved.append(path)
                        handle.close()
                except FileExistsError:
                    for path in reserved:
                        path.unlink()
                    reserved.clear()
                    suffix += 1
                    continue
                break
            for source, destination in zip(staged, paths):
                source.replace(destination)
        except BaseException:
            for path in reserved:
                path.unlink(missing_ok=True)
            raise
    return paths


def one_line(version: str, summary: dict, runs: list[dict], dirty: bool) -> str:
    metrics = summary["metrics"]
    bp = metrics["block precision"]
    avg = lambda key: format_metric(key, metrics[key]["mean"])
    seconds = ", ".join(f"{r['metrics']['seconds']:.2f}" for r in runs)
    return (f"{version} | block precision {percent(bp['mean'])} ({percent(bp['min'])} to {percent(bp['max'])})"
            f" | block recall {avg('block recall')} | monitor share {avg('monitor share')}"
            f" | macro precision {avg('macro precision')} | macro recall {avg('macro recall')}"
            f" | consistency {percent(summary['consistency'])} | pass^3 {percent(summary['pass3'])}"
            f" | seconds/run [{seconds}] | dirty: {'yes' if dirty else 'no'}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True, help="Results label for the current app triage and prompt")
    args = parser.parse_args(argv)
    try:
        validate_version(args.version)
    except ValueError as exc:
        parser.error(str(exc))
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    metadata = working_tree_metadata()
    golden = read_golden(GOLDEN)
    context = build_context(PROFILE.read_text(encoding="utf-8"),
                            "Plover Generic Search")
    runs = evaluate(golden, context)
    paths = write_results(ROOT / "evaluation" / "results", date.today().isoformat(), args.version, runs, commit, metadata)
    for path in paths:
        print(path.relative_to(ROOT))
    print(one_line(args.version, aggregate(runs), runs, metadata["dirty"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
