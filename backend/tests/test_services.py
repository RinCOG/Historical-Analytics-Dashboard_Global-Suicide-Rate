from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from backend.analysis import CSV_PATH, analyze, load_and_validate
from backend.ingest import ingest
from backend.services import (
    get_anomalies,
    get_analysis_quality,
    get_compare,
    get_compare_multi,
    get_coverage,
    get_decomposition,
    get_coverage_deep,
    get_findings,
    get_global_trend,
    get_kpis,
    get_top_countries,
    get_top_countries_by_years,
    get_trend_methods,
    get_rate_distribution,
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


class AnalysisEndpointsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.db_path = Path(cls.temp_dir.name) / "test.sqlite"
        ingest(CSV_PATH, cls.db_path)
        cls.previous_db_path = os.environ.get("DATABASE_PATH")
        os.environ["DATABASE_PATH"] = str(cls.db_path)
        for function in (
            get_anomalies,
            get_analysis_quality,
            get_compare_multi,
            get_coverage_deep,
            get_findings,
            get_kpis,
            get_top_countries_by_years,
            get_trend_methods,
            get_rate_distribution,
        ):
            function.cache_clear()

    @classmethod
    def tearDownClass(cls):
        if cls.previous_db_path is None:
            os.environ.pop("DATABASE_PATH", None)
        else:
            os.environ["DATABASE_PATH"] = cls.previous_db_path
        cls.temp_dir.cleanup()

    def test_analysis_quality_reference_figures(self):
        quality = get_analysis_quality()
        self.assertEqual(quality["row_count"], 2843)
        self.assertEqual(quality["entity_count"], 196)
        self.assertEqual(quality["iso_entity_count"], 190)
        self.assertEqual(quality["former_state_entities"]["USSR"], "OWID_USS")
        self.assertAlmostEqual(float(quality["summary"]["mean"]), 11.9502369786, places=8)
        self.assertEqual(quality["summary"]["global_peak_year"], 1982)
        self.assertAlmostEqual(float(quality["summary"]["global_peak_avg_rate"]), 14.7637322846, places=8)
        self.assertEqual(int(quality["quality"]["rate_outlier_count"]), 82)

    def test_rate_distribution_outliers_and_fences(self):
        distribution = get_rate_distribution()
        self.assertEqual(len(distribution["outliers"]), 82)
        maximum = max(distribution["outliers"], key=lambda row: row["rate"])
        self.assertEqual(maximum["entity"], "Lithuania")
        self.assertEqual(maximum["year"], 1996)
        self.assertAlmostEqual(float(maximum["rate"]), 44.35, places=2)
        self.assertEqual(len(distribution["histogram"]), 9)
        self.assertEqual(len(distribution["rate_iqr_fences"]), 2)

    def test_trend_methods_panel_definitions_and_peaks(self):
        trend = get_trend_methods(1950, 2005)
        self.assertEqual(trend["from"], 1950)
        self.assertEqual(trend["to"], 2005)
        self.assertEqual(len(trend["yearly"]), 56)
        self.assertEqual(len(trend["fixed_panel"]), 56)
        self.assertEqual(len(trend["wide_panel"]), 56)
        self.assertEqual(len(trend["median"]), 56)
        self.assertEqual(len(trend["reporting_counts"]), 56)
        self.assertEqual(
            trend["panel_entities"],
            [
                "Australia", "Canada", "Ireland", "Japan", "Netherlands", "New Zealand",
                "United Kingdom", "United States",
            ],
        )
        raw_peak = max(trend["yearly"], key=lambda row: row["avg_rate"])
        fixed_peak = max(trend["fixed_panel"], key=lambda row: row["avg_rate"])
        wide_peak = max(trend["wide_panel"], key=lambda row: row["avg_rate"])
        self.assertEqual(raw_peak["year"], 1982)
        self.assertAlmostEqual(float(raw_peak["avg_rate"]), 14.76, places=2)
        self.assertEqual(fixed_peak["year"], 1998)
        self.assertAlmostEqual(float(fixed_peak["avg_rate"]), 12.21, places=2)
        self.assertEqual(wide_peak["year"], 1984)

    def test_decomposition_components_sum_to_total_change(self):
        decomposition = get_decomposition("Lithuania")
        pairs = decomposition["pairs"]
        self.assertTrue(any((pair["from_year"], pair["to_year"]) == (2000, 2002) for pair in pairs))
        self.assertTrue(any((pair["from_year"], pair["to_year"]) == (2003, 2004) for pair in pairs))
        for pair in pairs:
            self.assertAlmostEqual(
                float(pair["within_effect"]) + float(pair["composition_effect"]),
                float(pair["total_change"]),
                places=6,
            )

    def test_top_countries_min_years_sensitivity(self):
        default_top = get_top_countries_by_years(10, 1950, 2005, 10)
        self.assertEqual(default_top[0]["entity"], "Lithuania")
        low_threshold_top = get_top_countries_by_years(3, 1950, 2005, 10)
        self.assertTrue(any(row["entity"] == "Guyana" for row in low_threshold_top))

    def test_findings_register_shape(self):
        findings = get_findings()
        self.assertEqual(len(findings), 7)
        self.assertEqual(findings[0]["number"], 1)
        for finding in findings:
            self.assertTrue(
                {"number", "title", "detail", "caveat", "confidence", "section"} <= set(finding)
            )


if __name__ == "__main__":
    unittest.main()
