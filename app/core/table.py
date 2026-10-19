"""The review table: report rows joined with their triage results and reviewer verdicts (PRD section 2, step 4).

build_table is the one place the table is built, so the screen and the evaluation work on the same table.
"""
import pandas as pd

COLUMNS = {
    "Month": "Month",  # kept only when the report has a Month column
    "Search term": "Term",
    "Ad group": "Ad group",
    "intent": "Intent stage",
    "label": "Decision",
    "trigger": "Trigger",
    "reason": "Reason",
    "reviewer": "Reviewer",
    "reviewer_note": "Reviewer note",
    "Clicks": "Clicks",
    "Cost": "Cost",
    "Conversions": "Conversions",
}


def build_table(rows: list[dict], results: list[dict], has_month: bool, verdicts: dict | None = None) -> pd.DataFrame:
    """rows are report rows and results triage's rows, one per report row in the same order. verdicts are the
    reviewer's results by triage id; only block rows read them. None leaves the reviewer columns empty."""
    triaged = pd.DataFrame(results)
    verdicts = verdicts or {}
    found = [verdicts.get(tid) if label == "block" else None for tid, label in zip(triaged["id"], triaged["label"])]
    triaged["reviewer"] = [v["verdict"] if v else "" for v in found]
    triaged["reviewer_note"] = [
        "" if not v else v["reason"] if v["verdict"] == "error" else f'{v["proposed_label"]}: {v["reason"]}'
        for v in found
    ]
    merged = pd.DataFrame(rows).join(triaged)
    kept = [c for c in COLUMNS if c != "Month" or has_month]
    return merged[kept].rename(columns=COLUMNS)
