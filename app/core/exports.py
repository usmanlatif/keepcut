"""The three output lists (PRD M5), built from the reviewed table as it stands.

Negatives and new keywords use Google Ads Editor's CSV import layout, checked on 2026-10-19 against:
- https://support.google.com/google-ads/editor/answer/57747 (CSV file columns): headers "Campaign", "Ad group",
  "Keyword" and "Match type" are standard column names
- https://support.google.com/google-ads/editor/answer/56501 (Add multiple keywords): Campaign name, Ad group name
  and Keyword are the required columns; match type values are "broad, phrase, exact, negative broad, negative
  phrase, or negative exact"
- https://support.google.com/google-ads/editor/answer/47635 (Change keyword match types): the sample list writes
  them as "exact" and "negative exact"
- https://support.google.com/google-ads/editor/answer/30553 (Add negative keywords): campaign and ad group negatives
  cannot be added together; the negatives list has no ad group, so it is imported under Keywords, Negative with
  "Add as campaign-level negative keywords"
- https://support.google.com/google-ads/editor/answer/56368 (Prepare a CSV file): the first row is the header

The watchlist is for the manager, not for Editor, so its columns follow the table.

In the Keyword column, the characters " [ ] are removed: answer/47635 reads them as match-type notation, and a
notation that conflicts with the Match type column is an import error. Runs of spaces collapse to one, and a term
left empty is not listed, in any of the three lists.

Two terms can clean to the same keyword (compared with term_key) under different decisions. Such a keyword is a
conflict: it goes in neither Editor file, and conflicts() lists its terms and decisions for the manager to resolve.

One row per distinct term (term_key, as triage counts terms), per ad group for new keywords, with clicks and cost
summed across months. Error rows go in no list.
"""
import re

import pandas as pd

from core.report import term_key

NEGATIVE_COLUMNS = ["Campaign", "Keyword", "Match type"]
KEYWORD_COLUMNS = ["Campaign", "Ad group", "Keyword", "Match type"]
WATCHLIST_COLUMNS = ["Search term", "Ad group", "Intent stage", "Reason", "Clicks", "Cost"]
CONFLICT_COLUMNS = ["Keyword", "Search term", "Decision"]
NEGATIVE_EXACT = "negative exact"
EXACT = "exact"
NOTATION = re.compile(r'["\[\]]')
SPACES = re.compile(r" {2,}")


def keyword(term: str) -> str:
    """The term as an Editor keyword: no match-type notation, single spaces, trimmed."""
    return SPACES.sub(" ", NOTATION.sub("", str(term))).strip()


def cleaned(table: pd.DataFrame) -> pd.DataFrame:
    """Every row with its keyword and that keyword's key; rows whose keyword is empty are left out. mixed marks a
    keyword that carries more than one decision."""
    rows = table.assign(Keyword=table["Term"].map(keyword))
    rows = rows[rows["Keyword"] != ""]
    rows = rows.assign(key=rows["Keyword"].map(term_key))
    return rows.assign(mixed=rows.groupby("key")["Decision"].transform("nunique") > 1)


def keyword_rows(table: pd.DataFrame, decision: str) -> pd.DataFrame:
    """Rows with that decision as Editor keywords; empty keywords and conflicts left out."""
    rows = cleaned(table)
    return rows[(rows["Decision"] == decision) & ~rows["mixed"]]


def conflicts(table: pd.DataFrame) -> pd.DataFrame:
    """Keywords left out of both Editor files because their terms carry different decisions: one row per term."""
    rows = cleaned(table)
    rows = rows[rows["mixed"]]
    rows = rows.assign(term=rows["Term"].map(term_key)).drop_duplicates("term").sort_values("key", kind="stable")
    return pd.DataFrame({"Keyword": rows["Keyword"], "Search term": rows["Term"].str.strip(),
                         "Decision": rows["Decision"]}, columns=CONFLICT_COLUMNS).reset_index(drop=True)


def rows_for(table: pd.DataFrame, decision: str) -> pd.DataFrame:
    rows = table[table["Decision"] == decision]
    return rows.assign(key=rows["Term"].map(term_key))


def negatives(table: pd.DataFrame, campaign: str) -> pd.DataFrame:
    """Block rows as campaign-level exact negatives, one per distinct term."""
    rows = keyword_rows(table, "block").drop_duplicates("key")
    return pd.DataFrame({"Campaign": campaign, "Keyword": rows["Keyword"], "Match type": NEGATIVE_EXACT},
                        columns=NEGATIVE_COLUMNS).reset_index(drop=True)


def new_keywords(table: pd.DataFrame, campaign: str) -> pd.DataFrame:
    """Target rows as exact keywords in the ad group the term came from, one per distinct term per ad group."""
    rows = keyword_rows(table, "target").drop_duplicates(["key", "Ad group"])
    return pd.DataFrame({"Campaign": campaign, "Ad group": rows["Ad group"], "Keyword": rows["Keyword"],
                         "Match type": EXACT}, columns=KEYWORD_COLUMNS).reset_index(drop=True)


def watchlist(table: pd.DataFrame) -> pd.DataFrame:
    """Monitor rows, one per distinct term; a term seen in more than one ad group lists them separated by
    semicolons. Clicks and cost are summed over the term's monitor rows."""
    rows = rows_for(table, "monitor")
    rows = rows[rows["Term"].map(keyword) != ""]
    if rows.empty:
        return pd.DataFrame(columns=WATCHLIST_COLUMNS)
    grouped = rows.groupby("key", sort=False).agg(**{
        "Search term": ("Term", lambda s: s.iloc[0].strip()),
        "Ad group": ("Ad group", lambda s: "; ".join(dict.fromkeys(s))),
        "Intent stage": ("Intent stage", "first"),
        "Reason": ("Reason", "first"),
        "Clicks": ("Clicks", "sum"),
        "Cost": ("Cost", "sum"),
    })
    grouped["Cost"] = grouped["Cost"].round(2)
    return grouped[WATCHLIST_COLUMNS].reset_index(drop=True)


def to_csv(frame: pd.DataFrame) -> bytes:
    return frame.to_csv(index=False).encode("utf-8")
