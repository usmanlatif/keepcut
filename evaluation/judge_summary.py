"""Judge the M6 weekly summaries with a model (PRD section 5, M6 judge row), against Usman's PASS/FAIL labels.

Reads the newest *-summary-labels.csv, asks the judge once per summary with the same account context the summary
model received, and reports TPR and TNR with PASS as the positive class. The judge never sees the human label or note.
"""
import argparse
import csv
import hashlib
import json
import re
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from evaluation.summary_check import CAMPAIGN, PROFILE, RESULTS, Counter, build_context, complete, reserve  # noqa: E402

PROMPT = ROOT / "evaluation" / "judge_prompt.md"
RUNNER = Path(__file__).resolve()
OPTIONS = {"temperature": 0, "response_format": {"type": "json_object"}}
LABELS = ("PASS", "FAIL")
VERDICTS = ("PASS", "FAIL", "UNKNOWN")
LABELS_NAME = re.compile(r"^(\d{4}-\d{2}-\d{2})(?:-(\d+))?-summary-labels\.csv$")
JUDGE_FIELDS = ("id", "variant", "verdict", "usman_label", "agree", "evidence", "error")


def newest_labels(directory: Path = RESULTS) -> Path:
    """The labels file with the latest date, then the highest suffix (none counts as 1), as reserve() names them."""
    found = [(m.group(1), int(m.group(2) or 1), p) for p in directory.glob("*-summary-labels.csv")
             if (m := LABELS_NAME.match(p.name))]
    if not found:
        raise FileNotFoundError(f"no *-summary-labels.csv in {directory}")
    return max(found)[2]


def load_labels(path: Path) -> list[dict]:
    """The labeled rows; raises ValueError naming every row whose usman_label is empty or not PASS or FAIL."""
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    bad = [r.get("id", "?") for r in rows if (r.get("usman_label") or "").strip() not in LABELS]
    if not rows:
        raise ValueError(f"{path.name} has no rows")
    if bad:
        raise ValueError(f"usman_label is empty or not PASS or FAIL on id {', '.join(bad)} in {path.name}")
    return rows


def system_prompt(context: str, prompt: Path = PROMPT) -> str:
    return prompt.read_text(encoding="utf-8").replace("{context}", context.strip())


def judge_messages(row: dict, context: str, prompt: Path = PROMPT) -> list[dict]:
    """Only the figures, summary and recommendations reach the judge; the human label and note never do."""
    user = (f"<figures>\n{json.dumps(json.loads(row['figures']), indent=2, ensure_ascii=False)}\n</figures>\n\n"
            f"<summary>\n{row['summary']}\n</summary>\n\n"
            f"<recommendations>\n{row['recommendations']}\n</recommendations>")
    return [{"role": "system", "content": system_prompt(context, prompt)}, {"role": "user", "content": user}]


def check(reply: object) -> tuple[dict | None, str | None]:
    """The reply as {"evidence", "verdict"}, or why it fails the contract. Evidence comes before a PASS or FAIL,
    and the verdict must follow from it: PASS with every quote supported, FAIL with at least one not."""
    if not isinstance(reply, str) or not reply.strip():
        return None, "reply is empty"
    try:
        data = json.loads(reply)
    except ValueError:
        return None, "reply is not valid JSON"
    if not isinstance(data, dict):
        return None, "reply is not a JSON object"
    evidence, verdict = data.get("evidence"), data.get("verdict")
    if verdict not in VERDICTS:
        return None, '"verdict" is not PASS, FAIL or UNKNOWN'
    if not isinstance(evidence, list) or not all(
            isinstance(e, dict) and isinstance(e.get("quote"), str) and e["quote"].strip()
            and isinstance(e.get("figure"), str) and isinstance(e.get("supported"), bool) for e in evidence):
        return None, '"evidence" is not a list of {"quote", "figure", "supported"} with a non-empty quote, ' \
                     'a string figure and a true or false supported'
    if verdict != "UNKNOWN" and not evidence:
        return None, f'"evidence" is empty before a {verdict} verdict'
    if verdict == "PASS" and not all(e["supported"] for e in evidence):
        return None, "verdict is PASS but a quote is marked unsupported"
    if verdict == "FAIL" and all(e["supported"] for e in evidence):
        return None, "verdict is FAIL but every quote is marked supported"
    return {"evidence": evidence, "verdict": verdict}, None


def judge(row: dict, context: str, call=complete, prompt: Path = PROMPT) -> dict:
    """One call, then one retry that names what failed. Returns {"verdict", "evidence", "error"}; UNKNOWN with the
    reason when both replies fail. call has llm.complete's signature; tests pass a fake."""
    messages = judge_messages(row, context, prompt)
    problems = []
    for _attempt in range(2):
        try:
            reply, _tokens = call(messages, **OPTIONS)
        except Exception as e:  # a failed call is retried like a failed reply
            reply, problem = None, f"call failed: {type(e).__name__}: {e}"
        else:
            result, problem = check(reply)
            if result:
                return {**result, "error": ""}
        problems.append(problem)
        messages = messages[:2] + ([{"role": "assistant", "content": reply}] if isinstance(reply, str) else []) + [
            {"role": "user", "content": f"That reply failed the output contract: {problem}. Reply again with one "
                                        "JSON object that meets it."}]
    return {"verdict": "UNKNOWN", "evidence": [], "error": "No valid verdict after one retry: " + "; ".join(problems) + "."}


def rate(rows: list[dict], label: str) -> dict:
    """Among rows Usman labeled `label`, how many the judge gave the same verdict; UNKNOWN counts as wrong.
    rate is None (n/a) when the class has no rows."""
    group = [r for r in rows if r["usman_label"] == label]
    hits = sum(r["verdict"] == label for r in group)
    unknown = sum(r["verdict"] == "UNKNOWN" for r in group)
    return {"hits": hits, "total": len(group), "unknown": unknown, "rate": hits / len(group) if group else None}


def metrics(rows: list[dict]) -> dict:
    return {"tpr": rate(rows, "PASS"), "tnr": rate(rows, "FAIL"),
            "unknown": sum(r["verdict"] == "UNKNOWN" for r in rows), "total": len(rows)}


def shown(m: dict) -> str:
    return "n/a" if m["rate"] is None else f"{m['rate']:.2f}"


def run_judge(labeled: list[dict], context: str, call=complete, prompt: Path = PROMPT) -> tuple[list[dict], Counter, float]:
    counter = Counter(call)
    start = time.perf_counter()
    rows = []
    for row in labeled:
        result = judge(row, context, call=counter, prompt=prompt)
        label = row["usman_label"].strip()
        rows.append({"id": row["id"], "variant": row["variant"], "usman_label": label, **result,
                     "agree": "yes" if result["verdict"] == label else "no"})
    return rows, counter, round(time.perf_counter() - start, 2)


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dirty(root: Path = ROOT) -> bool:
    status = subprocess.check_output(["git", "status", "--porcelain", "--untracked-files=all", "--",
                                      "app/", "evaluation/judge_prompt.md", "evaluation/judge_summary.py"],
                                     cwd=root, text=True)
    return bool(status.strip())


def evidence_text(evidence: list[dict]) -> str:
    return "<br>".join(f"{'supported' if e['supported'] else 'UNSUPPORTED'}: \"{e['quote']}\" ({e['figure']})"
                       for e in evidence)


def report_markdown(rows, counter, seconds, commit, is_dirty, day, labels_name, prompt_sha, runner_sha,
                    labels_sha) -> str:
    m = metrics(rows)
    tpr, tnr = m["tpr"], m["tnr"]
    lines = [f"# M6 summary judge: {day}", "", f"Git commit: `{commit}`", "",
             f"dirty: {'yes' if is_dirty else 'no'}", "",
             "Dirty status covers uncommitted changes under `app/`, in `evaluation/judge_prompt.md` and in "
             "`evaluation/judge_summary.py`.", "",
             f"Labels: `{labels_name}`, SHA-256 `{labels_sha}`.", "",
             f"Judge prompt: `evaluation/judge_prompt.md`, SHA-256 `{prompt_sha}`.", "",
             f"Judge runner: `evaluation/judge_summary.py`, SHA-256 `{runner_sha}`.", "",
             f"Context: build_context with `app/data/business_profile.md` and campaign {CAMPAIGN}.", "",
             "PASS is the positive class. UNKNOWN counts as wrong in TPR and TNR.", "",
             "| measure | value | counts | UNKNOWN in class |", "| --- | ---: | --- | ---: |",
             f"| TPR (judge PASS among Usman's PASS) | {shown(tpr)} | {tpr['hits']} of {tpr['total']} | {tpr['unknown']} |",
             f"| TNR (judge FAIL among Usman's FAIL) | {shown(tnr)} | {tnr['hits']} of {tnr['total']} | {tnr['unknown']} |",
             "", f"UNKNOWN verdicts: {m['unknown']} of {m['total']}.", "",
             f"Judge calls: {counter.calls}. Prompt tokens: {counter.prompt_tokens}. "
             f"Completion tokens: {counter.completion_tokens}. "
             f"Total tokens: {counter.prompt_tokens + counter.completion_tokens}. Seconds: {seconds:.2f}.", "",
             "| id | variant | Usman | judge | agree | evidence | error |",
             "| ---: | --- | --- | --- | --- | --- | --- |"]
    for r in rows:
        cells = [str(r["id"]), r["variant"], r["usman_label"], r["verdict"], r["agree"],
                 evidence_text(r["evidence"]), r["error"]]
        lines.append("| " + " | ".join(c.replace("|", "\\|").replace("\n", " ") for c in cells) + " |")
    return "\n".join(lines) + "\n"


def write_results(rows, counter, seconds, commit, is_dirty, day, labels_name, prompt_sha, runner_sha, labels_sha,
                  directory: Path = RESULTS):
    md_path, csv_path = reserve(directory, day, ("judge.md", "judge.csv"))
    md_path.write_text(report_markdown(rows, counter, seconds, commit, is_dirty, day, labels_name, prompt_sha,
                                       runner_sha, labels_sha), encoding="utf-8")
    with csv_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=JUDGE_FIELDS)
        writer.writeheader()
        for r in rows:
            writer.writerow({**{k: r[k] for k in JUDGE_FIELDS if k != "evidence"},
                             "evidence": json.dumps(r["evidence"], ensure_ascii=False)})
    return md_path, csv_path


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.parse_args(argv)
    labels_path = newest_labels()
    try:
        labeled = load_labels(labels_path)
    except ValueError as e:
        print(f"Refusing to run: {e}", file=sys.stderr)
        return 2
    day = date.today().isoformat()
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    is_dirty = dirty()
    prompt_sha, runner_sha, labels_sha = sha256(PROMPT), sha256(RUNNER), sha256(labels_path)
    context = build_context(PROFILE.read_text(encoding="utf-8"), CAMPAIGN)
    rows, counter, seconds = run_judge(labeled, context)
    labels_name = labels_path.relative_to(ROOT).as_posix()
    for path in write_results(rows, counter, seconds, commit, is_dirty, day, labels_name, prompt_sha, runner_sha,
                              labels_sha):
        print(path.relative_to(ROOT))
    m = metrics(rows)
    print(f"TPR {shown(m['tpr'])} ({m['tpr']['hits']} of {m['tpr']['total']}) | "
          f"TNR {shown(m['tnr'])} ({m['tnr']['hits']} of {m['tnr']['total']}) | "
          f"UNKNOWN {m['unknown']} of {m['total']} | dirty: {'yes' if is_dirty else 'no'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
