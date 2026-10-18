"""Triage search terms into target, block or monitor (PRD M2).

Only the term text reaches the model: triage_report takes the search term column from each report row, so no
metric can leak in. Each distinct term (trimmed, case ignored) is triaged once and its result copied to every row
with that term. Each batch is validated object by object; ids that fail are retried once, then marked as error.
"""
import json
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from html import escape, unescape
from pathlib import Path

from core.llm import complete

PROMPT = Path(__file__).resolve().parents[1] / "prompts" / "triage.md"
BATCH_SIZE = 20
PARALLEL_BATCHES = 4
LABELS = {"target", "block", "monitor"}
INTENTS = {"transactional", "commercial", "informational", "navigational"}
FIELDS = ("id", "intent", "label", "trigger", "reason")
OPTIONS = {"temperature": 0, "response_format": {"type": "json_object"}}
ERROR = {"intent": "", "label": "error", "trigger": "", "reason": "No valid answer after one retry."}


@dataclass
class TriageResult:
    rows: list[dict]
    distinct_terms: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    seconds: float = 0.0
    calls: int = 0
    errors: list[str] = field(default_factory=list)


@dataclass
class Batch:
    decided: dict[str, dict] = field(default_factory=dict)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    calls: int = 0
    errors: list[str] = field(default_factory=list)


def system_prompt(context: str) -> str:
    return PROMPT.read_text(encoding="utf-8").replace("{context}", context.strip())


def render_terms(batch: list[tuple[str, str]]) -> str:
    """Escape the term so its text can never close the tag it sits in."""
    return "\n".join(f'<term id="{tid}">{escape(term, quote=False)}</term>' for tid, term in batch)


def check(item: object, terms: dict[str, str]) -> str | None:
    """Return why an object fails the contract, or None if it passes."""
    if not isinstance(item, dict):
        return "result is not an object"
    wrong = [k for k in FIELDS if not isinstance(item.get(k), str)]
    if wrong:
        return f"{item.get('id')!r}: {', '.join(wrong)} not a string"
    tid = item["id"]
    if tid not in terms:
        return f"unknown id {tid!r}"
    if item["intent"] not in INTENTS:
        return f"{tid}: intent {item['intent']!r} not one of the four stages"
    if item["label"] not in LABELS:
        return f"{tid}: label {item['label']!r} not in the set"
    trigger = unescape(item["trigger"]).strip()
    if not trigger:
        return f"{tid}: trigger missing"
    if trigger.casefold() not in terms[tid].casefold():
        return f"{tid}: trigger {item['trigger']!r} not found in the term"
    if not item["reason"].strip():
        return f"{tid}: reason missing"
    return None


def parse_reply(reply: object, terms: dict[str, str]) -> tuple[dict[str, dict], list[str]]:
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
        problem = check(item, terms)
        if problem:
            problems.append(problem)
            continue
        tid = item["id"]
        if tid in seen:
            problems.append(f"{tid}: duplicate id")
            valid.pop(tid, None)
            continue
        seen.add(tid)
        valid[tid] = {k: item[k].strip() for k in ("intent", "label", "reason")}
        valid[tid]["trigger"] = unescape(item["trigger"]).strip()
    problems += [f"{tid}: missing from reply" for tid in terms if tid not in seen]
    return valid, problems


def run_batch(pending: dict[str, str], system: str, call) -> Batch:
    """One call, then one retry of the ids that failed; whatever still fails is marked error."""
    batch = Batch()
    for _attempt in range(2):
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": render_terms(list(pending.items()))},
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
        pending = {tid: term for tid, term in pending.items() if tid not in valid}
        if not pending:
            break
        batch.errors += problems
    for tid in pending:
        batch.decided[tid] = dict(ERROR)
    return batch


def triage(terms: list[str], context: str, call=complete, batch_size: int = BATCH_SIZE, progress=None) -> TriageResult:
    """call has llm.complete's signature; tests pass a fake that returns a canned reply.
    progress, if given, is called as progress(done, total) in the calling thread each time a batch finishes."""
    system = system_prompt(context)
    keys = [term.strip().casefold() for term in terms]
    distinct: dict[str, str] = {}  # key -> id
    unique: list[tuple[str, str]] = []  # (id, first spelling seen, trimmed)
    for term, key in zip(terms, keys):
        if key not in distinct:
            distinct[key] = f"t{len(unique) + 1}"
            unique.append((distinct[key], term.strip()))

    start = time.perf_counter()
    chunks = [dict(unique[b:b + batch_size]) for b in range(0, len(unique), batch_size)]
    batches = []
    with ThreadPoolExecutor(max_workers=PARALLEL_BATCHES) as pool:
        for batch in pool.map(lambda chunk: run_batch(chunk, system, call), chunks):
            batches.append(batch)
            if progress:
                progress(len(batches), len(chunks))

    result = TriageResult(rows=[], distinct_terms=len(unique))
    decided: dict[str, dict] = {}
    for batch in batches:
        decided.update(batch.decided)
        result.prompt_tokens += batch.prompt_tokens
        result.completion_tokens += batch.completion_tokens
        result.calls += batch.calls
        result.errors += batch.errors
    result.seconds = round(time.perf_counter() - start, 2)
    result.rows = [{"id": distinct[key], "term": term, **decided[distinct[key]]} for term, key in zip(terms, keys)]
    return result


def triage_report(rows: list[dict], context: str, call=complete, progress=None) -> TriageResult:
    """The app's entry point: report rows in, one result per row out. Only the search term is read."""
    return triage([row["Search term"] for row in rows], context, call=call, progress=progress)
