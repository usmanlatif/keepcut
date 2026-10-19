"""The weekly summary (PRD M6): a figures table computed by code, then one model call that writes about it.

figures(table) and write_summary(figures, context) are importable on their own, so the evaluation can call them.
Every figure is a string, formatted exactly as the summary must quote it: costs as 1,234.56, counts as whole numbers
(1,234). The model sees only the figures and the account context, never the table.
"""
import json
import re
from datetime import datetime
from pathlib import Path

import pandas as pd

from core import dashboard, exports
from core.llm import complete
from core.report import term_key

PROMPT = Path(__file__).resolve().parents[1] / "prompts" / "summary.md"
OPTIONS = {"temperature": 0, "response_format": {"type": "json_object"}}
TOP = 5
SENTENCE_END = re.compile(r"[.!?](?=\s|$)")


def money(value: float) -> str:
    return f"{value:,.2f}"


def count(value: float) -> str:
    return f"{int(round(value)):,}"


def months_in(table: pd.DataFrame) -> list[str]:
    """The table's months in calendar order, only those written as the export writes them ("September 2026")."""
    if "Month" not in table.columns:
        return []
    readable = []
    for month in dict.fromkeys(table["Month"].dropna()):
        try:
            readable.append((datetime.strptime(month, "%B %Y"), month))
        except (TypeError, ValueError):
            continue
    return [month for _, month in sorted(readable)]


def top_blocked(table: pd.DataFrame) -> list[dict]:
    """The block terms with the highest cost, summed over each term's rows (term_key, as triage counts terms)."""
    rows = table[table["Decision"] == "block"]
    rows = rows.assign(key=rows["Term"].map(term_key))
    grouped = rows.groupby("key", sort=False).agg(term=("Term", lambda s: s.iloc[0].strip()), cost=("Cost", "sum"))
    grouped = grouped.sort_values("cost", ascending=False, kind="stable").head(TOP)
    return [{"term": r.term, "cost": money(r.cost)} for r in grouped.itertuples()]


def new_keywords(table: pd.DataFrame) -> dict:
    """The new keywords file's distinct keywords: how many, and the ones with the most clicks over their rows."""
    rows = exports.keyword_rows(table, "target")
    grouped = rows.groupby("key", sort=False).agg(keyword=("Keyword", "first"), clicks=("Clicks", "sum"))
    grouped = grouped.sort_values("clicks", ascending=False, kind="stable").head(TOP)
    return {"count": count(dashboard.tiles(table)["new_keywords"]),
            "top_by_clicks": [{"keyword": r.keyword, "clicks": count(r.clicks)} for r in grouped.itertuples()]}


def consecutive(previous: str, latest: str) -> bool:
    """True when latest is the calendar month right after previous (December to January counts)."""
    p, q = (datetime.strptime(m, "%B %Y") for m in (previous, latest))
    return (q.year * 12 + q.month) - (p.year * 12 + p.month) == 1


def latest_pair(table: pd.DataFrame) -> tuple[str, str] | None:
    """The table's latest two months, or None with fewer than two."""
    months = months_in(table)
    return tuple(months[-2:]) if len(months) >= 2 else None


def rising_ad_groups(table: pd.DataFrame) -> list[dict]:
    """Ad groups that spent more in the latest month than in the month before it; empty with fewer than two months,
    or when the latest two months are not consecutive calendar months."""
    pair = latest_pair(table)
    if pair is None or not consecutive(*pair):
        return []
    previous, latest = pair
    spend = table[table["Month"].isin([previous, latest])].pivot_table(
        index="Ad group", columns="Month", values="Cost", aggfunc="sum", fill_value=0.0)
    spend = spend.reindex(columns=[previous, latest], fill_value=0.0)
    rising = spend[spend[latest] > spend[previous]]
    rising = rising.assign(change=rising[latest] - rising[previous]).sort_values("change", ascending=False, kind="stable")
    return [{"ad_group": group, "previous_month": previous, "previous_spend": money(row[previous]),
             "latest_month": latest, "latest_spend": money(row[latest]), "increase": money(row["change"])}
            for group, row in rising.iterrows()]


def figures(table: pd.DataFrame) -> dict:
    """The figures table for one campaign's reviewed table, ready for JSON."""
    by_decision = dashboard.spend_by_decision(table)
    by_intent = dashboard.spend_by_intent(table)
    return {
        "months": months_in(table),
        "total_spend": money(dashboard.total_spend(table)),
        "spend_by_decision": {d: money(c) for d, c in zip(by_decision["Decision"], by_decision["Cost"])},
        "top_blocked_terms_by_cost": top_blocked(table),
        "new_keywords": new_keywords(table),
        "spend_by_intent_stage": {i: money(c) for i, c in zip(by_intent["Intent stage"], by_intent["Cost"])},
        "ad_groups_rising_month_over_month": rising_ad_groups(table),
        "month_over_month_note": month_over_month_note(table),
    }


def month_over_month_note(table: pd.DataFrame) -> str:
    """Why there is no month over month comparison when the months have a gap; empty otherwise."""
    pair = latest_pair(table)
    if pair is None or consecutive(*pair):
        return ""
    return f"{pair[0]} and {pair[1]} are not consecutive months, so month over month change is not reported."


def system_prompt(context: str) -> str:
    return PROMPT.read_text(encoding="utf-8").replace("{context}", context.strip())


def check(reply: object) -> tuple[dict | None, str | None]:
    """The reply as {"summary", "recommendations"}, or why it fails the contract."""
    if not isinstance(reply, str) or not reply.strip():
        return None, "reply is empty"
    try:
        data = json.loads(reply)
    except ValueError:
        return None, "reply is not valid JSON"
    if not isinstance(data, dict):
        return None, "reply is not a JSON object"
    summary, recommendations = data.get("summary"), data.get("recommendations")
    if not isinstance(summary, str) or not summary.strip():
        return None, '"summary" is not a non-empty string'
    sentences = len(SENTENCE_END.findall(summary.strip()))
    if not 4 <= sentences <= 6:
        return None, f'"summary" has {sentences} sentences, not 4 to 6'
    if (not isinstance(recommendations, list) or not 1 <= len(recommendations) <= 3
            or not all(isinstance(r, str) and r.strip() for r in recommendations)):
        return None, '"recommendations" is not a list of 1 to 3 non-empty strings'
    return {"summary": summary.strip(), "recommendations": [r.strip() for r in recommendations]}, None


def write_summary(figures: dict, context: str, call=complete) -> dict:
    """One call, then one retry that names what failed. Returns {"summary", "recommendations"}, or {"error"} with
    the reason when both replies fail. call has llm.complete's signature; tests pass a fake."""
    messages = [
        {"role": "system", "content": system_prompt(context)},
        {"role": "user", "content": f"<figures>\n{json.dumps(figures, indent=2, ensure_ascii=False)}\n</figures>"},
    ]
    problems = []
    for _attempt in range(2):
        try:
            reply, _tokens = call(messages, **OPTIONS)
        except Exception as e:  # a failed call is retried like a failed reply
            reply, problem = None, f"call failed: {type(e).__name__}: {e}"
        else:
            result, problem = check(reply)
            if result:
                return result
        problems.append(problem)
        messages = messages[:2] + ([{"role": "assistant", "content": reply}] if isinstance(reply, str) else []) + [
            {"role": "user", "content": f"That reply failed the output contract: {problem}. Reply again with one "
                                        "JSON object that meets it."}]
    return {"error": "No valid summary after one retry: " + "; ".join(problems) + "."}
