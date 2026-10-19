"""The one screen (PRD section 2, steps 1 to 4): account, report, review terms, check."""
from pathlib import Path

import pandas as pd
import streamlit as st

from core.context import build_context
from core.edits import apply_decision_edits
from core.report import ReportError, campaign_rows, campaigns, parse_report
from core.reviewer import review as review_blocks
from core.triage import triage_report

APP = Path(__file__).resolve().parent
PROFILE = APP / "data" / "business_profile.md"
DEMO = APP / "data" / "demo" / "search_terms_demo_synthetic.csv"
DEFAULT_CAMPAIGN = "Plover Generic Search"
DECISIONS = ["target", "block", "monitor", "error"]
COLUMNS = {
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

st.set_page_config(page_title="Search term triage", layout="wide")
state = st.session_state
state.setdefault("raw", None)
state.setdefault("source", None)
state.setdefault("reviews", {})  # campaign -> {"table", "run", "context"}: each campaign keeps its own review and edits
state.setdefault("editor_version", 0)
state.setdefault("campaign_name", DEFAULT_CAMPAIGN)


def set_report(raw, source):
    """The latest upload, paste or demo click wins; a new report clears the old results."""
    state.raw, state.source, state.reviews = raw, source, {}
    state.pop("campaign_pick", None)


def on_upload():
    file = state.upload
    if file is not None:
        set_report(file.getvalue(), file.name)


def on_paste():
    if state.paste.strip():
        set_report(state.paste, "pasted text")


def on_demo():
    set_report(DEMO.read_bytes(), "demo report")


def editor_key(campaign):
    return f"editor_{campaign}_{state.editor_version}"


def apply_edits():
    """Copy decision edits from the filtered editor back into the full table, then start a fresh editor so the
    positional edits are not reapplied to a view whose rows have changed."""
    edits = state[editor_key(state.view_campaign)]["edited_rows"]
    stored = state.reviews[state.view_campaign]
    stored["table"] = apply_decision_edits(stored["table"], state.view_index, edits)
    state.editor_version += 1


# The report is parsed before step 1 is drawn, because the campaign picked in step 2 sets the campaign name there.
report, report_error, report_campaigns, pick = None, None, [], None
if state.raw is not None:
    try:
        report = parse_report(state.raw)
    except ReportError as e:
        report_error = f"{state.source}: {e}"
if report:
    report_campaigns = campaigns(report.rows)
    pick = state.get("campaign_pick")
    if pick not in report_campaigns:
        pick = report_campaigns[0] if len(report_campaigns) == 1 else None
    state.campaign_name = pick or ""

st.title("Search term triage")

# Step 1: account
st.header("1. Account")
profile = st.text_area("Business profile", PROFILE.read_text(encoding="utf-8"), height=260)
campaign = st.text_input("Campaign", key="campaign_name", disabled=report is not None,
                         placeholder="Choose the campaign in step 2",
                         help="Set by the campaign chosen in step 2 once a report is loaded.")
context = build_context(profile, campaign)
with st.expander("What the model sees"):
    st.code(context, language=None, wrap_lines=True)

# Step 2: report
st.header("2. Report")
upload_col, paste_col = st.columns(2)
upload_col.file_uploader("Upload a Google Ads search terms export", type=["csv", "tsv", "txt"],
                         key="upload", on_change=on_upload)
upload_col.button("Load demo report", on_click=on_demo)
paste_col.text_area("Or paste the export", key="paste", height=120, on_change=on_paste)

rows = []
if report_error:
    st.error(report_error)
elif report and report.row_count == 0:
    st.error("No search terms in this report.")
elif report:
    st.caption(f"Source: {state.source}. {report.row_count} rows across {len(report_campaigns)} campaign(s).")
    st.selectbox("Campaign to review", report_campaigns,
                 index=report_campaigns.index(pick) if pick else None,
                 placeholder="Choose a campaign", key="campaign_pick")
    if pick:
        rows = campaign_rows(report.rows, pick)
        rows_col, dates_col, cost_col = st.columns(3)
        rows_col.metric("Rows", len(rows))
        dates_col.metric("Date range", report.date_range or "Not in the file")
        cost_col.metric("Cost", f"{sum(r['Cost'] for r in rows):,.2f}")

# Step 3: review terms
st.header("3. Review terms")
if st.button("Review terms", type="primary", disabled=not rows):
    bar = st.progress(0.0, text="Triage...")
    result = triage_report(
        rows, context,
        progress=lambda done, total: bar.progress(done / total, text=f"Triage: batch {done} of {total}"),
    )
    bar.progress(0.0, text="Reviewer...")
    checked = review_blocks(
        result.rows, context,
        progress=lambda done, total: bar.progress(done / total, text=f"Reviewer: batch {done} of {total}"),
    )
    bar.empty()
    triaged = pd.DataFrame(result.rows)
    verdicts = [checked.results.get(tid) if label == "block" else None
                for tid, label in zip(triaged["id"], triaged["label"])]
    triaged["reviewer"] = [v["verdict"] if v else "" for v in verdicts]
    triaged["reviewer_note"] = [
        "" if not v else v["reason"] if v["verdict"] == "error" else f'{v["proposed_label"]}: {v["reason"]}'
        for v in verdicts
    ]
    merged = pd.DataFrame(rows).join(triaged)
    state.reviews[pick] = {"table": merged[list(COLUMNS)].rename(columns=COLUMNS), "run": result,
                           "reviewer": checked, "context": context}
    state.editor_version += 1
review = state.reviews.get(pick) if pick else None
if review:
    run, checked = review["run"], review["reviewer"]
    errors = int((review["table"]["Decision"] == "error").sum())
    st.caption(f"{run.distinct_terms} distinct terms, {run.calls} model calls, {run.seconds}s. "
               f"Rows the model could not label: {errors}. "
               f"Reviewer: {checked.calls} model calls, {checked.seconds}s, {checked.challenges} challenges.")

# Step 4: check
st.header("4. Check")
if review is None:
    st.info("Run the review to see the table.")
else:
    if context != review["context"]:
        st.warning("The business profile changed since this campaign's review. These decisions were made under "
                   "the old context: click \"Review terms\" to review the terms again.")
    table = review["table"]
    counts = table["Decision"].value_counts()
    st.caption("  ·  ".join(f"{d}: {counts.get(d, 0)}" for d in DECISIONS))
    filter_col, challenged_col = st.columns([4, 1], vertical_alignment="bottom")
    shown = filter_col.multiselect("Filter by decision", DECISIONS, default=DECISIONS, key="filter")
    challenged = challenged_col.checkbox("Challenged only", key="challenged_only")
    view = table[table["Decision"].isin(shown)]
    if challenged:
        view = view[view["Reviewer"] == "challenge"]
    state.view_index, state.view_campaign = list(view.index), pick
    st.data_editor(
        view,
        key=editor_key(pick),
        on_change=apply_edits,
        hide_index=True,
        width="stretch",
        disabled=[c for c in view.columns if c != "Decision"],
        column_config={
            "Decision": st.column_config.SelectboxColumn("Decision", options=DECISIONS, required=True),
            "Reason": st.column_config.TextColumn("Reason", width="large"),
            "Reviewer note": st.column_config.TextColumn("Reviewer note", width="large"),
            "Cost": st.column_config.NumberColumn("Cost", format="%.2f"),
        },
    )
