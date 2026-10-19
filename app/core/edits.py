"""Map decision edits from the filtered editor back to the full review table.

The editor reports edits by position in the view it showed; view_index holds the full table's index for each of
those positions, so a filtered view edits the right row of the full table. Triage decides once per distinct term, so
an edit sets the decision on every row of the table with the same term key (other months, other ad groups).
"""
import pandas as pd

from core.report import term_key


def apply_decision_edits(table: pd.DataFrame, view_index: list, edited_rows: dict) -> pd.DataFrame:
    """Return a copy of table with each edited Decision written to every row of its term. Other edits are ignored."""
    table = table.copy()
    keys = table["Term"].map(term_key)
    for position, change in edited_rows.items():
        if "Decision" in change:
            table.loc[keys == keys[view_index[int(position)]], "Decision"] = change["Decision"]
    return table
