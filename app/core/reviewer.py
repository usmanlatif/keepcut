"""Check each block decision against the label rules (PRD M3). Read-only: it never changes a decision.

Only block rows are sent, each distinct term once (by the id triage gave it), with its triage answer. Only the
term and the triage fields are read from a row, so no metric can leak in. Batching, retries and the error mark
work as in triage: each batch is validated object by object; ids that fail are retried once, then marked error.
"""
import json
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from html import escape
from pathlib import Path

from core.llm import complete
from core.triage import BATCH_SIZE, LABELS, OPTIONS, PARALLEL_BATCHES

PROMPT = Path(__file__).resolve().parents[1] / "prompts" / "reviewer.md"
VERDICTS = {"agree", "challenge"}
FIELDS = ("id", "verdict", "proposed_label", "reason")
TRIAGE_FIELDS = ("intent", "label", "trigger", "reason")
ERROR = {"verdict": "error", "proposed_label": "", "reason": "No valid answer after one retry."}


@dataclass
class ReviewResult:
    results: dict[str, dict] = field(default_factory=dict)  # triage id -> {"term", "verdict", "proposed_label", "reason"}
    prompt_tokens: int = 0
    completion_tokens: int = 0
    seconds: float = 0.0
    calls: int = 0
    errors: list[str] = field(default_factory=list)

    @property
    def challenges(self) -> int:
        return sum(r["verdict"] == "challenge" for r in self.results.values())


@dataclass
class Batch:
    decided: dict[str, dict] = field(default_factory=dict)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    calls: int = 0
    errors: list[str] = field(default_factory=list)


def system_prompt(context: str) -> str:
    return PROMPT.read_text(encoding="utf-8").replace("{context}", context.strip())


def render_items(batch: dict[str, dict]) -> str:
    """The term, then its triage answer as JSON; both escaped so their text can never close the tag they sit in."""
    lines = []
    for tid, item in batch.items():
        answer = json.dumps({k: item[k] for k in TRIAGE_FIELDS}, ensure_ascii=False)
        lines.append(f'<term id="{tid}">{escape(item["term"], quote=False)}</term>')
        lines.append(f'<triage id="{tid}">{escape(answer, quote=False)}</triage>')
    return "\n".join(lines)


def check(item: object, ids) -> str | None:
    """Return why an object fails the contract, or None if it passes."""
    if not isinstance(item, dict):
        return "result is not an object"
    wrong = [k for k in FIELDS if not isinstance(item.get(k), str)]
    if wrong:
        return f"{item.get('id')!r}: {', '.join(wrong)} not a string"
    tid = item["id"]
    if tid not in ids:
        return f"unknown id {tid!r}"
    if item["verdict"] not in VERDICTS:
        return f"{tid}: verdict {item['verdict']!r} not in the set"
    if item["proposed_label"] not in LABELS:
        return f"{tid}: proposed_label {item['proposed_label']!r} not in the set"
    if (item["verdict"] == "agree") != (item["proposed_label"] == "block"):
        return f"{tid}: {item['verdict']} with proposed_label {item['proposed_label']!r}"
    if not item["reason"].strip():
        return f"{tid}: reason missing"
    return None


def parse_reply(reply: object, ids) -> tuple[dict[str, dict], list[str]]:
    """Valid objects by id, plus the problems found. A missing or duplicated id counts as a problem."""
    if not isinstance(reply, str) or not reply.strip():
        return {}, ["reply is empty"]
    try:
        data = json.loads(reply)
    except ValueError:
        return {}, ["reply is not valid JSON"]
    results = data.get("results") if isinstance(data, dict) else None
    if not isinstance(results, list):
        return {}, ['reply has no "results" list']
    valid, problems, seen = {}, [], set()
    for item in results:
        problem = check(item, ids)
        if problem:
            problems.append(problem)
            continue
        tid = item["id"]
        if tid in seen:
            problems.append(f"{tid}: duplicate id")
            valid.pop(tid, None)
            continue
        seen.add(tid)
        valid[tid] = {k: item[k].strip() for k in ("verdict", "proposed_label", "reason")}
    problems += [f"{tid}: missing from reply" for tid in ids if tid not in seen]
    return valid, problems


def run_batch(pending: dict[str, dict], system: str, call) -> Batch:
    """One call, then one retry of the ids that failed; whatever still fails is marked error."""
    batch = Batch()
    for _attempt in range(2):
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": render_items(pending)},
        ]
        failure = None
        try:
            reply, tokens = call(messages, **OPTIONS)
            tokens = tokens if isinstance(tokens, dict) else {}
        except Exception as e:  # a failed call is retried like a failed reply
            reply, tokens, failure = None, {}, f"call failed: {type(e).__name__}: {e}"
        batch.calls += 1
        batch.prompt_tokens += tokens.get("prompt") or 0
        batch.completion_tokens += tokens.get("completion") or 0
        valid, problems = parse_reply(reply, pending)
        problems = [failure] if failure else problems
        batch.decided.update(valid)
        pending = {tid: item for tid, item in pending.items() if tid not in valid}
        if not pending:
            break
        batch.errors += problems
    for tid in pending:
        batch.decided[tid] = dict(ERROR)
    return batch


def review(rows: list[dict], context: str, call=complete, batch_size: int = BATCH_SIZE, progress=None) -> ReviewResult:
    """rows are triage's rows (id, term, intent, label, trigger, reason); only label block is sent. call has
    llm.complete's signature; tests pass a fake. progress, if given, is called as progress(done, total) in the
    calling thread each time a batch finishes. The rows are read, never written."""
    unique: dict[str, dict] = {}  # triage id -> the fields sent; triage already gives one id per distinct term
    for row in rows:
        if row["label"] == "block" and row["id"] not in unique:
            unique[row["id"]] = {k: row[k] for k in ("term", *TRIAGE_FIELDS)}

    system = system_prompt(context)
    start = time.perf_counter()
    items = list(unique.items())
    chunks = [dict(items[b:b + batch_size]) for b in range(0, len(items), batch_size)]
    batches = []
    with ThreadPoolExecutor(max_workers=PARALLEL_BATCHES) as pool:
        for batch in pool.map(lambda chunk: run_batch(chunk, system, call), chunks):
            batches.append(batch)
            if progress:
                progress(len(batches), len(chunks))

    result = ReviewResult()
    for batch in batches:
        for tid, verdict in batch.decided.items():
            result.results[tid] = {"term": unique[tid]["term"], **verdict}
        result.prompt_tokens += batch.prompt_tokens
        result.completion_tokens += batch.completion_tokens
        result.calls += batch.calls
        result.errors += batch.errors
    result.seconds = round(time.perf_counter() - start, 2)
    return result
