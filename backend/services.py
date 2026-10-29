from __future__ import annotations

import json
from functools import lru_cache

import pandas as pd

from backend.analysis import FORMER_STATES, MIN_TOP_COUNTRY_YEARS, OUTPUT_PATH
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
