"""Parse a Google Ads search terms export into rows (PRD section 4, search terms report)."""
import csv
import re
import unicodedata
from dataclasses import dataclass

REQUIRED = ["Search term", "Campaign", "Ad group", "Clicks", "Impr.", "Cost", "Conversions"]
OPTIONAL = ["Month"]
INT_COLUMNS = ["Clicks", "Impr."]
FLOAT_COLUMNS = ["Cost", "Conversions"]
DELIMITERS = (",", "\t")
WHOLE = re.compile(r"-?\d+")
DECIMAL = re.compile(r"-?\d+(\.\d+)?")

# Preamble date range, e.g. "September 17, 2026 - October 16, 2026"
DATE_RANGE = re.compile(r"^[A-Z][a-z]+ \d{1,2}, \d{4} - [A-Z][a-z]+ \d{1,2}, \d{4}$")


class ReportError(ValueError):
    """The file cannot be read as a search terms report; the message says why."""


@dataclass
class Report:
    rows: list[dict]
    row_count: int
    date_range: str | None
    total_cost: float
    has_month: bool


def decode(data: bytes | str) -> str:
    """Uploads arrive as bytes, pasted text as str. Accepts UTF-8 (with or without BOM) and UTF-16 with a BOM."""
    if isinstance(data, str):
        return data.lstrip("﻿")
    if data.startswith((b"\xff\xfe", b"\xfe\xff")):
        return data.decode("utf-16")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError as e:
        raise ReportError("The file is not UTF-8 or UTF-16 text. Export the report again as CSV.") from e


def to_number(value: str, column: str, line: int) -> float:
    """'--' (with or without spaces) reads as zero; currency symbols, thousands separators and spaces are stripped.
    What is left must be a plain number: whole for Clicks and Impr., decimals allowed for Cost and Conversions."""
    text = value.strip()
    if text in ("", "--"):
        return 0.0
    cleaned = "".join(c for c in text if c != "," and not c.isspace() and unicodedata.category(c) != "Sc")
    pattern = WHOLE if column in INT_COLUMNS else DECIMAL
    if not pattern.fullmatch(cleaned):
        kind = "a whole number" if column in INT_COLUMNS else "a number"
        raise ReportError(f"Line {line}: {column} value '{value}' is not {kind}.")
    return float(cleaned)


def find_header(text: str) -> tuple[list[list[str]], int]:
    """The header is the first line that, split by a delimiter, contains every required column; the preamble before
    it is skipped and that delimiter is used for the whole file. Only the header line decides the delimiter.
    UTF-16 exports are usually tab-separated, UTF-8 exports comma-separated, so both are tried."""
    lines = text.splitlines()
    candidate = None
    for i, line in enumerate(lines):
        for delimiter in DELIMITERS:
            cells = [c.strip() for c in next(csv.reader([line], delimiter=delimiter), [])]
            if all(name in cells for name in REQUIRED):
                return list(csv.reader(lines, delimiter=delimiter)), i
            if candidate is None and "Search term" in cells:
                candidate = cells
    if candidate is not None:
        missing = [name for name in REQUIRED if name not in candidate]
        raise ReportError("Missing required column(s): " + ", ".join(missing) + ".")
    raise ReportError("No header row found: no row has a 'Search term' column.")


def parse_report(data: bytes | str) -> Report:
    text = decode(data)
    reader, header_row = find_header(text)
    header = [c.strip() for c in reader[header_row]]
    has_month = "Month" in header
    position = {name: header.index(name) for name in REQUIRED + OPTIONAL if name in header}

    date_range = None
    for row in reader[:header_row]:
        for cell in row:
            if DATE_RANGE.match(cell.strip()):
                date_range = cell.strip()

    rows = []
    for offset, row in enumerate(reader[header_row + 1:], start=header_row + 2):
        if not any(cell.strip() for cell in row):
            continue
        row = row + [""] * (len(header) - len(row))
        term = row[position["Search term"]].strip()
        if term.startswith("Total:"):
            continue
        record = {
            "Month": (row[position["Month"]].strip() or None) if has_month else None,
            "Search term": term,
            "Campaign": row[position["Campaign"]].strip(),
            "Ad group": row[position["Ad group"]].strip(),
        }
        for name in INT_COLUMNS:
            record[name] = int(to_number(row[position[name]], name, offset))
        for name in FLOAT_COLUMNS:
            record[name] = to_number(row[position[name]], name, offset)
        rows.append(record)

    total_cost = round(sum(r["Cost"] for r in rows), 2)
    return Report(rows=rows, row_count=len(rows), date_range=date_range, total_cost=total_cost, has_month=has_month)


def term_key(term: str) -> str:
    """One distinct term: trimmed, case folded (so "ß" and "ss" match). The same key triage counts terms by."""
    return str(term).strip().casefold()


def campaigns(rows: list[dict]) -> list[str]:
    """The campaigns in the report, in order of first appearance. Every decision is scoped to one of them."""
    return list(dict.fromkeys(r["Campaign"] for r in rows))


def campaign_rows(rows: list[dict], campaign: str) -> list[dict]:
    return [r for r in rows if r["Campaign"] == campaign]
