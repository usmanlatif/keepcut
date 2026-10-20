"""The one screen (PRD section 2, steps 1 to 6): account, report, review terms, check, dashboard, approve and
summary."""
import re
from pathlib import Path

import streamlit as st

from core import dashboard, exports, summary
from core.context import build_context
from core.edits import apply_decision_edits
from core.report import ReportError, campaign_rows, campaigns, parse_report, term_key
from core.reviewer import review as review_blocks
from core.table import build_table
from core.triage import BATCH_SIZE, triage_report

APP = Path(__file__).resolve().parent
PROFILE = APP / "data" / "business_profile.md"
DEMO = APP / "data" / "demo" / "search_terms_demo_small.csv"
DECISIONS = ["target", "block", "monitor", "error"]
# One color per decision, for the step 4 cards and the charts
DECISION_COLORS = {"target": "#1F4D3F", "block": "#9B2C2C", "monitor": "#7A4F00", "error": "#4A5563"}
STEPS = ("step-1", "step-2")  # the two setup steps, which collapse once complete

st.set_page_config(page_title="KeepCut", layout="wide")
# The only custom CSS: cap the wide layout at 1180px, centered, raise captions to 0.8 opacity for a projector,
# fill the six step boxes white, bold field labels, give buttons the brand green, size the labels of the two
# collapsible steps like the other step headings, style every number as a white card with a bold label (the date
# range smaller and wrapping), pad the chart boxes, and give each decision card a tint, a thick left border and a
# value in its decision color.
st.html("""<style>
[data-testid="stMainBlockContainer"] { max-width: 1180px; margin: 0 auto; }
[data-testid="stCaptionContainer"] { opacity: 0.8; }
[class*="st-key-step-"] { background: #FFFFFF; }
[data-testid="stWidgetLabel"], [data-testid="stWidgetLabel"] p { font-weight: 600; }
button[data-testid="stBaseButton-secondary"]:not(:disabled) { color: #1F4D3F; border-color: #1F4D3F; }
button[data-testid="stBaseButton-secondary"]:not(:disabled):hover { background: #1F4D3F; color: #FFFFFF; }
button[data-testid="stBaseButton-primary"]:not(:disabled):hover { background: #163A2F; border-color: #163A2F; }
[class*="st-key-step-"] > [data-testid="stExpander"] > details > summary { background: #FFFFFF; }
[class*="st-key-step-"] > [data-testid="stExpander"] > details > summary strong { font-size: 2.25rem; font-weight: 600; margin-right: 0.75rem; }
[data-testid="stMetric"] { background: #FFFFFF; padding: 0.75rem 1rem; }
[data-testid="stMetricLabel"] p { font-weight: 600; color: #14181A; }
.st-key-date-range [data-testid="stMetricValue"] { font-size: 1.35rem; }
.st-key-date-range [data-testid="stMetricValue"] p { white-space: normal; }
[class*="st-key-chart-"] { padding: 1.25rem; }
[class*="st-key-decision-"] [data-testid="stMetric"] { border-left-width: 6px; }
[class*="st-key-decision-"] [data-testid="stMetricValue"] { font-size: 3rem; }
""" + "".join(
    f".st-key-decision-{d} [data-testid='stMetric'] {{ background: color-mix(in srgb, {c} 8%, #FFFFFF); "
    f"border-left-color: {c}; }}\n.st-key-decision-{d} [data-testid='stMetricValue'] {{ color: {c}; }}\n"
    for d, c in DECISION_COLORS.items()) + "</style>")
state = st.session_state
state.setdefault("raw", None)
state.setdefault("source", None)
state.setdefault("reviews", {})  # campaign -> {"table", "run", "context"}: each campaign keeps its own review and edits
state.setdefault("editor_version", 0)
state.setdefault("profile", "")
state.setdefault("open", dict.fromkeys(STEPS, True))  # whether each setup step is open, kept across label changes
state.setdefault("complete", dict.fromkeys(STEPS, False))
state.setdefault("demo", False)  # whether the demo button was clicked, which offers the demo report in step 2


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
    """Fills the profile only; step 2 then offers the demo report as a file or as pasted text."""
    state.profile = PROFILE.read_text(encoding="utf-8")
    state.demo = True


def on_demo_file():
    """Loads the small demo report as if it were uploaded; its one campaign is picked when the report is parsed."""
    set_report(DEMO.read_bytes(), DEMO.name)


def on_demo_paste():
    """Puts the demo report's text in the paste box and loads it as pasted text."""
    state.paste = DEMO.read_text(encoding="utf-8")
    set_report(state.paste, "pasted text")


def proper(values):
    """Decisions, intent stages and verdicts as the screen shows them ("target" as "Target"); the table keeps them
    lowercase."""
    return values.str.capitalize()


def remember_open(step):
    state.open[step] = state[step]


def step_box(step, heading, summary):
    """A setup step as an expander. Its label changes as the summary does, which makes Streamlit treat it as a new
    widget, so the open state lives in state.open and is written to the widget's key before every draw."""
    state[step] = state.open[step]
    label = f"**{heading}** {summary}" if summary else f"**{heading}**"
    return st.expander(label, key=step, on_change=remember_open, args=(step,))


def profile_name(profile):
    """The profile's first line, without heading marks or a trailing note in brackets: "Plover Payments"."""
    first = next(line for line in profile.splitlines() if line.strip())
    return re.sub(r"\s*\(.*\)\s*$", "", first.strip().lstrip("#").strip())[:60]


def period(rows, date_range):
    """The months the rows cover, short: "Aug to Sep 2026"; else the report's date range, if it has one."""
    months = list(dict.fromkeys(r["Month"] for r in rows if r.get("Month")))
    parts = [m.split() for m in (months[0], months[-1])] if months else []
    if len(parts) == 2 and all(len(p) == 2 for p in parts) and parts[0][1] == parts[1][1]:
        first, last = parts[0][0][:3], parts[1][0][:3]
        return f"{first} {parts[0][1]}" if first == last else f"{first} to {last} {parts[0][1]}"
    return date_range


def editor_key(campaign):
    return f"editor_{campaign}_{state.editor_version}"


def apply_edits():
    """Copy decision edits from the filtered editor back into the full table, then start a fresh editor so the
    positional edits are not reapplied to a view whose rows have changed."""
    edits = {position: {**change, "Decision": change["Decision"].lower()} if change.get("Decision") else change
             for position, change in state[editor_key(state.view_campaign)]["edited_rows"].items()}
    stored = state.reviews[state.view_campaign]
    stored["table"] = apply_decision_edits(stored["table"], state.view_index, edits)
    state.editor_version += 1


# The report is parsed before step 1 is drawn, because the campaign picked in step 2 goes into the context there,
# and both setup steps need to know whether they are complete before they are drawn.
report, report_error, report_campaigns, pick, rows = None, None, [], None, []
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
    if pick:
        rows = campaign_rows(report.rows, pick)

profile = state.profile
summaries = {"step-1": f"{profile_name(profile)} profile" if profile.strip() else None,
             "step-2": f"{len({term_key(r['Search term']) for r in rows})} terms, "
                       + ", ".join(filter(None, [pick, period(rows, report.date_range)])) if rows else None}
for step in STEPS:
    # A step closes when it becomes complete and opens again if it stops being complete.
    complete = summaries[step] is not None
    if complete != state.complete[step]:
        state.complete[step], state.open[step] = complete, not complete

st.title("KeepCut")
st.caption("Keep what works. Cut what doesn't.")
st.button("Load demo: Plover Payments", on_click=on_demo)

# Step 1: account
with step_box("step-1", "1. Account", summaries["step-1"]):
    st.text_area("Business profile", key="profile", height=260,
                 placeholder="What you sell, who you serve and who you don't, what you don't sell, pricing, "
                             "competitors, and the campaign's goal.")
    context = build_context(profile, pick or "")
    with st.expander("What the model sees"):
        if profile.strip():
            st.code(context, language=None, wrap_lines=True)
        else:
            st.caption("Nothing yet. Write a business profile first.")

# Step 2: report
with step_box("step-2", "2. Report", summaries["step-2"]):
    upload_col, paste_col = st.columns(2)
    upload_col.file_uploader("Upload a Google Ads search terms export", type=["csv", "tsv", "txt"],
                             key="upload", on_change=on_upload)
    paste_col.text_area("Or paste the export", key="paste", height=120, on_change=on_paste)
    if state.demo:
        # A row of their own, so the two buttons line up under fields of different heights
        file_col, text_col = st.columns(2)
        file_col.button("Use demo file", icon=":material/upload_file:", on_click=on_demo_file)
        text_col.button("Paste demo export", icon=":material/content_paste:", on_click=on_demo_paste)

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
            rows_col, dates_col, cost_col = st.columns(3)
            rows_col.metric("Rows", len(rows), border=True, height="stretch")
            dates_col.container(key="date-range", height="stretch").metric(
                "Date range", report.date_range or "Not in the file", border=True, height="stretch")
            cost_col.metric("Cost", f"{sum(r['Cost'] for r in rows):,.2f}", border=True, height="stretch")

# Step 3: review terms
with st.container(border=True, key="step-3"):
    st.header("3. Review terms")
    if st.button("Review terms", type="primary", disabled=not (rows and profile.strip())):
        terms = len({term_key(r["Search term"]) for r in rows})
        bar = st.progress(0.0, text=f"Triage: 0 of {-(-terms // BATCH_SIZE)} calls done, {terms} terms")
        result = triage_report(
            rows, context,
            progress=lambda done, total: bar.progress(done / total,
                                                      text=f"Triage: {done} of {total} calls done, {terms} terms"),
        )
        blocks = len({r["id"] for r in result.rows if r["label"] == "block"})
        bar.progress(0.0, text=f"Reviewer: 0 of {-(-blocks // BATCH_SIZE)} calls done, {blocks} blocks to check")
        checked = review_blocks(
            result.rows, context,
            progress=lambda done, total: bar.progress(
                done / total, text=f"Reviewer: {done} of {total} calls done, {blocks} blocks to check"),
        )
        bar.empty()
        state.reviews[pick] = {"table": build_table(rows, result.rows, report.has_month, checked.results), "run": result,
                               "reviewer": checked, "context": context}
        state.editor_version += 1
    review = state.reviews.get(pick) if pick else None
    if review:
        run, checked = review["run"], review["reviewer"]
        errors = int((review["table"]["Decision"] == "error").sum())
        run_figures = [("Distinct terms", run.distinct_terms), ("Model calls", run.calls),
                       ("Seconds", round(run.seconds + checked.seconds, 1)), ("Rows not labeled", errors),
                       ("Reviewer calls", checked.calls), ("Challenges", checked.challenges)]
        for row in (run_figures[:3], run_figures[3:]):  # two rows of three, so no label is cut short
            for column, (label, value) in zip(st.columns(3), row):
                column.metric(label, value, border=True)

# Step 4: check
with st.container(border=True, key="step-4"):
    st.header("4. Check")
    if review is None:
        st.info("Run the review to see the table.")
    else:
        if context != review["context"]:
            st.warning("The business profile changed since this campaign's review. These decisions were made under "
                       "the old context: click \"Review terms\" to review the terms again.")
        table = review["table"]
        counts = table["Decision"].value_counts()
        for column, d in zip(st.columns(len(DECISIONS)), DECISIONS):
            column.container(key=f"decision-{d}").metric(d.capitalize(), int(counts.get(d, 0)), border=True)
        filter_col, challenged_col = st.columns([4, 1], vertical_alignment="bottom")
        shown = filter_col.multiselect("Filter by decision", DECISIONS, default=DECISIONS, key="filter",
                                       format_func=str.capitalize)
        challenged = challenged_col.checkbox("Challenged only", key="challenged_only")
        view = table[table["Decision"].isin(shown)]
        if challenged:
            view = view[view["Reviewer"] == "challenge"]
        state.view_index, state.view_campaign = list(view.index), pick
        # A display copy: proper case on screen, lowercase in the table (apply_edits lowercases an edited decision)
        shown_view = view.assign(**{c: proper(view[c]) for c in ("Decision", "Intent stage", "Reviewer")},
                                 **{"Reviewer note": view["Reviewer note"].str[:1].str.upper()
                                    + view["Reviewer note"].str[1:]})
        st.data_editor(
            shown_view,
            key=editor_key(pick),
            on_change=apply_edits,
            hide_index=True,
            width="stretch",
            disabled=[c for c in view.columns if c != "Decision"],
            column_config={
                "Decision": st.column_config.SelectboxColumn(
                    "Decision", options=[d.capitalize() for d in DECISIONS], required=True),
                "Reason": st.column_config.TextColumn("Reason", width="large"),
                "Reviewer note": st.column_config.TextColumn("Reviewer note", width="large"),
                "Cost": st.column_config.NumberColumn("Cost", format="%.2f"),
            },
        )

# Step 5: dashboard
with st.container(border=True, key="step-5"):
    st.header("5. Dashboard")
    if review is None:
        st.info("Run the review to see the dashboard.")
    else:
        table = review["table"]
        figures = dashboard.tiles(table)
        spend_col, blocked_col, new_col = st.columns(3)
        spend_col.metric("Total spend", f"{figures['total_spend']:,.2f}", border=True)
        blocked_col.metric("Spend on blocked terms", f"{figures['blocked_spend']:,.2f}", border=True)
        new_col.metric("New keywords found", figures["new_keywords"], border=True)
        st.divider()
        # Display copies of the chart frames: decisions and intent stages in proper case
        by_decision = dashboard.spend_by_decision(table)
        by_intent = dashboard.spend_by_intent(table)
        grid = dashboard.intent_by_decision(table)
        decision_col, intent_col = st.columns(2)
        with decision_col.container(border=True, key="chart-decision"):
            st.subheader("Spend by decision")
            st.bar_chart(by_decision.assign(Decision=proper(by_decision["Decision"])), x="Decision", y="Cost",
                         sort=False)
        with intent_col.container(border=True, key="chart-intent"):
            st.subheader("Spend by intent stage")
            st.bar_chart(by_intent.assign(**{"Intent stage": proper(by_intent["Intent stage"])}), x="Intent stage",
                         y="Cost", sort=False)
        group_col, grid_col = st.columns(2)
        with group_col.container(border=True, key="chart-ad-group"):
            st.subheader("Spend by ad group")
            st.bar_chart(dashboard.spend_by_ad_group(table), x="Ad group", y="Cost")
        with grid_col.container(border=True, key="chart-intent-decision"):
            st.subheader("Intent stage against decision")
            st.bar_chart(grid.rename(index=str.capitalize, columns=str.capitalize), sort=False, y_label="Cost")
        months = dashboard.month_by_decision(table)
        if months is not None:
            with st.container(border=True, key="chart-month"):
                st.subheader("Month over month spend by decision")
                st.bar_chart(months.rename(index=str.capitalize, columns=str.capitalize), sort=False,
                             y_label="Cost")

# Step 6: approve
with st.container(border=True, key="step-6"):
    st.header("6. Approve")
    if review is None:
        st.info("Run the review to approve its decisions.")
    else:
        if st.button("Approve and build outputs", type="primary"):
            review["approved"] = review["table"].copy()
            review["figures"] = summary.figures(review["approved"])
            with st.spinner("Writing the weekly summary..."):
                review["summary"] = summary.write_summary(review["figures"], review["context"])
        clashes = exports.conflicts(review["table"])
        if len(clashes):
            st.warning("These keywords come from terms with different decisions, so they are left out of the negatives "
                       "and new keywords files. Give their terms one decision in step 4, then approve again.")
            st.dataframe(clashes, hide_index=True)
        approved = review.get("approved")
        if approved is not None and not approved["Decision"].equals(review["table"]["Decision"]):
            st.warning("A decision changed after approval. Approve again to build the outputs.")
        elif approved is not None:
            st.caption("Built from the table as approved.")
            lists = [("Negatives", exports.negatives(approved, pick), "negatives.csv"),
                     ("New keywords", exports.new_keywords(approved, pick), "new_keywords.csv"),
                     ("Watchlist", exports.watchlist(approved), "watchlist.csv")]
            for column, (label, frame, name) in zip(st.columns(3), lists):
                with column.container(border=True, key=f"file-{name.removesuffix('.csv')}"):
                    st.markdown(f":material/csv: **{name}**")
                    st.caption(f"{len(frame)} rows")
                    st.download_button(f"{label} ({len(frame)} rows)", exports.to_csv(frame), file_name=name,
                                       mime="text/csv", key=f"download_{name}", type="primary",
                                       icon=":material/download:")
            st.subheader("Weekly summary")
            written = review["summary"]
            if "error" in written:
                st.error(written["error"])
            else:
                st.write(written["summary"])
                st.markdown("**Recommendations**")
                st.markdown("\n".join(f"- {r}" for r in written["recommendations"]))
            with st.expander("Figures the summary was written from"):
                st.json(review["figures"])
