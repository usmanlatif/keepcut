"""Check the app's M6 weekly summary by code (PRD section 5, M6 rows), without changing the app.

One triage run of the demo report, cut into 20 seeded variants so the figures differ; one summary per variant.
A summary passes when every number in it appears in its figures as written and it has no number word.
"""
import argparse
import csv
import json
import random
import re
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"
sys.path.insert(0, str(APP))

from core.context import build_context  # noqa: E402
from core.llm import complete  # noqa: E402
from core.report import parse_report  # noqa: E402
from core.summary import figures, write_summary  # noqa: E402
from core.table import build_table  # noqa: E402
from core.triage import triage_report  # noqa: E402

SEED = 42
VARIANTS = 20
CAMPAIGN = "Plover Generic Search"
PROFILE = APP / "data" / "business_profile.md"
DEMO = APP / "data" / "demo" / "search_terms_demo_synthetic.csv"
RESULTS = ROOT / "evaluation" / "results"
# A number: an optional minus sign (not when it joins two words or numbers, as in "2-3"), a whole part with
# optional thousands separators and decimals, or a leading-dot decimal (".5"), then an optional %.
NUMBER = re.compile(r"(?<![\d.])(?:(?<![\w.])-)?(?:(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?|\.\d+)(?!\d)%?")
NUMBER_WORDS = ("two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen "
                "seventeen eighteen nineteen twenty").split()
NUMBER_WORD = re.compile(r"\b(" + "|".join(NUMBER_WORDS) + r")\b", re.IGNORECASE)
LABEL_FIELDS = ("id", "variant", "figures", "summary", "recommendations", "figure_check", "usman_label", "usman_note")


def numbers(text: str) -> list[str]:
    return NUMBER.findall(text)


def figure_strings(value) -> list[str]:
    """Every string in the figures, keys included."""
    if isinstance(value, dict):
        return [s for k, v in value.items() for s in (str(k), *figure_strings(v))]
    if isinstance(value, list):
        return [s for v in value for s in figure_strings(v)]
    return [str(value)]


def check_summary(result: dict, figs: dict) -> dict:
    """Pass only when every number in the summary and recommendations is a number in the figures, as written,
    and no number word from two to twenty appears. A summary the app could not write fails with its error."""
    if "error" in result:
        return {"figure_check": "fail", "missing": [], "number_words": [], "error": result["error"]}
    text = "\n".join([result["summary"], *result["recommendations"]])
    known = {n for s in figure_strings(figs) for n in numbers(s)}
    missing = list(dict.fromkeys(n for n in numbers(text) if n not in known))
    words = [m.group(0) for m in NUMBER_WORD.finditer(text)]
    passed = not missing and not words
    return {"figure_check": "pass" if passed else "fail", "missing": missing, "number_words": words, "error": ""}


def triage_table(rows: list[dict], has_month: bool, context: str, triage_fn=triage_report) -> tuple[pd.DataFrame, object]:
    """The app's own table, built by build_table as the screen builds it; no reviewer runs, so its columns are empty."""
    result = triage_fn(rows, context)
    return build_table(rows, result.rows, has_month), result


def load_base(path: Path) -> pd.DataFrame:
    table = pd.read_csv(path, dtype=str, keep_default_na=False)
    for column, kind in (("Clicks", int), ("Cost", float), ("Conversions", float)):
        if column in table.columns:
            table[column] = table[column].astype(kind)
    if "Month" in table.columns:
        table["Month"] = table["Month"].replace("", None)
    return table


def variants(table: pd.DataFrame, count: int = VARIANTS, seed: int = SEED) -> list[tuple[str, pd.DataFrame]]:
    """The whole table, each ad group alone, each month alone, then seeded random halves of the rows."""
    out = [("whole table", table)]
    out += [(f"ad group: {g}", table[table["Ad group"] == g]) for g in dict.fromkeys(table["Ad group"]) if g]
    if "Month" in table.columns:
        out += [(f"month: {m}", table[table["Month"] == m]) for m in dict.fromkeys(table["Month"].dropna()) if m]
    rng = random.Random(seed)
    half = len(table) // 2
    while len(out) < count:
        picked = sorted(rng.sample(range(len(table)), half))
        out.append((f"random half {len(out) + 1}", table.iloc[picked]))
    return [(name, part.reset_index(drop=True)) for name, part in out[:count]]


class Counter:
    """Wraps llm.complete's signature and counts calls and tokens."""

    def __init__(self, call=complete):
        self.call, self.calls, self.prompt_tokens, self.completion_tokens = call, 0, 0, 0

    def __call__(self, messages, **options):
        self.calls += 1
        reply, tokens = self.call(messages, **options)
        tokens = tokens if isinstance(tokens, dict) else {}
        self.prompt_tokens += tokens.get("prompt") or 0
        self.completion_tokens += tokens.get("completion") or 0
        return reply, tokens


def run_summaries(parts, context: str, summary_fn=write_summary, call=complete) -> tuple[list[dict], Counter, float]:
    counter = Counter(call)
    start = time.perf_counter()
    rows = []
    for number, (name, part) in enumerate(parts, 1):
        figs = figures(part)
        result = summary_fn(figs, context, call=counter)
        rows.append({"id": number, "variant": name, "figures": figs, "result": result,
                     **check_summary(result, figs)})
    return rows, counter, round(time.perf_counter() - start, 2)


def reserve(directory: Path, day: str, tails: tuple[str, ...]) -> tuple[Path, ...]:
    """Create every file empty under one free suffix (none, -2, -3, ...); never replace an existing file."""
    directory.mkdir(parents=True, exist_ok=True)
    suffix = 1
    while True:
        stem = day + (f"-{suffix}" if suffix > 1 else "")
        paths = tuple(directory / f"{stem}-{tail}" for tail in tails)
        made = []
        try:
            for path in paths:
                path.open("x").close()
                made.append(path)
            return paths
        except FileExistsError:
            for path in made:
                path.unlink()
            suffix += 1


def dirty(root: Path = ROOT) -> bool:
    status = subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=all", "--", "app/"],
                                     cwd=root, text=True)
    return bool(status.strip())


def report_markdown(rows: list[dict], counter: Counter, seconds: float, commit: str, is_dirty: bool,
                    day: str, base: str) -> str:
    passed = sum(r["figure_check"] == "pass" for r in rows)
    lines = [f"# M6 summary figure check: {day}", "", f"Git commit: `{commit}`", "",
             f"dirty: {'yes' if is_dirty else 'no'}", "", "Dirty status covers only uncommitted changes under `app/`.",
             "", f"Base table: `{base}`. Campaign: {CAMPAIGN}. Profile: `app/data/business_profile.md`. "
             f"Variants seeded with {SEED}.", "",
             f"**Passed: {passed} of {len(rows)}.**", "",
             f"Summary calls: {counter.calls}. Prompt tokens: {counter.prompt_tokens}. "
             f"Completion tokens: {counter.completion_tokens}. "
             f"Total tokens: {counter.prompt_tokens + counter.completion_tokens}. Seconds: {seconds:.2f}.", "",
             "Calls, tokens and seconds cover the summaries only, retries included, not the base triage.", "",
             "| id | variant | check | numbers not in figures | number words | error |",
             "| ---: | --- | --- | --- | --- | --- |"]
    for r in rows:
        cells = [str(r["id"]), r["variant"], r["figure_check"], ", ".join(r["missing"]),
                 ", ".join(r["number_words"]), r["error"]]
        lines.append("| " + " | ".join(c.replace("|", "\\|") for c in cells) + " |")
    return "\n".join(lines) + "\n"


def write_results(rows, counter, seconds, commit, is_dirty, day, base, directory: Path = RESULTS):
    check_path, labels_path = reserve(directory, day, ("summary-check.md", "summary-labels.csv"))
    check_path.write_text(report_markdown(rows, counter, seconds, commit, is_dirty, day, base), encoding="utf-8")
    with labels_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=LABEL_FIELDS)
        writer.writeheader()
        for r in rows:
            result = r["result"]
            writer.writerow({"id": r["id"], "variant": r["variant"],
                             "figures": json.dumps(r["figures"], ensure_ascii=False),
                             "summary": result.get("summary", result.get("error", "")),
                             "recommendations": "\n".join(result.get("recommendations", [])),
                             "figure_check": r["figure_check"], "usman_label": "", "usman_note": ""})
    return check_path, labels_path


def save_base(table: pd.DataFrame, day: str, directory: Path = RESULTS) -> Path:
    (path,) = reserve(directory, day, ("summary-base.csv",))
    table.to_csv(path, index=False)
    return path


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", type=Path, help="A saved triaged table to reuse instead of triaging again")
    args = parser.parse_args(argv)
    day = date.today().isoformat()
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    is_dirty = dirty()
    context = build_context(PROFILE.read_text(encoding="utf-8"), CAMPAIGN)
    if args.base:
        base = args.base.resolve()
    else:
        report = parse_report(DEMO.read_bytes())
        rows = [r for r in report.rows if r["Campaign"] == CAMPAIGN]
        table, result = triage_table(rows, report.has_month, context)
        base = save_base(table, day)
        print(f"{base.relative_to(ROOT)}: triage {result.calls} calls, "
              f"{result.prompt_tokens + result.completion_tokens} tokens, {result.seconds}s")
    table = load_base(base)  # both paths read the saved file, so a reused base gives the same figures
    rows, counter, seconds = run_summaries(variants(table), context)
    base_name = base.relative_to(ROOT).as_posix() if base.is_relative_to(ROOT) else str(base)
    for path in write_results(rows, counter, seconds, commit, is_dirty, day, base_name):
        print(path.relative_to(ROOT))
    print(f"passed {sum(r['figure_check'] == 'pass' for r in rows)} of {len(rows)} | dirty: {'yes' if is_dirty else 'no'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
