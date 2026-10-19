"""Dashboard figures over the reviewed table (PRD M4).

Every function reads the table as it stands, so a changed decision changes the figures. Every spend table keeps all
rows of the table, error rows and rows with no intent stage included, so each one totals the table's total cost.
"""
from datetime import datetime

import pandas as pd

from core.exports import new_keywords
from core.report import term_key

DECISIONS = ["target", "block", "monitor", "error"]
INTENTS = ["transactional", "commercial", "informational", "navigational"]
NO_INTENT = "none"  # error rows have no intent stage
NO_MONTH = "no month"


def total_spend(table: pd.DataFrame) -> float:
    return round(float(table["Cost"].sum()), 2)


def tiles(table: pd.DataFrame) -> dict:
    """Total spend, spend on blocked terms, and new keywords found: the distinct keywords in the new keywords file."""
    return {
        "total_spend": total_spend(table),
        "blocked_spend": round(float(table.loc[table["Decision"] == "block", "Cost"].sum()), 2),
        "new_keywords": new_keywords(table, "")["Keyword"].map(term_key).nunique(),
    }


def ordered(values, known: list) -> list:
    """Known values first in their fixed order, then any others in the order they appear."""
    present = list(dict.fromkeys(values))
    return [v for v in known if v in present] + [v for v in present if v not in known]


def spend_by(table: pd.DataFrame, column: str, order: list | None = None) -> pd.DataFrame:
    """Cost summed per value of one column, one row per value, nothing dropped."""
    totals = table.groupby(column, sort=False)["Cost"].sum().round(2)
    index = ordered(table[column], order or [])
    return totals.reindex(index).rename_axis(column).reset_index()


def intent_column(table: pd.DataFrame) -> pd.Series:
    return table["Intent stage"].fillna("").replace("", NO_INTENT)


def spend_by_decision(table: pd.DataFrame) -> pd.DataFrame:
    return spend_by(table, "Decision", DECISIONS)


def spend_by_intent(table: pd.DataFrame) -> pd.DataFrame:
    return spend_by(table.assign(**{"Intent stage": intent_column(table)}), "Intent stage", INTENTS + [NO_INTENT])


def spend_by_ad_group(table: pd.DataFrame) -> pd.DataFrame:
    return spend_by(table, "Ad group")


def crosstab(table: pd.DataFrame, rows: pd.Series, row_order: list) -> pd.DataFrame:
    """Cost with rows as given and one column per decision; every cell is kept, so the cells total the cost."""
    grid = pd.crosstab(rows, table["Decision"], values=table["Cost"], aggfunc="sum").fillna(0.0).round(2)
    grid = grid.reindex(index=ordered(rows, row_order), columns=ordered(table["Decision"], DECISIONS), fill_value=0.0)
    grid.columns.name = "Decision"
    return grid


def intent_by_decision(table: pd.DataFrame) -> pd.DataFrame:
    return crosstab(table, intent_column(table).rename("Intent stage"), INTENTS + [NO_INTENT])


def month_order(months) -> list:
    """Months as the export writes them ("September 2026"), in calendar order; anything unreadable goes last."""
    def when(month):
        try:
            return (0, datetime.strptime(month, "%B %Y"))
        except (TypeError, ValueError):
            return (1, datetime.max)
    return sorted(dict.fromkeys(months), key=when)


def month_by_decision(table: pd.DataFrame) -> pd.DataFrame | None:
    """Spend per month and decision when the table has a Month column, else None."""
    if "Month" not in table.columns:
        return None
    months = table["Month"].fillna(NO_MONTH).replace("", NO_MONTH).rename("Month")
    return crosstab(table, months, month_order(months))
