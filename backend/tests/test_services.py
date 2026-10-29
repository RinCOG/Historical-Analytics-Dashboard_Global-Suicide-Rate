from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from backend.analysis import CSV_PATH, analyze, load_and_validate
from backend.ingest import ingest
from backend.services import (
    get_anomalies,
    get_compare,
    get_coverage,
    get_global_trend,
    get_kpis,
    get_top_countries,
)


class DashboardDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.db_path = Path(cls.temp_dir.name) / "test.sqlite"
        ingest(CSV_PATH, cls.db_path)
        cls.previous_db_path = os.environ.get("DATABASE_PATH")
        os.environ["DATABASE_PATH"] = str(cls.db_path)
        for function in (get_anomalies, get_compare, get_coverage, get_global_trend, get_kpis, get_top_countries):
            function.cache_clear()

    @classmethod
    def tearDownClass(cls):
        if cls.previous_db_path is None:
            os.environ.pop("DATABASE_PATH", None)
        else:
            os.environ["DATABASE_PATH"] = cls.previous_db_path
        cls.temp_dir.cleanup()

    def test_headline_figures_and_top_country_rule(self):
        kpis = get_kpis()
        self.assertAlmostEqual(kpis["global_avg"], 11.9502369786, places=8)
        self.assertEqual(kpis["peak_year"], 1982)
        self.assertAlmostEqual(kpis["peak_value"], 14.7637322846, places=8)
        self.assertEqual(kpis["country_count"], 196)
        self.assertEqual(kpis["top_country"]["entity"], "Lithuania")
        self.assertEqual(get_top_countries(10)[0]["years_reported"], 23)
        self.assertNotIn("Guyana", [row["entity"] for row in get_top_countries(10)])

    def test_global_aggregation_and_country_comparison(self):
        trend = get_global_trend()
        self.assertEqual(len(trend), 56)
        self.assertEqual(trend[0]["year"], 1950)
        peak = max(trend, key=lambda row: row["avg_rate"])
        self.assertEqual(peak["year"], 1982)
        comparison = get_compare("Lithuania")
        self.assertTrue(all(row["country_rate"] >= 0 and row["global_avg"] >= 0 for row in comparison))

    def test_anomalies_use_consecutive_years_and_both_methods(self):
        zscore_rows = get_anomalies(method="zscore", threshold=2)
        iqr_rows = get_anomalies(method="iqr", threshold=2)
        self.assertEqual(len(zscore_rows), 122)
        self.assertEqual(len(iqr_rows), 235)
        self.assertIn("Mauritius", {row["entity"] for row in zscore_rows})

    def test_coverage_counts_gaps_and_respects_pagination(self):
        coverage = get_coverage(1950, 2005, 5, 0)
        self.assertEqual(len(coverage), 5)
        self.assertEqual(coverage[0]["years_reported"], 56)
        self.assertTrue(all(row["gaps"] >= 0 for row in coverage))
        early_year = get_coverage(1950, 1950, 250, 0)
        self.assertEqual(len(early_year), 196)
        self.assertTrue(any(row["years_reported"] == 0 for row in early_year))

    def test_analysis_reproducibility_and_data_quality(self):
        frame = load_and_validate(CSV_PATH)
        report = analyze(frame)
        self.assertEqual(report["row_count"], 2843)
        self.assertEqual(report["quality"]["null_cells"], 0)
        self.assertEqual(report["quality"]["duplicate_entity_year_rows"], 0)
        self.assertEqual(report["summary"]["fixed_panel_entities"], [
            "Australia", "Canada", "Ireland", "Japan", "Netherlands", "New Zealand",
            "United Kingdom", "United States",
        ])


if __name__ == "__main__":
    unittest.main()
