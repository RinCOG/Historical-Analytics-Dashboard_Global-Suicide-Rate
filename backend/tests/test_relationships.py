from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

import pandas as pd

from backend.analysis import CSV_PATH, analyze, load_and_validate
from backend.ingest import ingest
from backend.registry import FORMATS, build_registry
from backend.relationships import (
    VERDICT_RULES,
    _bootstrap_cluster,
    _pearson,
    _spearman,
    compact_payload,
    compute_relationships,
)
from backend.services import (
    get_alignment,
    get_compare,
    get_compare_multi,
    get_findings,
    get_insights,
    get_kpis,
    get_range_summary,
    get_relationships_compact,
    get_relationships_full,
    get_metric_registry,
)


def _close(actual: float, expected: float, tolerance: float = 0.002) -> bool:
    return abs(float(actual) - float(expected)) <= tolerance


class RelationshipComputationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.frame = load_and_validate(CSV_PATH)
        cls.payload = compute_relationships(cls.frame)

    def test_reference_values_reproduce(self):
        block_a = {row["id"]: row for row in self.payload["block_a"]["rows"]}
        self.assertEqual(block_a["A1"]["n"], 2843)
        self.assertTrue(_close(block_a["A1"]["pearson"], -0.024))
        self.assertEqual(block_a["A2"]["n"], 2216)
        self.assertTrue(_close(block_a["A2"]["pearson"], 0.086))
        self.assertEqual(block_a["A3"]["n"], 448)
        self.assertTrue(_close(block_a["A3"]["pearson"], 0.193))
        self.assertEqual(block_a["A4"]["n"], 56)
        self.assertTrue(_close(block_a["A4"]["pearson"], 0.723))
        self.assertEqual(block_a["A5"]["entities"], 32)
        self.assertEqual(block_a["A5"]["n"], 1637)
        self.assertTrue(_close(block_a["A5"]["pearson"], 0.107))

        b1 = self.payload["block_b"]["B1"]
        self.assertEqual(b1["n"], 63)
        self.assertTrue(_close(b1["pearson"], 0.924))
        self.assertTrue(_close(b1["spearman"], 0.959))

        b2 = self.payload["block_b"]["B2"]
        self.assertEqual(b2["n"], 67)
        self.assertTrue(_close(b2["pearson"], 0.946))
        self.assertTrue(_close(b2["spearman"], 0.936))

        b3 = self.payload["block_b"]["B3"]
        self.assertEqual(b3["n"], 196)
        self.assertTrue(_close(b3["pearson"], 0.228))
        self.assertTrue(_close(b3["spearman"], 0.259))
        self.assertEqual(b3["subset"]["n"], 68)
        self.assertTrue(_close(b3["subset"]["pearson"], -0.047))

        b4 = self.payload["block_b"]["B4"]
        self.assertEqual(b4["n"], 68)
        self.assertTrue(_close(b4["pearson"], 0.715))

    def test_bootstrap_is_reproducible_with_same_seed(self):
        frame = self.frame[self.frame["entity"].isin(["Australia", "Canada", "Japan", "Lithuania"])]
        statistic = lambda sample: _pearson(sample["year"], sample["rate"])
        first = _bootstrap_cluster(frame, statistic, resamples=40, seed=7)
        second = _bootstrap_cluster(frame, statistic, resamples=40, seed=7)
        different = _bootstrap_cluster(frame, statistic, resamples=40, seed=8)
        self.assertEqual(first, second)
        self.assertNotEqual(first, different)

    def test_within_country_demeaning(self):
        counts = self.frame.groupby("entity")["year"].nunique()
        panel_entities = sorted(counts[counts == 56].index)
        panel = self.frame[self.frame["entity"].isin(panel_entities)].copy()
        panel["manual"] = panel["rate"] - panel.groupby("entity")["rate"].transform("mean")
        manual_r = _pearson(panel["year"], panel["manual"])
        stored = {row["id"]: row for row in self.payload["block_a"]["rows"]}["A3"]
        self.assertTrue(_close(stored["pearson"], manual_r, tolerance=1e-6))
        self.assertTrue(_close(panel.groupby("entity")["manual"].mean().abs().max(), 0.0, tolerance=1e-9))

    def test_window_and_minimum_observation_definitions(self):
        b1 = self.payload["block_b"]["B1"]
        self.assertEqual(b1["windows"], {"x": [1980, 1989], "y": [1990, 1999]})
        self.assertEqual(b1["sensitivity"][0]["n"], 55)
        self.assertEqual(b1["sensitivity"][1]["n"], 58)
        b2 = self.payload["block_b"]["B2"]
        self.assertEqual(b2["windows"], {"x": [1990, 1999], "y": [2000, 2005]})
        self.assertEqual(b2["sensitivity"][0]["n"], 63)
        self.assertEqual(b2["sensitivity"][1]["n"], 66)
        b3 = self.payload["block_b"]["B3"]
        self.assertEqual(b3["cutoff"], 10)
        self.assertEqual(b3["subset"]["n"], 68)
        b4 = self.payload["block_b"]["B4"]
        self.assertEqual(b4["n"], 68)
        self.assertTrue(all(point["x_obs"] >= 10 for point in b4["points"]))

    def test_verdict_rules_and_thresholds_are_documented(self):
        verdicts = {
            "A": self.payload["block_a"]["verdict"],
            **{key: self.payload["block_b"][key]["verdict"] for key in ("B1", "B2", "B3", "B4")},
        }
        self.assertEqual(verdicts["A"]["label"], "Not Favourable")
        self.assertEqual(verdicts["B1"]["label"], "Favourable")
        self.assertEqual(verdicts["B2"]["label"], "Favourable")
        self.assertEqual(verdicts["B3"]["label"], "Mixed")
        self.assertEqual(verdicts["B4"]["label"], "Not Favourable")
        for identifier, verdict in verdicts.items():
            self.assertEqual(verdict["judged_on"], "Data reliability")
            self.assertIn(verdict["label"], {"Favourable", "Not Favourable", "Mixed"})
            self.assertIn(identifier, VERDICT_RULES)
            self.assertTrue(verdict["rule"])
            self.assertTrue(verdict["reason"])

    def test_takeaways_are_generated_from_stored_numbers(self):
        takeaways = self.payload["takeaways"]
        self.assertIn(f"{self.payload['block_b']['B1']['pearson']:.2f}", takeaways["B1"])
        self.assertIn(f"{self.payload['block_b']['B3']['subset']['pearson']:.2f}", takeaways["B3"])
        self.assertIn(f"{self.payload['block_b']['B4']['pearson']:.2f}", takeaways["B4"])

    def test_anomaly_sensitivity_does_not_change_existing_table(self):
        sensitivity = self.payload["anomaly_sensitivity"]
        self.assertEqual(sensitivity["consecutive_changes"], 2457)
        self.assertEqual(sensitivity["pooled_zscore_flags"], 122)
        self.assertEqual(sensitivity["within_country_zscore_flags"], 124)
        self.assertEqual(sensitivity["status_changes"], 154)


class RelationshipContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.db_path = Path(cls.temp_dir.name) / "test.sqlite"
        ingest(CSV_PATH, cls.db_path)
        cls.previous_db_path = os.environ.get("DATABASE_PATH")
        os.environ["DATABASE_PATH"] = str(cls.db_path)
        for function in (
            get_alignment,
            get_compare,
            get_compare_multi,
            get_findings,
            get_insights,
            get_kpis,
            get_range_summary,
            get_relationships_compact,
            get_relationships_full,
            get_metric_registry,
        ):
            function.cache_clear()

    @classmethod
    def tearDownClass(cls):
        if cls.previous_db_path is None:
            os.environ.pop("DATABASE_PATH", None)
        else:
            os.environ["DATABASE_PATH"] = cls.previous_db_path
        cls.temp_dir.cleanup()

    def test_compact_and_full_payloads_share_every_number(self):
        full = get_relationships_full()
        compact = get_relationships_compact()
        for key in ("A1", "A2", "A3", "A4"):
            full_row = {row["id"]: row for row in full["block_a"]["rows"]}[key]
            compact_row = {row["id"]: row for row in compact["block_a"]["rows"]}[key]
            self.assertEqual(full_row["n"], compact_row["n"])
            self.assertEqual(full_row["pearson"], compact_row["pearson"])
            self.assertEqual(full_row["pearson_ci"], compact_row["pearson_ci"])
        for key in ("B1", "B3", "B4"):
            for field in ("n", "pearson", "pearson_ci", "spearman", "spearman_ci"):
                self.assertEqual(full["block_b"][key][field], compact["block_b"][key][field])
        self.assertEqual(full["block_a"]["verdict"], compact["block_a"]["verdict"])
        for key in ("B1", "B3", "B4"):
            self.assertEqual(full["block_b"][key]["verdict"], compact["block_b"][key]["verdict"])

    def test_dashboard_and_indepth_headline_values_match(self):
        for start, end in ((1950, 2005), (1980, 1995), (1960, 1970)):
            kpis = get_kpis(start, end)
            summary = get_range_summary(start, end)
            self.assertTrue(_close(kpis["global_avg"], summary["mean"], 0.0005))
            self.assertEqual(kpis["peak_year"], summary["peak_year"])
            self.assertTrue(_close(kpis["peak_value"], summary["peak_value"], 0.0005))
            self.assertEqual(kpis["country_count"], summary["entity_count"])
            self.assertEqual(kpis["top_country"], summary["top_country"])

    def test_comparison_global_baseline_is_identical(self):
        for entity in ("Lithuania", "Japan", "Mauritius", "Guyana", "Dominica"):
            for start, end in ((1950, 2005), (1980, 1995)):
                dashboard = {row["year"]: row for row in get_compare(entity, start, end)}
                deep = {row["year"]: row for row in get_compare_multi((entity,), start, end)}
                for year, row in dashboard.items():
                    self.assertIn(year, deep)
                    self.assertTrue(_close(row["global_avg"], deep[year]["global_avg"], 1e-9))
                    self.assertTrue(_close(row["country_rate"], deep[year]["country_rate"], 1e-9))

    def test_key_insights_1_to_7_equal_findings_1_to_7(self):
        insights = get_insights()
        findings = get_findings()
        self.assertEqual(len(insights), 7)
        self.assertEqual(len(findings), 11)
        for index, insight in enumerate(insights):
            self.assertEqual(insight["title"], findings[index]["title"])
            self.assertEqual(insight["detail"], findings[index]["detail"])
            self.assertEqual(insight["caveat"], findings[index]["caveat"])
        self.assertEqual([row["number"] for row in findings[7:]], [8, 9, 10, 11])
        self.assertTrue(all(row["section"] == "relationships" for row in findings[7:]))

    def test_alignment_contract_payload(self):
        alignment = get_alignment(1950, 2005, "Lithuania")
        self.assertTrue(alignment["comparison_global_baseline_equal"])
        self.assertEqual(alignment["key_insights"], alignment["findings_1_to_7"])
        self.assertEqual(alignment["relationships_compact"]["block_b"]["B1"]["n"], 63)
        self.assertEqual(alignment["relationships_full"]["block_b"]["B1"]["n"], 63)

    def test_registry_values_and_formats(self):
        registry = get_metric_registry()
        metrics = {metric["id"]: metric for metric in registry["metrics"]}
        self.assertEqual(metrics["observation_mean"]["display"], "11.95")
        self.assertEqual(metrics["median"]["display"], "10.64")
        self.assertEqual(metrics["peak_year"]["display"], "1982")
        self.assertEqual(metrics["peak_value"]["display"], "14.76")
        self.assertEqual(metrics["top_eligible_country"]["display"], "Lithuania")
        self.assertEqual(metrics["entity_count"]["display"], "196")
        self.assertEqual(metrics["relationship.B1.pearson"]["display"], "0.92")
        self.assertEqual(metrics["relationship.B1.n"]["display"], "63")
        for metric in registry["metrics"]:
            self.assertIn(metric["format"], FORMATS)
        self.assertEqual(registry["verdicts"]["B1"]["label"], "Favourable")
        self.assertEqual(registry["verdicts"]["A"]["judged_on"], "Data reliability")
        self.assertEqual(registry["labels"]["observation_mean"], "Observation mean")
        self.assertEqual(registry["labels"]["top_eligible_country"], "Top eligible country")
        self.assertEqual(registry["labels"]["entities_with_reported_rates"], "Entities with reported rates")

    def test_shared_formatter_is_used_by_both_pages(self):
        frontend = Path(__file__).resolve().parents[2] / "frontend" / "src"
        shared = (frontend / "shared.ts").read_text(encoding="utf-8")
        app = (frontend / "App.tsx").read_text(encoding="utf-8")
        analysis = (frontend / "Analysis.tsx").read_text(encoding="utf-8")
        relationships = (frontend / "RelationshipViews.tsx").read_text(encoding="utf-8")
        for format_id in FORMATS:
            self.assertIn(format_id, shared)
        for source in (app, analysis, relationships):
            self.assertIn("from './shared'", source)
        self.assertIn("formatRate", app)
        self.assertIn("formatRate", analysis)
        self.assertIn("formatRate", relationships)


if __name__ == "__main__":
    unittest.main()
