"""Tests for app/core/report.py. Fixtures are small, synthetic and written here; terms are invented words."""
import csv
import sys
import unittest
from pathlib import Path

APP = Path(__file__).resolve().parents[1] / "app"
sys.path.insert(0, str(APP))

from core.report import ReportError, parse_report  # noqa: E402

PREAMBLE = 'Search terms report\n"September 17, 2026 - October 16, 2026"\n'

WITH_MONTH = PREAMBLE + (
    "Month,Search term,Match type,Campaign,Ad group,Clicks,Impr.,Cost,Conversions\n"
    'September 2026,zorbix reader,Broad match,Camp A,Group 1,"1,234","5,678",$12.50,2\n'
    "September 2026,quillon terminal,Broad match,Camp A,Group 2,3,40,7.25, --\n"
    "October 2026,zorbix reader,Broad match,Camp A,Group 1,0,9,--,0\n"
    ',Total: Search terms,,Camp A,,"1,237","5,727",19.75,2\n'
    'September 2026,Total: Search terms,,Camp A,,"1,237","5,718",19.75,2\n'
    "October 2026,Total: Search terms,,Camp A,,0,9,0.00,0\n"
    ',Total: Account,,Camp A,,"1,237","5,727",19.75,2\n'
    'September 2026,Total: Account,,Camp A,,"1,237","5,718",19.75,2\n'
    "October 2026,Total: Account,,Camp A,,0,9,0.00,0\n"
    ',Total: Search,,Camp A,,"1,237","5,727",19.75,2\n'
    'September 2026,Total: Search,,Camp A,,"1,237","5,718",19.75,2\n'
    "October 2026,Total: Search,,Camp A,,0,9,0.00,0\n"
)

WITHOUT_MONTH = PREAMBLE + (
    "Search term,Match type,Campaign,Ad group,Clicks,Impr.,Cost,Conversions\n"
    "zorbix reader,Exact match,Camp A,Group 1,4,50,8.00,1\n"
    "quillon terminal,Exact match,Camp A,Group 2,1,10,1.10,0\n"
    "Total: Search terms,,Camp A,,5,60,9.10,1\n"
)

MISSING_COLUMNS = PREAMBLE + (
    "Search term,Match type,Campaign,Clicks,Impr.,Conversions\n"
    "zorbix reader,Exact match,Camp A,4,50,1\n"
)


class MonthFirst(unittest.TestCase):
    def setUp(self):
        self.report = parse_report(WITH_MONTH)

    def test_header_found_after_preamble_and_totals_dropped(self):
        self.assertEqual(self.report.row_count, 3)
        self.assertTrue(self.report.has_month)
        self.assertFalse(any(r["Search term"].startswith("Total:") for r in self.report.rows))

    def test_month_read(self):
        self.assertEqual([r["Month"] for r in self.report.rows], ["September 2026", "September 2026", "October 2026"])

    def test_thousands_separators_and_currency(self):
        first = self.report.rows[0]
        self.assertEqual(first["Clicks"], 1234)
        self.assertEqual(first["Impr."], 5678)
        self.assertEqual(first["Cost"], 12.50)

    def test_dashes_read_as_zero_with_leading_space(self):
        self.assertEqual(self.report.rows[1]["Conversions"], 0.0)
        self.assertEqual(self.report.rows[2]["Cost"], 0.0)

    def test_date_range_and_total_cost(self):
        self.assertEqual(self.report.date_range, "September 17, 2026 - October 16, 2026")
        self.assertEqual(self.report.total_cost, 19.75)


class NoMonth(unittest.TestCase):
    def test_month_optional(self):
        report = parse_report(WITHOUT_MONTH)
        self.assertFalse(report.has_month)
        self.assertEqual(report.row_count, 2)
        self.assertIsNone(report.rows[0]["Month"])
        self.assertEqual(report.total_cost, 9.10)

    def test_no_preamble(self):
        body = WITHOUT_MONTH[len(PREAMBLE):]
        report = parse_report(body)
        self.assertEqual(report.row_count, 2)
        self.assertIsNone(report.date_range)


class Errors(unittest.TestCase):
    def test_missing_columns_named(self):
        with self.assertRaises(ReportError) as ctx:
            parse_report(MISSING_COLUMNS)
        self.assertIn("Ad group", str(ctx.exception))
        self.assertIn("Cost", str(ctx.exception))

    def test_malformed_number_rejected(self):
        for bad in ("12oops50", "1e3"):
            text = WITHOUT_MONTH.replace("8.00", bad)
            with self.assertRaises(ReportError) as ctx:
                parse_report(text)
            message = str(ctx.exception)
            self.assertIn("Line 4", message)
            self.assertIn("Cost", message)
            self.assertIn(bad, message)

    def test_clicks_must_be_whole(self):
        text = WITHOUT_MONTH.replace("Group 1,4,", "Group 1,4.5,")
        with self.assertRaises(ReportError) as ctx:
            parse_report(text)
        self.assertIn("Clicks", str(ctx.exception))
        self.assertIn("4.5", str(ctx.exception))

    def test_no_header(self):
        with self.assertRaises(ReportError):
            parse_report("Search terms report\nnothing here\n")


class Encodings(unittest.TestCase):
    def test_utf16_with_bom_tab_separated(self):
        tabbed = PREAMBLE + (
            "Month\tSearch term\tCampaign\tAd group\tClicks\tImpr.\tCost\tConversions\n"
            "September 2026\tzorbix reader\tCamp A\tGroup 1\t1,234\t5,678\t12.50\t2\n"
            "September 2026\tquillon terminal\tCamp A\tGroup 2\t3\t40\t7.25\t --\n"
            "\tTotal: Search terms\tCamp A\t\t1,237\t5,718\t19.75\t2\n"
        )
        report = parse_report(tabbed.encode("utf-16"))
        self.assertEqual(report.row_count, 2)
        self.assertEqual(report.rows[0]["Clicks"], 1234)
        self.assertEqual(report.total_cost, 19.75)
        self.assertEqual(report.date_range, "September 17, 2026 - October 16, 2026")

    def test_utf16_tab_separated_with_comma_in_term(self):
        tabbed = PREAMBLE + (
            "Month\tSearch term\tCampaign\tAd group\tClicks\tImpr.\tCost\tConversions\n"
            "September 2026\tzorbix, reader\tCamp A\tGroup 1\t1,234\t5,678\t12.50\t2\n"
            "September 2026\tquillon, Search term, guide\tCamp A\tGroup 2\t3\t40\t7.25\t --\n"
        )
        report = parse_report(tabbed.encode("utf-16"))
        self.assertEqual([r["Search term"] for r in report.rows], ["zorbix, reader", "quillon, Search term, guide"])
        self.assertEqual(report.total_cost, 19.75)

    def test_utf16_with_bom_comma_separated(self):
        report = parse_report(WITH_MONTH.encode("utf-16"))
        self.assertEqual(report.row_count, 3)

    def test_utf8_bytes_with_bom(self):
        report = parse_report(WITHOUT_MONTH.encode("utf-8-sig"))
        self.assertEqual(report.row_count, 2)


class DemoReport(unittest.TestCase):
    def test_rows_and_cost_match_total_row(self):
        demo = APP / "data" / "demo" / "search_terms_demo_synthetic.csv"
        report = parse_report(demo.read_bytes())
        self.assertEqual(report.date_range, "August 1, 2026 - September 30, 2026")
        self.assertEqual(report.row_count, 243)
        self.assertFalse(any(r["Search term"].startswith("Total:") for r in report.rows))

        rows = list(csv.reader(demo.read_text(encoding="utf-8-sig").splitlines()))
        header = next(row for row in rows if "Search term" in row)
        term, month, cost = header.index("Search term"), header.index("Month"), header.index("Cost")
        total = next(row for row in rows if len(row) > cost and row[term] == "Total: Search terms" and row[month] == "")
        self.assertEqual(report.total_cost, round(float(total[cost].replace(",", "")), 2))


if __name__ == "__main__":
    unittest.main()
