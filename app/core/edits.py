"""Map decision edits from the filtered editor back to the full review table.

The editor reports edits by position in the view it showed; view_index holds the full table's index for each of
those positions, so a filtered view edits the right row of the full table.
"""
import pandas as pd


def apply_decision_edits(table: pd.DataFrame, view_index: list, edited_rows: dict) -> pd.DataFrame:
    """Return a copy of table with each edited Decision written to its full-table row. Other edits are ignored."""
    table = table.copy()
    for position, change in edited_rows.items():
        if "Decision" in change:
            table.loc[view_index[int(position)], "Decision"] = change["Decision"]
    return table
