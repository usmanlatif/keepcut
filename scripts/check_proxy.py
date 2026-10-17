"""Probe the course proxy with three calls; run with python scripts/check_proxy.py.

The diagnostic prompt stays beside this build-only script under the two-zone rule.
No evaluation data is read. SDK retries are disabled to bound actual requests.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import sys
from time import perf_counter
from datetime import datetime, timezone


APP_DIR = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(APP_DIR))

from core.llm import DEFAULT_MODEL, get_client  # noqa: E402


PROMPT_PATH = APP_DIR.parent / "scripts" / "proxy_check_prompt.md"
REPORT_DIR = APP_DIR.parent / "evaluation" / "results"
PROBES = (
    ("Baseline", {}),
    ("temperature=0", {"temperature": 0}),
    ('response_format={"type":"json_object"}', {"response_format": {"type": "json_object"}}),
)


def cell(value: object) -> str:
    """Keep literal errors on one Markdown table row."""
    return str(value).replace("&", "&amp;").replace("|", "&#124;").replace("\r", "&#13;").replace("\n", "<br>")


def visible_prefix(content: str | None) -> str:
    """Describe text before a JSON answer without claiming hidden reasoning."""
    if not content or not content.strip():
        return "Unknown: empty content"
    stripped = content.strip()
    try:
        answer = json.loads(stripped)
    except ValueError:
        # Fenced JSON is formatting, not evidence of reasoning.
        if stripped.startswith("```json\n") or stripped.startswith("```\n"):
            inner = stripped.split("\n", 1)[1].removesuffix("```").strip()
            try:
                if isinstance(json.loads(inner), dict):
                    return "No; JSON fence only"
            except ValueError:
                pass
        decoder = json.JSONDecoder()
        for index, char in enumerate(content):
            if char != "{":
                continue
            try:
                value, _ = decoder.raw_decode(content[index:])
            except ValueError:
                continue
            if isinstance(value, dict) and "answer" in value:
                prefix = content[:index].strip()
                return "Yes: " + json.dumps(prefix, ensure_ascii=False) if prefix else "No"
        return "Unknown: no JSON answer found"
    return "No" if isinstance(answer, dict) else "Unknown: JSON is not an object"


def usage_text(usage: object) -> str:
    if usage is None:
        return "No"
    values = usage.model_dump(exclude_none=True)
    if not any(values.get(key) is not None for key in ("prompt_tokens", "completion_tokens", "total_tokens")):
        return "No token counts: " + json.dumps(values, ensure_ascii=False)
    counts = [f"{key}={values.get(key, 'missing')}" for key in ("prompt_tokens", "completion_tokens", "total_tokens")]
    details = values.get("completion_tokens_details") or {}
    if "reasoning_tokens" in details:
        counts.append(f"reasoning_tokens={details['reasoning_tokens']}")
    return "Yes: " + ", ".join(counts)


def main() -> int:
    run_at = datetime.now(timezone.utc)
    report_path = REPORT_DIR / f"{run_at:%Y-%m-%d}-proxy-check.md"
    prompt = PROMPT_PATH.read_text(encoding="utf-8").strip()
    model = os.environ.get("LLM_MODEL") or DEFAULT_MODEL
    rows = []
    # Prompt requests a tiny answer; omit token-cap options so they cannot
    # confound acceptance of the two settings being tested.
    with get_client().with_options(max_retries=0, timeout=60.0) as client:
        for setting, options in PROBES:
            started = perf_counter()
            try:
                response = client.chat.completions.create(
                    model=model,
                    messages=[{"role": "user", "content": prompt}],
                    **options,
                )
            except Exception as exc:
                elapsed = perf_counter() - started
                # Preserve the exception text, but never persist a credential
                # if an upstream error happens to echo it.
                error = f"{type(exc).__name__}: {exc}".replace(client.api_key, "[REDACTED]")
                rows.append([setting, "no", error, "N/A", "N/A", f"{elapsed:.3f}"])
                continue
            elapsed = perf_counter() - started
            message = response.choices[0].message if response.choices else None
            content = message.content if message else None
            observation = "None"
            if setting.startswith("response_format"):
                try:
                    valid_object = isinstance(json.loads(content or ""), dict)
                except ValueError:
                    valid_object = False
                observation = f"JSON object returned: {'yes' if valid_object else 'no'}"
            if response.choices:
                observation += f"; finish_reason={response.choices[0].finish_reason}"
            else:
                observation += "; no choices returned"
            prefix = visible_prefix(content)
            if message:
                # Some compatible proxies expose reasoning outside content.
                fields = message.model_dump(exclude_none=True)
                reasoning_fields = [name for name, value in fields.items() if "reasoning" in name and value]
                if reasoning_fields:
                    prefix += "; separate reasoning fields: " + ", ".join(reasoning_fields)
            rows.append([setting, "yes", observation, usage_text(response.usage), prefix, f"{elapsed:.3f}"])

    report = [
        "# Course proxy check",
        "",
        f"Run (UTC): {run_at.isoformat(timespec='seconds')}",
        f"Model: {model}. Requests: {len(rows)}; automatic retries: 0.",
        "",
        "One neutral diagnostic prompt from `scripts/proxy_check_prompt.md` was reused unchanged.",
        "No token cap was sent; the prompt requests a sentence of at most 12 words.",
        "",
        "| Setting | Accepted | Exact error if no / observation | Token usage | Text before JSON answer | Seconds |",
        "| --- | --- | --- | --- | --- | ---: |",
        *["| " + " | ".join(cell(value) for value in row) + " |" for row in rows],
        "",
        "Accepted means the request succeeded, not that the proxy honored the setting. "
        "Errors are preserved verbatim after the exception type, except credential redaction and Markdown escaping. "
        "Transport failures cannot establish whether a setting is supported.",
        "Times measure each complete SDK call, including network and generation. "
        "Visible prefixes are evidence only for these replies; hidden reasoning, rate limits, "
        "and the group's credit budget are not established by this check.",
        "",
    ]
    rendered = "\n".join(report)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(rendered, encoding="utf-8")
    print(rendered)
    return 0 if all(row[1] == "yes" for row in rows) else 1


if __name__ == "__main__":
    raise SystemExit(main())
