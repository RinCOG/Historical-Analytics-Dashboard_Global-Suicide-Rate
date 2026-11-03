from __future__ import annotations

"""Shared metric registry for the dashboard and the in-depth page.

The registry is generated offline from the analysis report and the relationship
payload.  It gives both pages one place to look up a metric's label, value,
unit, number format, caveat, and verdict.  Request-time endpoints read the
stored JSON; they never recalculate a displayed shared value.
"""

import json
from pathlib import Path

from backend.analysis import OUTPUT_PATH
from backend.relationships import RELATIONSHIPS_PATH

ROOT = Path(__file__).resolve().parents[1]
REGISTRY_PATH = ROOT / "data" / "metric_registry.json"

LABELS = {
    "observation_mean": "Observation mean",
    "median": "Median",
    "peak_year": "Peak year",
    "peak_value": "Peak year average",
    "top_eligible_country": "Top eligible country",
    "entities_with_reported_rates": "Entities with reported rates",
    "entities": "Entities",
    "records": "Records",
    "coverage_years": "Years reported",
    "country_mean": "Country mean",
    "year_range": "Period",
    "relationship_pearson": "Pearson r",
    "relationship_spearman": "Spearman rho",
    "relationship_n": "n",
    "zscore": "z-score",
    "anomaly_flags": "Anomaly flags",
}

FORMATS = {
    "rate2": {"id": "rate2", "description": "Two decimals, per 100,000", "example": "11.95"},
    "zscore3": {"id": "zscore3", "description": "Three decimals", "example": "1.999"},
    "count0": {"id": "count0", "description": "Whole count with no decimals", "example": "2,843"},
    "year": {"id": "year", "description": "Four-digit year", "example": "1982"},
    "text": {"id": "text", "description": "Entity or category text", "example": "Lithuania"},
    "range": {"id": "range", "description": "Year range with an en dash", "example": "1950–2005"},
    "list": {"id": "list", "description": "Structured list or table", "example": "top-10 rows"},
}

CAVEATS = {
    "coverage": (
        "Mean of all country-year observations in the selected years; coverage varies by year and this "
        "is not a fixed-population world rate."
    ),
    "peak_method": "Raw yearly mean; the peak year ranges 1982–1998 depending on method.",
    "minimum_years": "Requires at least 10 observations; rankings depend on the minimum-coverage rule.",
    "zscore_pooled": (
        "Pooled z-score screening; countries with larger natural variability can be flagged more often."
    ),
    "anomaly_descriptive": "Flags identify unusual observed changes, not errors or causes.",
    "relationships_fixed": (
        "Fixed periods; not affected by the year range. Descriptive only: no p-values, causes, or forecasts."
    ),
    "causation": "Correlation does not establish causation.",
}


def _display(value, number_format: str) -> str:
    if value is None:
        return "—"
    if number_format == "rate2":
        return f"{float(value):,.2f}"
    if number_format == "zscore3":
        return f"{float(value):.3f}"
    if number_format == "count0":
        return f"{int(round(float(value))):,}"
    if number_format == "year":
        return str(int(value))
    if number_format == "range":
        return str(value)
    return str(value)


def _metric(
    identifier: str,
    label: str,
    value,
    *,
    unit: str,
    number_format: str,
    caveat_id: str | None = None,
    anchor: str | None = None,
    source: str | None = None,
    verdict_id: str | None = None,
) -> dict:
    return {
        "id": identifier,
        "label": label,
        "value": value,
        "display": _display(value, number_format),
        "unit": unit,
        "format": number_format,
        "caveat_id": caveat_id,
        "anchor": anchor,
        "source": source,
        "verdict_id": verdict_id,
    }


def _relationship_metrics(relationships: dict) -> list[dict]:
    metrics: list[dict] = []
    block_a = relationships["block_a"]
    for row in block_a["rows"]:
        metrics.append(
            _metric(
                f"relationship.{row['id']}.pearson",
                f"{row['label']} · Pearson r",
                row["pearson"],
                unit="r",
                number_format="rate2",
                caveat_id="relationships_fixed",
                anchor="#relationships-a",
            )
        )
        metrics.append(
            _metric(
                f"relationship.{row['id']}.n",
                f"{row['label']} · n",
                row["n"],
                unit="observations",
                number_format="count0",
                caveat_id="relationships_fixed",
                anchor="#relationships-a",
            )
        )
    for key, block in relationships["block_b"].items():
        anchor = f"#relationships-{key.lower()}"
        for field in ("pearson", "spearman"):
            if block.get(field) is not None:
                metrics.append(
                    _metric(
                        f"relationship.{key}.{field}",
                        f"{block['title']} · {'Pearson r' if field == 'pearson' else 'Spearman rho'}",
                        block[field],
                        unit="r" if field == "pearson" else "rho",
                        number_format="rate2",
                        caveat_id="relationships_fixed",
                        anchor=anchor,
                        verdict_id=key,
                    )
                )
        metrics.append(
            _metric(
                f"relationship.{key}.n",
                f"{block['title']} · n",
                block["n"],
                unit="entities",
                number_format="count0",
                caveat_id="relationships_fixed",
                anchor=anchor,
                verdict_id=key,
            )
        )
        if "subset" in block:
            metrics.append(
                _metric(
                    f"relationship.{key}.subset.pearson",
                    f"{block['title']} · >=10-year subset Pearson r",
                    block["subset"]["pearson"],
                    unit="r",
                    number_format="rate2",
                    caveat_id="relationships_fixed",
                    anchor=anchor,
                    verdict_id=key,
                )
            )
    return metrics


def build_registry(report: dict, relationships: dict) -> dict:
    summary = report["summary"]
    top = report["top_countries"][0]
    metrics: list[dict] = [
        _metric("observation_mean", LABELS["observation_mean"], summary["mean"], unit="per 100,000", number_format="rate2", caveat_id="coverage", anchor="#overview"),
        _metric("median", LABELS["median"], summary["median"], unit="per 100,000", number_format="rate2", caveat_id="coverage", anchor="#overview"),
        _metric("peak_year", LABELS["peak_year"], summary["global_peak_year"], unit="year", number_format="year", caveat_id="peak_method", anchor="#trend"),
        _metric("peak_value", LABELS["peak_value"], summary["global_peak_avg_rate"], unit="per 100,000", number_format="rate2", caveat_id="peak_method", anchor="#trend"),
        _metric("peak_reporters", "Peak year reporters", summary["global_peak_countries_reporting"], unit="entities", number_format="count0", caveat_id="peak_method", anchor="#trend"),
        _metric("top_eligible_country", LABELS["top_eligible_country"], top["entity"], unit="entity", number_format="text", caveat_id="minimum_years", anchor="#top"),
        _metric("top_country_mean", "Top eligible country mean", top["avg_rate"], unit="per 100,000", number_format="rate2", caveat_id="minimum_years", anchor="#top"),
        _metric("top_country_years", "Top eligible country years", top["years_reported"], unit="years", number_format="count0", caveat_id="minimum_years", anchor="#top"),
        _metric("entity_count", LABELS["entities_with_reported_rates"], report["entity_count"], unit="entities", number_format="count0", caveat_id="coverage", anchor="#data"),
        _metric("row_count", LABELS["records"], report["row_count"], unit="country-year observations", number_format="count0", caveat_id="coverage", anchor="#data"),
        _metric("year_range", LABELS["year_range"], f"{report['period']['from']}–{report['period']['to']}", unit="years", number_format="range", caveat_id="coverage", anchor="#overview"),
        _metric(
            "top_10",
            "Top 10 eligible countries",
            [
                {
                    "rank": index + 1,
                    "entity": row["entity"],
                    "mean": row["avg_rate"],
                    "mean_display": _display(row["avg_rate"], "rate2"),
                    "years_reported": row["years_reported"],
                }
                for index, row in enumerate(report["top_countries"])
            ],
            unit="ranked rows",
            number_format="list",
            caveat_id="minimum_years",
            anchor="#top",
        ),
        _metric(
            "global_trend",
            "Global annual trend",
            report["yearly"],
            unit="annual mean and reporting count",
            number_format="list",
            caveat_id="coverage",
            anchor="#trend",
        ),
        _metric(
            "country_vs_global",
            "Country vs global baseline",
            None,
            unit="per 100,000",
            number_format="rate2",
            caveat_id="coverage",
            anchor="#compare",
            source="GET /api/v1/compare?entity=...&from=...&to=...",
        ),
        _metric("anomaly_consecutive_changes", "Consecutive changes", report["anomalies"]["consecutive_changes"], unit="year pairs", number_format="count0", caveat_id="anomaly_descriptive", anchor="#anomalies"),
        _metric("anomaly_zscore_count", "|z| > 2 flags", report["anomalies"]["zscore_count"], unit="changes", number_format="count0", caveat_id="zscore_pooled", anchor="#anomalies"),
        _metric("anomaly_iqr_count", "1.5xIQR flags", report["anomalies"]["iqr_count"], unit="changes", number_format="count0", caveat_id="anomaly_descriptive", anchor="#anomalies"),
        _metric("anomaly_both_count", "Both methods", report["anomalies"]["both_count"], unit="changes", number_format="count0", caveat_id="anomaly_descriptive", anchor="#anomalies"),
        _metric(
            "anomaly_rows",
            "Anomaly rows",
            [
                {
                    "entity": row["entity"],
                    "year": row["year"],
                    "change": row["change"],
                    "change_display": _display(row["change"], "rate2"),
                    "z_score": row["z_score"],
                    "z_score_display": _display(row["z_score"], "zscore3"),
                    "zscore_flag": row["zscore_flag"],
                    "iqr_flag": row["iqr_flag"],
                }
                for row in report["anomalies"]["rows"]
            ],
            unit="flagged rows",
            number_format="list",
            caveat_id="zscore_pooled",
            anchor="#anomalies",
        ),
        _metric(
            "coverage_rows",
            "Coverage rows",
            report["coverage"],
            unit="entities",
            number_format="list",
            caveat_id="coverage",
            anchor="#coverage",
        ),
        _metric(
            "key_insights",
            "Key insights 01–07",
            [
                {
                    "number": index + 1,
                    "title": insight["title"],
                    "detail": insight["detail"],
                    "caveat": insight["caveat"],
                }
                for index, insight in enumerate(report["insights"])
            ],
            unit="insight rows",
            number_format="list",
            caveat_id="coverage",
            anchor="#findings",
        ),
    ]
    metrics.extend(_relationship_metrics(relationships))

    verdicts = {
        "A": relationships["block_a"]["verdict"],
        "B1": relationships["block_b"]["B1"]["verdict"],
        "B2": relationships["block_b"]["B2"]["verdict"],
        "B3": relationships["block_b"]["B3"]["verdict"],
        "B4": relationships["block_b"]["B4"]["verdict"],
    }
    return {
        "version": 1,
        "source": report["source"],
        "period": report["period"],
        "labels": LABELS,
        "formats": FORMATS,
        "caveats": CAVEATS,
        "metrics": metrics,
        "verdicts": verdicts,
        "findings": [
            {
                "number": index + 1,
                "title": insight["title"],
                "detail": insight["detail"],
                "caveat": insight["caveat"],
                "confidence": "High",
                "section": "overview",
            }
            for index, insight in enumerate(report["insights"])
        ]
        + relationships["findings"],
    }


def write_registry(
    report_path: Path = OUTPUT_PATH,
    relationships_path: Path = RELATIONSHIPS_PATH,
    output: Path = REGISTRY_PATH,
) -> dict:
    if not report_path.exists():
        raise FileNotFoundError(f"Analysis report not found at {report_path}; run `python -m backend.analysis` first.")
    if not relationships_path.exists():
        raise FileNotFoundError(
            f"Relationship results not found at {relationships_path}; run `python -m backend.relationships` first."
        )
    report = json.loads(report_path.read_text(encoding="utf-8"))
    relationships = json.loads(relationships_path.read_text(encoding="utf-8"))
    registry = build_registry(report, relationships)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(registry, indent=2), encoding="utf-8")
    return registry


def load_registry() -> dict:
    if not REGISTRY_PATH.exists():
        raise FileNotFoundError(f"Metric registry not found at {REGISTRY_PATH}; run `python -m backend.registry` first.")
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def main() -> None:
    registry = write_registry()
    print(
        json.dumps(
            {
                "output": str(REGISTRY_PATH),
                "metrics": len(registry["metrics"]),
                "verdicts": {key: value["label"] for key, value in registry["verdicts"].items()},
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
