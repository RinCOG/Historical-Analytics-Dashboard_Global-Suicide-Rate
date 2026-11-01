from __future__ import annotations

import json
from functools import lru_cache

import pandas as pd

from backend.analysis import FORMER_STATES, MIN_TOP_COUNTRY_YEARS, OUTPUT_PATH, analyze
from backend.db import connect


def _query(sql: str, params: tuple = ()) -> pd.DataFrame:
    connection = connect()
    try:
        return pd.read_sql_query(sql, connection, params=params)
    finally:
        connection.close()


def _date_where(start: int, end: int) -> tuple[str, tuple[int, int]]:
    return "year BETWEEN ? AND ?", (start, end)


@lru_cache(maxsize=64)
def get_kpis(start: int = 1950, end: int = 2005) -> dict:
    rows = _query(
        "SELECT AVG(rate) AS global_avg, COUNT(DISTINCT entity) AS country_count FROM suicide_rates WHERE year BETWEEN ? AND ?",
        (start, end),
    )
    trend = get_global_trend(start, end)
    peak = max(trend, key=lambda row: row["avg_rate"])
    top = get_top_countries(1, start, end)
    return {
        "global_avg": float(rows.iloc[0]["global_avg"] or 0),
        "peak_year": int(peak["year"]),
        "peak_value": float(peak["avg_rate"]),
        "top_country": top[0] if top else None,
        "country_count": int(rows.iloc[0]["country_count"]),
    }


@lru_cache(maxsize=128)
def get_global_trend(start: int = 1950, end: int = 2005) -> list[dict]:
    frame = _query(
        """
        SELECT year, AVG(rate) AS avg_rate, COUNT(DISTINCT entity) AS countries_reporting
        FROM suicide_rates WHERE year BETWEEN ? AND ? GROUP BY year ORDER BY year
        """,
        (start, end),
    )
    return [
        {"year": int(row.year), "avg_rate": float(row.avg_rate), "countries_reporting": int(row.countries_reporting)}
        for row in frame.itertuples()
    ]


@lru_cache(maxsize=128)
def get_top_countries(n: int = 10, start: int = 1950, end: int = 2005) -> list[dict]:
    placeholders = ",".join("?" for _ in FORMER_STATES)
    excluded = tuple(FORMER_STATES.values())
    frame = _query(
        f"""
        SELECT entity, AVG(rate) AS avg_rate, COUNT(*) AS years_reported
        FROM suicide_rates
        WHERE year BETWEEN ? AND ? AND code NOT IN ({placeholders})
        GROUP BY entity HAVING COUNT(*) >= ?
        ORDER BY avg_rate DESC, entity ASC LIMIT ?
        """,
        (start, end, *excluded, MIN_TOP_COUNTRY_YEARS, n),
    )
    return [
        {"entity": row.entity, "avg_rate": float(row.avg_rate), "years_reported": int(row.years_reported)}
        for row in frame.itertuples()
    ]


@lru_cache(maxsize=1)
def get_countries() -> list[dict]:
    frame = _query("SELECT entity, code FROM suicide_rates GROUP BY entity, code ORDER BY entity")
    return [{"entity": row.entity, "code": row.code} for row in frame.itertuples()]


@lru_cache(maxsize=256)
def get_compare(entity: str, start: int = 1950, end: int = 2005) -> list[dict]:
    if not _query("SELECT 1 FROM suicide_rates WHERE entity = ? LIMIT 1", (entity,)).shape[0]:
        raise KeyError(entity)
    frame = _query(
        """
        WITH yearly AS (
            SELECT year, AVG(rate) AS global_avg FROM suicide_rates
            WHERE year BETWEEN ? AND ? GROUP BY year
        )
        SELECT country.year, country.rate AS country_rate, yearly.global_avg
        FROM suicide_rates AS country JOIN yearly ON yearly.year = country.year
        WHERE country.entity = ? ORDER BY country.year
        """,
        (start, end, entity),
    )
    return [
        {"year": int(row.year), "country_rate": float(row.country_rate), "global_avg": float(row.global_avg)}
        for row in frame.itertuples()
    ]


@lru_cache(maxsize=128)
def get_anomalies(entity: str | None = None, method: str = "zscore", threshold: float = 2.0) -> list[dict]:
    if entity and not _query("SELECT 1 FROM suicide_rates WHERE entity = ? LIMIT 1", (entity,)).shape[0]:
        raise KeyError(entity)
    frame = _query(
        """
        SELECT entity, year, rate,
               rate - LAG(rate) OVER (PARTITION BY entity ORDER BY year) AS change,
               year - LAG(year) OVER (PARTITION BY entity ORDER BY year) AS year_diff
        FROM suicide_rates ORDER BY entity, year
        """
    )
    frame = frame[(frame["year_diff"] == 1) & frame["change"].notna()].copy()
    if frame.empty:
        return []
    if method == "zscore":
        standard_deviation = frame["change"].std(ddof=1)
        frame["score"] = (frame["change"] - frame["change"].mean()) / standard_deviation
        flagged = frame[frame["score"].abs() > threshold]
    else:
        q1, q3 = frame["change"].quantile([0.25, 0.75])
        spread = q3 - q1
        frame["score"] = (frame["change"] - frame["change"].mean()) / frame["change"].std(ddof=1)
        flagged = frame[(frame["change"] < q1 - 1.5 * spread) | (frame["change"] > q3 + 1.5 * spread)]
    if entity:
        flagged = flagged[flagged["entity"] == entity]
    return [
        {
            "entity": row.entity,
            "year": int(row.year),
            "change": float(row.change),
            "z_score": float(row.score),
        }
        for row in flagged.sort_values(["year", "entity"]).itertuples()
    ]


@lru_cache(maxsize=128)
def get_coverage(start: int = 1950, end: int = 2005, limit: int = 250, offset: int = 0) -> list[dict]:
    frame = _query(
        """
        SELECT entities.entity, COUNT(rates.year) AS years_reported,
               MIN(rates.year) AS first_year, MAX(rates.year) AS last_year
        FROM (SELECT DISTINCT entity FROM suicide_rates) AS entities
        LEFT JOIN suicide_rates AS rates
          ON rates.entity = entities.entity AND rates.year BETWEEN ? AND ?
        GROUP BY entities.entity ORDER BY years_reported DESC, entities.entity
        LIMIT ? OFFSET ?
        """,
        (start, end, limit, offset),
    )
    result = []
    for row in frame.itertuples():
        has_observations = int(row.years_reported) > 0
        possible_years = int(row.last_year) - int(row.first_year) + 1 if has_observations else 0
        result.append(
            {
                "entity": row.entity,
                "years_reported": int(row.years_reported),
                "first_year": int(row.first_year) if has_observations else None,
                "last_year": int(row.last_year) if has_observations else None,
                "gaps": possible_years - int(row.years_reported),
            }
        )
    return result


@lru_cache(maxsize=1)
def get_insights() -> list[dict]:
    path = OUTPUT_PATH
    if not path.exists():
        raise FileNotFoundError(f"Analysis report not found at {path}; run `python -m backend.analysis` first.")
    return json.loads(path.read_text(encoding="utf-8"))["insights"]



def _frame_between(start: int, end: int) -> pd.DataFrame:
    return _query(
        "SELECT entity, code, year, rate FROM suicide_rates WHERE year BETWEEN ? AND ? ORDER BY entity, year",
        (start, end),
    )


@lru_cache(maxsize=64)
def _analysis_frame() -> pd.DataFrame:
    return _query("SELECT entity, code, year, rate FROM suicide_rates ORDER BY entity, year")


@lru_cache(maxsize=64)
def _analysis_report() -> dict:
    return analyze(_analysis_frame())


@lru_cache(maxsize=64)
def get_analysis_quality() -> dict:
    report = _analysis_report()
    return {
        "row_count": int(report["row_count"]),
        "entity_count": int(report["entity_count"]),
        "iso_entity_count": int(report["iso_entity_count"]),
        "former_state_entities": report["former_state_entities"],
        "quality": report["quality"],
        "summary": report["summary"],
        "coverage": report["coverage"],
        "coverage_count_distribution": report["coverage_count_distribution"],
    }


@lru_cache(maxsize=64)
def get_rate_distribution() -> dict:
    report = _analysis_report()
    frame = _analysis_frame()
    quality = report["quality"]
    lower_fence = float(quality["rate_iqr_fences"][0])
    upper_fence = float(quality["rate_iqr_fences"][1])
    outlier_rows = [
        {
            "entity": str(row.entity),
            "code": str(row.code),
            "year": int(row.year),
            "rate": float(row.rate),
        }
        for row in frame[(frame["rate"] < lower_fence) | (frame["rate"] > upper_fence)].sort_values(["entity", "year"]).itertuples()
    ]
    return {
        "histogram": report["rate_histogram"],
        "outliers": outlier_rows,
        "rate_iqr_fences": [lower_fence, upper_fence],
        "summary": report["summary"],
    }


@lru_cache(maxsize=256)
def get_top_countries_by_years(min_years: int = MIN_TOP_COUNTRY_YEARS, start: int = 1950, end: int = 2005, n: int = 10) -> list:
    frame = _frame_between(start, end)
    counted = frame.groupby(["entity", "code"], as_index=False).agg(
        avg_rate=("rate", "mean"),
        years_reported=("year", "nunique"),
    )
    eligible = counted[counted["years_reported"] >= min_years]
    filtered = eligible[~eligible["code"].isin(FORMER_STATES.values())]
    top = filtered.sort_values(["avg_rate", "entity"], ascending=[False, True]).head(n)
    return [
        {"entity": str(row.entity), "avg_rate": float(row.avg_rate), "years_reported": int(row.years_reported)}
        for row in top.itertuples()
    ]


@lru_cache(maxsize=64)
def get_trend_methods(start: int = 1950, end: int = 2005) -> dict:
    frame = _frame_between(start, end)

    def series(rows_frame: pd.DataFrame) -> list:
        grouped = rows_frame.groupby("year")["rate"].mean().reset_index().rename(columns={"rate": "avg_rate"})
        counts = frame.groupby("year")["entity"].nunique().rename("countries_reporting").reset_index()
        merged = grouped.merge(counts, on="year")
        return [
            {
                "year": int(row.year),
                "avg_rate": float(row.avg_rate),
                "countries_reporting": int(row.countries_reporting),
            }
            for row in merged.sort_values("year").itertuples()
        ]

    medians = frame.groupby("year")["rate"].median().reset_index().rename(columns={"rate": "avg_rate"})
    median_counts = frame.groupby("year")["entity"].nunique().rename("countries_reporting").reset_index()
    median_series = []
    for row in medians.merge(median_counts, on="year").sort_values("year").itertuples():
        median_series.append(
            {
                "year": int(row.year),
                "avg_rate": float(row.avg_rate),
                "countries_reporting": int(row.countries_reporting),
            }
        )

    observed = frame.groupby("entity")["year"].apply(set)
    year_list = list(range(start, end + 1))
    panel_entities = sorted(
        str(entity) for entity, years in observed.items() if set(year_list).issubset({int(value) for value in years})
    )
    wide_entities = sorted(
        str(entity) for entity, years in frame.groupby("entity")["year"].apply(set).items() if len(years) >= 40
    )

    reporting_counts = [
        {
            "year": int(row.year),
            "countries_reporting": int(row.countries_reporting),
        }
        for row in frame.groupby("year")["entity"].nunique().rename("countries_reporting").reset_index().sort_values("year").itertuples()
    ]

    return {
        "from": start,
        "to": end,
        "yearly": series(frame),
        "fixed_panel": series(frame[frame["entity"].isin(panel_entities)]) if panel_entities else [],
        "wide_panel": series(frame[frame["entity"].isin(wide_entities)]) if wide_entities else [],
        "median": median_series,
        "reporting_counts": reporting_counts,
        "panel_entities": panel_entities,
    }


@lru_cache(maxsize=64)
def get_decomposition(entity: str, start: int = 1950, end: int = 2005) -> dict:
    frame = _frame_between(start, end)
    target = str(entity)
    target_years = sorted({int(r.year) for r in frame[frame["entity"] == target].itertuples()})
    pairs = []
    for y1, y2 in [(2000, 2002), (2003, 2004)]:
        if y1 in target_years and y2 in target_years and start <= y1 and y2 <= end:
            pairs.append((y1, y2))
    target_year_set = set(target_years)
    for year in sorted(target_year_set):
        if (year + 1) in target_year_set and start <= year and year + 1 <= end:
            pair = (year, year + 1)
            if pair not in pairs:
                pairs.append(pair)
    pairs = sorted(set(pairs))

    rates: dict = {}
    for row in frame.itertuples():
        rates[(str(row.entity), int(row.year))] = float(row.rate)

    results = []
    for y1, y2 in pairs:
        mean_1 = float(frame.loc[frame["year"] == y1, "rate"].mean()) if bool((frame["year"] == y1).any()) else None
        mean_2 = float(frame.loc[frame["year"] == y2, "rate"].mean()) if bool((frame["year"] == y2).any()) else None
        if mean_1 is None or mean_2 is None:
            continue
        total_change = float(mean_2 - mean_1)
        entities_y1 = {str(r.entity) for r in frame[frame["year"] == y1].itertuples()}
        entities_y2 = {str(r.entity) for r in frame[frame["year"] == y2].itertuples()}
        common_entities = entities_y1 & entities_y2
        within_values = []
        for entity_name in common_entities:
            rate_1 = rates.get((entity_name, y1))
            rate_2 = rates.get((entity_name, y2))
            if rate_1 is not None and rate_2 is not None:
                within_values.append(rate_2 - rate_1)
        within_effect = float(sum(within_values) / len(within_values)) if within_values else 0.0
        results.append(
            {
                "from_year": int(y1),
                "to_year": int(y2),
                "total_change": float(total_change),
                "within_effect": float(within_effect),
                "composition_effect": float(total_change - within_effect),
                "countries_in_both": int(len(common_entities)),
            }
        )
    return {"entity": target, "pairs": results}


@lru_cache(maxsize=64)
def get_compare_multi(entities: tuple, start: int = 1950, end: int = 2005) -> list:
    frame = _frame_between(start, end)
    global_means = {
        int(row.year): float(row.avg_rate)
        for row in frame.groupby("year")["rate"].mean().reset_index().rename(columns={"rate": "avg_rate"}).itertuples()
    }
    observed = frame.groupby("entity")["year"].apply(set)
    year_list = list(range(start, end + 1))
    panel_entities = sorted(
        str(entity) for entity, years in observed.items() if set(year_list).issubset({int(value) for value in years})
    )
    panel_means: dict = {}
    if panel_entities:
        panel = frame[frame["entity"].isin(panel_entities)]
        for row in panel.groupby("year")["rate"].mean().reset_index().rename(columns={"rate": "avg_rate"}).itertuples():
            panel_means[int(row.year)] = float(row.avg_rate)
    for entity in entities:
        if not _query("SELECT 1 FROM suicide_rates WHERE entity = ? LIMIT 1", (entity,)).shape[0]:
            raise KeyError(entity)
    rows = []
    for entity in entities:
        entity_frame = frame[frame["entity"] == entity]
        for row in entity_frame.sort_values("year").itertuples():
            year = int(row.year)
            rows.append(
                {
                    "entity": str(entity),
                    "year": year,
                    "country_rate": float(row.rate),
                    "global_avg": float(global_means.get(year, 0.0)),
                    "panel_avg": float(panel_means.get(year, 0.0)),
                }
            )
    return rows


@lru_cache(maxsize=64)
def get_anomaly_summary() -> dict:
    report = _analysis_report()
    anomalies = report["anomalies"]
    return {
        "consecutive_changes": int(anomalies["consecutive_changes"]),
        "change_mean": float(anomalies["change_mean"]),
        "change_std": float(anomalies["change_std"]),
        "iqr_change_fences": anomalies["iqr_change_fences"],
        "zscore_count": int(anomalies["zscore_count"]),
        "iqr_count": int(anomalies["iqr_count"]),
        "both_count": int(anomalies["both_count"]),
        "flagged_rows": anomalies["rows"],
    }


@lru_cache(maxsize=64)
def get_coverage_deep() -> dict:
    report = _analysis_report()
    return {
        "coverage": report["coverage"],
        "coverage_count_distribution": report["coverage_count_distribution"],
        "summary": report["summary"],
    }


@lru_cache(maxsize=64)
def get_findings() -> list:
    report = _analysis_report()
    findings = []
    for index, insight in enumerate(report["insights"]):
        findings.append(
            {
                "number": index + 1,
                "title": insight["title"],
                "detail": insight["detail"],
                "caveat": insight["caveat"],
                "confidence": "High",
                "section": "overview",
            }
        )
    return findings
