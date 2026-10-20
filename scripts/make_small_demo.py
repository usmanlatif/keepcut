"""Cut the small demo export from the full one; run with python3 scripts/make_small_demo.py.

Only app/data/demo/search_terms_demo_synthetic.csv supplies rows, and it is read, never written (the summary check
and the report tests depend on it). Each chosen term keeps all its rows, and the subtotals are recalculated over
them. The keep, cut and watch groups below only spread the pick; the app never sees them.
"""

from __future__ import annotations

import csv
from pathlib import Path

from make_demo_report import CAMPAIGN, HEADER, INJECTION, MONTHS, metrics

DEMO = Path(__file__).resolve().parents[1] / "app" / "data" / "demo"
SOURCE = DEMO / "search_terms_demo_synthetic.csv"
OUTPUT = DEMO / "search_terms_demo_small.csv"
SIZE = 80

KEEP = (
    "merchant account", "ecommerce merchant account", "merchant account providers", "business merchant account",
    "online merchant account", "merchant account fees", "merchant account services", "credit card merchant account",
    "best merchant account", "merchant account for business", "credit card processing", "credit card processing fees",
    "credit card processing companies", "small business credit card processing", "merchant credit card processing",
    "best credit card processing", "credit card processing machine", "credit card processing rates",
    "online credit card processing", "credit card processing small business", "cheapest credit card processing",
    "business credit card processing", "merchant services credit card processing", "payment processing",
    "payment processing services", "online payment processing", "payment processing solutions",
    "card reader for business", "mobile credit card reader", "credit card reader",
)
CUT = (
    "sd card reader", "micro sd card reader", "sd card reader for pc", "usb c sd card reader", "memory card reader",
    "usb sd card reader", "apple sd card reader to usb-c", "smart card reader", "merchant account high risk",
    "high risk ecommerce merchant account", "fantasy sports merchant account", "merchant account offshore",
    "free merchant account", "free payment processing", "square pos login", "clover pos login", "toast login pos",
    "payments news today stripe", "stripe payments news today", "clover pos news today", "toast pos news",
    "k12 school payment processing audit deficiencies", "government payment processing contract awards",
    "government payment processing regulatory mandates", "toast pos business model",
    "stripe connect marketplace payments documentation", "fox river grove pto zeffy stripe paypal payments",
    "stripe payout speed japan card payments days",
)
WATCH = (
    "square pos", "toast pos", "clover pos", "stripe payments", "square credit card processing",
    "stripe credit card processing", "quickbooks credit card processing", "paypal credit card processing",
    "clover credit card processing", "toast pos pricing", "square pos pricing", "square card reader",
    "clover card reader", "card reader", "credit card processing by phone", "credit card processing washington",
    "credit card processing manassas county", "moto merchant account", "[global payments merchant account]",
    "sumup plus credit card reader - white | verizon", "inland usb type-c/a to sd/micro sd card reader",
)
CHOSEN = (*KEEP, *CUT, *WATCH, INJECTION)


def main() -> None:
    if len(CHOSEN) != SIZE or len(set(CHOSEN)) != SIZE:
        raise ValueError(f"Expected {SIZE} distinct chosen terms")
    with SOURCE.open(encoding="utf-8", newline="") as source:
        lines = list(csv.reader(source))
    title, dates, header = lines[:3]
    if tuple(header) != HEADER:
        raise ValueError("The full demo header changed")
    at = {column: header.index(column) for column in ("Month", "Search term", "Campaign", "Clicks", "Impr.",
                                                         "Cost", "Conversions")}
    term_rows = [row for row in lines[3:] if not row[at["Search term"]].startswith("Total:")]
    missing = set(CHOSEN) - {row[at["Search term"]] for row in term_rows}
    if missing:
        raise ValueError(f"Not in the full demo: {sorted(missing)}")
    rows = [row for row in term_rows if row[at["Search term"]] in CHOSEN]
    if {row[at["Campaign"]] for row in rows} != {CAMPAIGN} or {row[at["Month"]] for row in rows} != set(MONTHS):
        raise ValueError("Expected one campaign and both months")

    def counts(row: list[str]) -> tuple[int, int, int, int]:
        cost = row[at["Cost"]].replace(",", "")
        whole, cents = cost.split(".")
        return (int(row[at["Clicks"]].replace(",", "")), int(row[at["Impr."]].replace(",", "")),
                int(whole) * 100 + int(cents), int(row[at["Conversions"]]))

    with OUTPUT.open("w", encoding="utf-8", newline="") as output:
        writer = csv.writer(output, lineterminator="\n")
        writer.writerows([title, dates, header, *rows])
        by_month = {month: [r for r in rows if r[at["Month"]] == month] for month in MONTHS}
        for label in ("Total: Search terms", "Total: Account", "Total: Search"):
            for month, entries in (("", rows), *by_month.items()):
                totals = [sum(column) for column in zip(*map(counts, entries))]
                subtotal = {"Search term": label, "Campaign": CAMPAIGN, "Currency code": "USD",
                            "Campaign type": "Search", "Month": month, **metrics(*totals)}
                writer.writerow([subtotal.get(column, "") for column in HEADER])

    print(f"Wrote {OUTPUT.relative_to(DEMO.parents[2])}: {SIZE} terms, {len(rows)} term rows, 9 subtotals")


if __name__ == "__main__":
    main()
