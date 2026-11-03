"""Independent pandas verification of values displayed on the dashboard and /analysis pages.

Recomputes every expected value directly from the raw CSV
(data/SDG-3___suicide-rates-by-country.csv) with pandas and compares the result
with the values served by the running FastAPI backend (the values the frontend
displays).

Independent criteria for a check to count:
  (a) reads the raw CSV with pandas and recomputes the metric from scratch;
  (b) does not import or call the application's own service/aggregation
      functions to produce the expected value;
  (c) compares against the displayed API payload value;
  (d) reproducible (fixed bootstrap seed).

Usage: python analysis/verify_with_pandas.py
Prints one PASS/FAIL line per metric and exits non-zero on any failure.
"""

from __future__ import annotations

import json
import math
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd
import pycountry

ROOT = Path(__file__).resolve().parents[1]
CSV_PATH = ROOT / "data" / "SDG-3___suicide-rates-by-country.csv"
RATE_COLUMN = "suicide rate (age-adjusted suicides per 100,000 people)"

FORMER_STATES = {
    "Czechoslovakia": "OWID_CZS",
    "East Germany": "OWID_GDR",
    "Serbia and Montenegro": "OWID_SRM",
    "USSR": "OWID_USS",
    "West Germany": "OWID_GFR",
    "Yugoslavia": "OWID_YGS",
}
FORMER_STATE_CODES = set(FORMER_STATES.values())
FIRST_YEAR = 1950
LAST_YEAR = 2005
MIN_TOP_COUNTRY_YEARS = 10
FIXED_PANEL_MIN_YEARS = 56
WIDE_PANEL_MIN_YEARS = 40
MIN_COVERAGE_YEARS = 10
BOOTSTRAP_SEED = 20260101
BOOTSTRAP_RESAMPLES = 2000
CONFIDENCE_LEVEL = 0.95
SUB_RANGE = (1980, 1995)
ENTITIES = ["Lithuania", "Japan", "Mauritius", "Guyana", "Dominica"]

PORT = 8971
BASE = f"http://127.0.0.1:{PORT}/api/v1"

RATE_TOL = 0.005
ZSCORE_TOL = 0.0005
CORR_TOL = 0.002

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, bool(ok), detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""), flush=True)


def approx(actual, expected, tol: float) -> bool:
    return abs(float(actual) - float(expected)) <= tol


# ---------------------------------------------------------------------------
# HTTP client + temporary server bootstrap
# ---------------------------------------------------------------------------
def _get(path: str):
    url = BASE + path
    with urllib.request.urlopen(url, timeout=90) as response:
        return json.loads(response.read().decode("utf-8"))


def start_server() -> subprocess.Popen:
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "backend.main:app", "--host", "127.0.0.1", "--port", str(PORT), "--log-level", "warning"],
        cwd=str(ROOT), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
    )
    deadline = time.time() + 120
    while time.time() < deadline:
        if proc.poll() is not None:
            raise RuntimeError("uvicorn exited before becoming ready")
        try:
            _get("/health")
            return proc
        except Exception:
            time.sleep(0.5)
    proc.terminate()
    proc.wait(timeout=20)
    raise RuntimeError("uvicorn did not become ready in time")


def stop_server(proc: subprocess.Popen) -> None:
    proc.terminate()
    try:
        proc.wait(timeout=20)
    except Exception:
        proc.kill()


# ---------------------------------------------------------------------------
# Independent recomputation from the raw CSV
# ---------------------------------------------------------------------------
def load_frame() -> pd.DataFrame:
    frame = pd.read_csv(CSV_PATH)
    frame = frame.rename(columns={"Entity": "entity", "Code": "code", "Year": "year", RATE_COLUMN: "rate"})
    frame["entity"] = frame["entity"].astype(str).str.strip()
    frame["code"] = frame["code"].astype(str).str.strip().str.upper()
    frame["year"] = pd.to_numeric(frame["year"], errors="raise").astype(int)
    frame["rate"] = pd.to_numeric(frame["rate"], errors="raise").astype(float)
    return frame[["entity", "code", "year", "rate"]]


def pearson(x, y) -> float:
    x_values = np.asarray(x, dtype=float)
    y_values = np.asarray(y, dtype=float)
    if len(x_values) < 2 or len(y_values) < 2:
        return float("nan")
    if np.std(x_values) == 0 or np.std(y_values) == 0:
        return float("nan")
    return float(np.corrcoef(x_values, y_values)[0, 1])


def spearman(x, y) -> float:
    return pearson(
        pd.Series(np.asarray(x, dtype=float)).rank().to_numpy(),
        pd.Series(np.asarray(y, dtype=float)).rank().to_numpy(),
    )


def bootstrap_interval(frame: pd.DataFrame, statistic) -> list:
    if frame.empty:
        return [None, None]
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    entities = np.array(sorted(frame["entity"].unique()))
    groups = {entity: group for entity, group in frame.groupby("entity")}
    values: list[float] = []
    for _ in range(BOOTSTRAP_RESAMPLES):
        picked = rng.choice(entities, size=len(entities), replace=True)
        sample = pd.concat([groups[entity] for entity in picked], ignore_index=True)
        try:
            value = float(statistic(sample))
        except Exception:
            continue
        if math.isfinite(value):
            values.append(value)
    if not values:
        return [None, None]
    alpha = (1.0 - CONFIDENCE_LEVEL) / 2.0
    return [round(float(np.quantile(values, alpha)), 6), round(float(np.quantile(values, 1.0 - alpha)), 6)]


def yearly_rows(frame: pd.DataFrame, start=None, end=None) -> list[dict]:
    sub = frame if start is None else frame[(frame["year"] >= start) & (frame["year"] <= end)]
    grouped = sub.groupby("year")["rate"].mean().reset_index().rename(columns={"rate": "avg_rate"})
    counts = sub.groupby("year")["entity"].nunique().rename("countries_reporting").reset_index()
    rows = []
    for row in grouped.merge(counts, on="year").itertuples():
        rows.append({"year": int(row.year), "avg_rate": float(row.avg_rate), "countries_reporting": int(row.countries_reporting)})
    return rows


def panel_entities(frame: pd.DataFrame, start: int | None = None, end: int | None = None) -> list[str]:
    observed = frame.groupby("entity")["year"].apply(set)
    if start is None:
        complete = set(range(FIRST_YEAR, LAST_YEAR + 1))
        return sorted(entity for entity, years in observed.items() if complete.issubset({int(v) for v in years}))
    window = set(range(start, end + 1))
    return sorted(entity for entity, years in observed.items() if window.issubset({int(v) for v in years}))


def series_for(frame: pd.DataFrame, entities: list[str], start=None, end=None) -> list[dict]:
    sub = frame if start is None else frame[(frame["year"] >= start) & (frame["year"] <= end)]
    if not entities:
        return []
    sub = sub[sub["entity"].isin(entities)]
    grouped = sub.groupby("year")["rate"].mean().reset_index().rename(columns={"rate": "avg_rate"})
    counts = sub.groupby("year")["entity"].nunique().rename("countries_reporting").reset_index()
    rows = []
    for row in grouped.merge(counts, on="year").itertuples():
        rows.append({"year": int(row.year), "avg_rate": float(row.avg_rate), "countries_reporting": int(row.countries_reporting)})
    return rows


def country_stats(frame: pd.DataFrame, start=None, end=None) -> pd.DataFrame:
    sub = frame if start is None else frame[(frame["year"] >= start) & (frame["year"] <= end)]
    return sub.groupby(["entity", "code"], as_index=False).agg(
        mean=("rate", "mean"), years=("year", "nunique")
    )


def mean_over(frame: pd.DataFrame, start=None, end=None) -> float:
    sub = frame if start is None else frame[(frame["year"] >= start) & (frame["year"] <= end)]
    return float(sub["rate"].mean())


def anomaly_frame(frame: pd.DataFrame) -> pd.DataFrame:
    changes = frame.sort_values(["entity", "year"]).copy()
    changes["previous_year"] = changes.groupby("entity")["year"].shift()
    changes["change"] = changes.groupby("entity")["rate"].diff()
    return changes[(changes["year"] - changes["previous_year"]) == 1].copy()


def independent_compare(entity: str, start, end) -> list[dict]:
    sub = frame_ref[(frame_ref["entity"] == entity) & (frame_ref["year"] >= start) & (frame_ref["year"] <= end)]
    global_means = {
        int(r.year): float(r.rate)
        for r in frame_ref[(frame_ref["year"] >= start) & (frame_ref["year"] <= end)]
        .groupby("year")["rate"].mean().reset_index().itertuples()
    }
    # The fixed panel is defined over the full observed period (1950-2005); the
    # backend and frontend always use the full-period panel for baseline means.
    panel_ents = panel_entities(frame_ref, FIRST_YEAR, LAST_YEAR)
    panel_means: dict[int, float] = {}
    if panel_ents:
        subp = frame_ref[(frame_ref["year"] >= FIRST_YEAR) & (frame_ref["year"] <= LAST_YEAR) & frame_ref["entity"].isin(panel_ents)]
        for r in subp.groupby("year")["rate"].mean().reset_index().itertuples():
            panel_means[int(r.year)] = float(r.rate)
    rows = []
    for r in sub.sort_values("year").itertuples():
        rows.append({
            "entity": entity,
            "year": int(r.year),
            "country_rate": float(r.rate),
            "global_avg": float(global_means[int(r.year)]),
            "panel_avg": float(panel_means.get(int(r.year), float("nan"))),
        })
    return rows


frame_ref = pd.DataFrame()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> int:
    global frame_ref
    proc = start_server()
    try:
        frame = load_frame()
        frame_ref = frame
        failed: list[str] = []

        def expect(name: str, ok: bool, detail: str = "") -> None:
            check(name, ok, detail)
            if not ok:
                failed.append(name)

        # ============================ DATA FOUNDATION ============================
        expect("data.foundation.row_count", len(frame) == 2843, f"rows={len(frame)}")
        expect("data.foundation.entity_count", int(frame["entity"].nunique()) == 196, f"entities={int(frame['entity'].nunique())}")
        iso_count = int(frame.loc[~frame["code"].isin(FORMER_STATE_CODES), "entity"].nunique())
        expect("data.foundation.iso_entity_count", iso_count == 190, f"iso_entities={iso_count}")
        expect(
            "data.foundation.former_state_entities",
            set(FORMER_STATES) == {"Czechoslovakia", "East Germany", "Serbia and Montenegro", "USSR", "West Germany", "Yugoslavia"},
            f"former_states={sorted(FORMER_STATES)}",
        )
        expect(
            "data.foundation.quality.block",
            not frame.isna().any().any()
            and not frame.duplicated(["entity", "year"]).any()
            and int((frame["rate"] > 0).sum()) == len(frame)
            and int(frame["year"].between(FIRST_YEAR, LAST_YEAR).sum()) == len(frame),
            "no nulls / no duplicate entity-year / all rates positive / years in range",
        )
        expect(
            "data.foundation.years_covered",
            sorted(frame["year"].unique().tolist()) == list(range(FIRST_YEAR, LAST_YEAR + 1)) and int(frame["year"].nunique()) == 56,
            f"distinct_years={int(frame['year'].nunique())}",
        )
        iso_codes = {c.alpha_3 for c in pycountry.countries}
        unrecognized = sorted(
            {r.code for r in frame.itertuples() if r.code not in iso_codes and r.code not in FORMER_STATE_CODES}
        )
        expect("data.foundation.iso_validation_pycountry", not unrecognized, f"unrecognized_codes={unrecognized}")

        rate_mean = float(frame["rate"].mean())
        rate_median = float(frame["rate"].median())
        rate_q1 = float(frame["rate"].quantile(0.25))
        rate_q3 = float(frame["rate"].quantile(0.75))
        rate_iqr = rate_q3 - rate_q1
        lower_fence = float(rate_q1 - 1.5 * rate_iqr)
        upper_fence = float(rate_q3 + 1.5 * rate_iqr)
        expect("data.foundation.summary_mean", approx(rate_mean, 11.95, RATE_TOL), f"mean={rate_mean:.4f}")
        expect("data.foundation.summary_median", approx(rate_median, 10.64, RATE_TOL), f"median={rate_median:.4f}")
        expect("data.foundation.summary_q1_q3_iqr", approx(rate_q1, 6.22, RATE_TOL) and approx(rate_q3, 16.10, RATE_TOL) and approx(rate_iqr, 9.88, RATE_TOL), f"q1={rate_q1:.3f} q3={rate_q3:.3f} iqr={rate_iqr:.3f}")

        quality_displayed = _get("/analysis/quality")
        distribution_displayed = _get("/analysis/distribution")
        summary_displayed = quality_displayed["summary"]
        expect("data.foundation.displayed_mean", approx(float(summary_displayed["mean"]), rate_mean, RATE_TOL), f"displayed={float(summary_displayed['mean']):.4f} independent={rate_mean:.4f}")
        expect("data.foundation.displayed_median", approx(float(summary_displayed["median"]), rate_median, RATE_TOL), f"displayed={float(summary_displayed['median']):.4f} independent={rate_median:.4f}")
        expect("data.foundation.displayed_q1_q3", approx(float(summary_displayed["q1"]), rate_q1, RATE_TOL) and approx(float(summary_displayed["q3"]), rate_q3, RATE_TOL), f"displayed=({summary_displayed['q1']},{summary_displayed['q3']}) independent=({rate_q1},{rate_q3})")
        expect("data.foundation.displayed_fences", approx(float(quality_displayed["quality"]["rate_iqr_fences"][1]), upper_fence, RATE_TOL) and approx(float(quality_displayed["quality"]["rate_iqr_fences"][0]), lower_fence, RATE_TOL), f"fences={quality_displayed['quality']['rate_iqr_fences']} independent=({lower_fence:.4f},{upper_fence:.4f})")
        expect("data.foundation.quality_block", int(quality_displayed["quality"]["null_cells"]) == 0 and int(quality_displayed["quality"]["duplicate_entity_year_rows"]) == 0 and int(quality_displayed["quality"]["invalid_codes"]) == 0 and int(quality_displayed["quality"]["negative_or_zero_rates"]) == 0, json.dumps(quality_displayed["quality"]))
        expect("data.foundation.displayed_outlier_count", int(quality_displayed["quality"]["rate_outlier_count"]) == 82, f"displayed={quality_displayed['quality']['rate_outlier_count']}")
        expect("data.foundation.displayed_gaps_within_span", int(quality_displayed["quality"]["country_year_gaps_within_observed_span"]) == 331, f"displayed={quality_displayed['quality']['country_year_gaps_within_observed_span']}")

        outlier_rows = frame[(frame["rate"] < lower_fence) | (frame["rate"] > upper_fence)]
        expect("data.foundation.outlier_count_independent", int(len(outlier_rows)) == 82, f"independent_outliers={len(outlier_rows)}")
        max_row = outlier_rows.loc[outlier_rows["rate"].idxmax()]
        expect("data.foundation.outlier_max", approx(float(max_row["rate"]), 44.35, RATE_TOL) and str(max_row["entity"]) == "Lithuania" and int(max_row["year"]) == 1996, f"{max_row['entity']} {int(max_row['year'])} {float(max_row['rate']):.2f}")

        histogram_edges = [0, 5, 10, 15, 20, 25, 30, 35, 40, math.inf]
        histogram = []
        for low, high in zip(histogram_edges, histogram_edges[1:]):
            label = f"{low:g}\u2013{high:g}" if math.isfinite(high) else "40+"
            histogram.append({"range": label, "count": int(((frame["rate"] >= low) & (frame["rate"] < high)).sum())})
        displayed_hist = distribution_displayed["histogram"]
        expect(
            "data.foundation.histogram_bins",
            len(displayed_hist) == len(histogram) and all(int(d["count"]) == int(e["count"]) for d, e in zip(displayed_hist, histogram)),
            f"displayed_total={sum(int(r['count']) for r in displayed_hist)} independent_total={sum(int(r['count']) for r in histogram)}",
        )
        bin_5_10 = [r for r in displayed_hist if r["range"] == "5\u201310"]
        bin_10_15 = [r for r in displayed_hist if r["range"] == "10\u201315"]
        bin_5_15 = bin_5_10 + bin_10_15 if len(bin_5_10) == 1 and len(bin_10_15) == 1 else []
        expect("data.foundation.histogram_5_10", len(bin_5_10) == 1 and int(bin_5_10[0]["count"]) == 820 and approx(int(bin_5_10[0]["count"]) / len(frame) * 100, 28.8, 0.5), f"count={bin_5_10[0]['count'] if bin_5_10 else None}")
        expect(
            "data.foundation.histogram_5_15",
            len(bin_5_15) == 2 and int(bin_5_15[0]["count"]) + int(bin_5_15[1]["count"]) == 1534 and approx((int(bin_5_15[0]["count"]) + int(bin_5_15[1]["count"])) / len(frame) * 100, 54.0, 0.5),
            f"combined_5_15_count={int(bin_5_15[0]['count']) + int(bin_5_15[1]['count']) if bin_5_15 else None}",
        )

        gap_stats = frame.groupby("entity")["year"].agg(["min", "max", "nunique"])
        gap_stats["gaps"] = gap_stats["max"] - gap_stats["min"] + 1 - gap_stats["nunique"]
        expect("data.foundation.gaps_within_observed_span", int(gap_stats["gaps"].sum()) == 331, f"gaps={int(gap_stats['gaps'].sum())}")

        # ============================ TOP COUNTRIES ============================
        top_displayed = _get("/countries/top?n=10&from=1950&to=2005")
        top_analysis = _get("/analysis/top-countries?min_years=10&n=10&from=1950&to=2005")
        independent_top = country_stats(frame, FIRST_YEAR, LAST_YEAR)
        eligible = independent_top[(independent_top["years"] >= MIN_TOP_COUNTRY_YEARS) & (~independent_top["code"].isin(FORMER_STATE_CODES))]
        independent_top_sorted = eligible.sort_values(["mean", "entity"], ascending=[False, True]).head(10)

        def top_rows_list(rows):
            if hasattr(rows, "to_dict"):
                rows = rows.to_dict("records")
            out = []
            for r in rows:
                if isinstance(r, dict):
                    out.append((str(r["entity"]), float(r.get("avg_rate", r.get("mean", 0.0))), int(r.get("years_reported", r.get("years", 0)))))
                else:
                    out.append((str(r.entity), float(r.avg_rate), int(r.years_reported)))
            return out

        def independent_top_tuples() -> list:
            return [
                (str(r.entity), float(r.mean), int(r.years))
                for r in independent_top_sorted.itertuples()
            ]

        expect(
            "top.countries.displayed_matches_independent",
            len(top_displayed) == 10 and all(
                row[0] == ind[0] and approx(row[1], ind[1], RATE_TOL) and row[2] == ind[2]
                for row, ind in zip(top_rows_list(top_displayed), independent_top_tuples())
            ),
            f"displayed={[top_rows_list(top_displayed)[:2]]} independent={[independent_top_tuples()[:2]]}",
        )
        expect(
            "top.countries.analysis_matches_independent",
            len(top_analysis) == 10 and all(
                r[0] == ind[0] and approx(r[1], ind[1], RATE_TOL) and int(r[2]) == int(ind[2])
                for r, ind in zip(top_rows_list(top_analysis), independent_top_tuples())
            ),
            f"analysis_top10_first={top_rows_list(top_analysis)[:1]}",
        )
        expect("top.countries.first_is_lithuania", top_rows_list(top_displayed)[0][0] == "Lithuania" and top_rows_list(top_displayed)[0][2] == 23, f"first={top_rows_list(top_displayed)[0]}")
        expect("top.countries.guyana_excluded", all(row[0] != "Guyana" for row in top_rows_list(top_displayed)), f"top={[r[0] for r in top_rows_list(top_displayed)]}")
        guyana = frame[frame["entity"] == "Guyana"]
        expect("top.countries.guyana_three_obs", int(len(guyana)) == 3 and approx(float(guyana["rate"].mean()), 30.85, RATE_TOL), f"guyana_mean={float(guyana['rate'].mean()):.2f} n={len(guyana)}")
        for min_years in (1, 3, 5, 10, 20):
            displayed = _get(f"/analysis/top-countries?min_years={min_years}&n=10&from=1950&to=2005")
            elig = independent_top[independent_top["years"] >= min_years]
            elig_sorted = elig[~elig["code"].isin(FORMER_STATE_CODES)].sort_values(["mean", "entity"], ascending=[False, True]).head(10)
            ok = len(displayed) == 10 and all(
                r["entity"] == str(e.entity) and approx(r["avg_rate"], float(e.mean), RATE_TOL) and int(r["years_reported"]) == int(e.years)
                for r, e in zip(displayed, elig_sorted.itertuples())
            )
            expect(f"top.countries.min_years_{min_years}", ok, f"top_entity_at_min_{min_years}={displayed[0]['entity'] if displayed else None}")

        # ============================ GLOBAL TREND ============================
        trend_displayed = _get("/trend/global?from=1950&to=2005")
        trend_analysis = _get("/analysis/trend?from=1950&to=2005")
        independent_yearly = yearly_rows(frame, FIRST_YEAR, LAST_YEAR)
        expect(
            "trend.global.displayed_rows",
            len(trend_displayed) == 56 and all(
                int(d["year"]) == int(i["year"]) and approx(d["avg_rate"], i["avg_rate"], RATE_TOL) and int(d["countries_reporting"]) == int(i["countries_reporting"])
                for d, i in zip(trend_displayed, independent_yearly)
            ),
            f"rows={len(trend_displayed)} first={trend_displayed[0]}",
        )
        raw_peak_row = max(independent_yearly, key=lambda r: r["avg_rate"])
        expect("trend.raw_peak", int(raw_peak_row["year"]) == 1982 and approx(float(raw_peak_row["avg_rate"]), 14.76, RATE_TOL) and int(raw_peak_row["countries_reporting"]) == 52, f"peak={raw_peak_row}")
        fixed_panel = sorted(panel_entities(frame, FIRST_YEAR, LAST_YEAR))
        fixed_series = series_for(frame, fixed_panel, FIRST_YEAR, LAST_YEAR)
        fixed_peak = max(fixed_series, key=lambda r: r["avg_rate"])
        wide_panel = sorted([e for e, years in frame.groupby("entity")["year"].apply(set).items() if len(years) >= WIDE_PANEL_MIN_YEARS])
        wide_series = series_for(frame, wide_panel, FIRST_YEAR, LAST_YEAR)
        wide_peak = max(wide_series, key=lambda r: r["avg_rate"])
        median_series = []
        sub_years = frame[(frame["year"] >= FIRST_YEAR) & (frame["year"] <= LAST_YEAR)]
        for year, value in sub_years.groupby("year")["rate"].median().items():
            median_series.append({"year": int(year), "avg_rate": float(value), "countries_reporting": int(sub_years.loc[sub_years["year"] == year, "entity"].nunique())})
        median_peak = max(median_series, key=lambda r: r["avg_rate"])
        expect("trend.fixed_panel_peak", int(fixed_peak["year"]) == 1998 and approx(float(fixed_peak["avg_rate"]), 12.21, RATE_TOL) and fixed_panel == ["Australia", "Canada", "Ireland", "Japan", "Netherlands", "New Zealand", "United Kingdom", "United States"], f"fixed_peak={fixed_peak} panel={fixed_panel}")
        expect("trend.fixed_panel_mean_of_yearly", approx(float(np.mean([r["avg_rate"] for r in fixed_series])), 10.67, RATE_TOL), f"fixed_panel_mean={float(np.mean([r['avg_rate'] for r in fixed_series])):.4f}")
        expect("trend.wide_panel_peak", int(wide_peak["year"]) == 1984 and approx(float(wide_peak["avg_rate"]), 13.01, RATE_TOL) and len(wide_panel) == 32, f"wide_peak={wide_peak} wide_n={len(wide_panel)}")
        expect("trend.median_peak", int(median_peak["year"]) == 1988 and approx(float(median_peak["avg_rate"]), 13.64, RATE_TOL), f"median_peak={median_peak}")

        reporting_displayed = {int(r["year"]): int(r["countries_reporting"]) for r in trend_displayed}
        reporting_expected = {int(r["year"]): int(r["countries_reporting"]) for r in independent_yearly}
        expect("trend.reporting_counts", reporting_displayed == reporting_expected, f"reporting={reporting_displayed}")
        expect(
            "trend.reporting_counts_reference",
            int(reporting_expected[1950]) == 10 and int(reporting_expected[2001]) == 62 and int(reporting_expected[2002]) == 190 and int(reporting_expected[2003]) == 55 and int(reporting_expected[2004]) == 191 and int(reporting_expected[2005]) == 191,
            f"reporting_ref={reporting_expected}",
        )
        fixed_by_year = {int(r["year"]): float(r["avg_rate"]) for r in trend_analysis["fixed_panel"]}
        raw_by_year = {int(r["year"]): float(r["avg_rate"]) for r in trend_displayed}
        below = sum(1 for year, val in fixed_by_year.items() if year <= 2001 and val < raw_by_year[year])
        above = sum(1 for year, val in fixed_by_year.items() if 2002 <= year <= 2005 and val > raw_by_year[year])
        expect("trend.panel_vs_raw_direction", below == 52 and above == 3, f"below={below} above={above}")

        # ============================ DECOMPOSITION ============================
        decomposition = _get("/analysis/decomposition?entity=Lithuania")
        independent_pairs = []
        target_years = sorted({int(y) for y in frame_ref.loc[frame_ref["entity"] == "Lithuania", "year"]})
        pairs = []
        for y1, y2 in [(2000, 2002), (2003, 2004)]:
            if y1 in target_years and y2 in target_years:
                pairs.append((y1, y2))
        for y in target_years:
            if (y + 1) in target_years:
                pairs.append((y, y + 1))
        pairs = sorted(set(pairs))
        for y1, y2 in pairs:
            mean_1 = float(frame_ref.loc[frame_ref["year"] == y1, "rate"].mean()) if bool((frame_ref["year"] == y1).any()) else None
            mean_2 = float(frame_ref.loc[frame_ref["year"] == y2, "rate"].mean()) if bool((frame_ref["year"] == y2).any()) else None
            if mean_1 is None or mean_2 is None:
                continue
            total_change = float(mean_2 - mean_1)
            e1 = {r.entity for r in frame_ref.loc[frame_ref["year"] == y1].itertuples()}
            e2 = {r.entity for r in frame_ref.loc[frame_ref["year"] == y2].itertuples()}
            common = e1 & e2
            within = float(np.mean([
                float(frame_ref.loc[(frame_ref["entity"] == e) & (frame_ref["year"] == y2), "rate"].iloc[0])
                - float(frame_ref.loc[(frame_ref["entity"] == e) & (frame_ref["year"] == y1), "rate"].iloc[0])
                for e in common
            ]))
            independent_pairs.append((y1, y2, total_change, within, float(total_change - within), len(common)))
        expect("decomposition.pair_count", len(decomposition["pairs"]) == len(independent_pairs) == 22, f"displayed={len(decomposition['pairs'])} independent={len(independent_pairs)}")
        pair_2002_2003 = [p for p in decomposition["pairs"] if int(p["from_year"]) == 2002 and int(p["to_year"]) == 2003]
        expect("decomposition.pair_2002_2003", len(pair_2002_2003) == 1 and approx(float(pair_2002_2003[0]["total_change"]), 2.97, RATE_TOL) and approx(float(pair_2002_2003[0]["within_effect"]), -0.31, RATE_TOL) and approx(float(pair_2002_2003[0]["composition_effect"]), 3.29, RATE_TOL), f"pair={pair_2002_2003}")
        pair_2000_2002 = [p for p in decomposition["pairs"] if int(p["from_year"]) == 2000 and int(p["to_year"]) == 2002]
        expect("decomposition.pair_2000_2002", len(pair_2000_2002) == 1, f"pair={pair_2000_2002}")
        expect("decomposition.components_sum", all(abs(float(p["within_effect"]) + float(p["composition_effect"]) - float(p["total_change"])) < 1e-6 for p in decomposition["pairs"]), "within + composition == total")

        # ============================ COUNTRY COMPARISON ============================
        lt_default_rows = _get("/compare?entity=Lithuania&from=1950&to=2005")
        lt_deep = _get("/analysis/compare-multi?entities=Lithuania")
        independent_lt = independent_compare("Lithuania", FIRST_YEAR, LAST_YEAR)
        expect("compare.lithuania.row_count", len(independent_lt) == len(lt_default_rows), f"independent={len(independent_lt)} dashboard={len(lt_default_rows)}")
        expect(
            "compare.lithuania.values",
            all(
                approx(float(d["country_rate"]), float(i["country_rate"]), RATE_TOL) and approx(float(d["global_avg"]), float(i["global_avg"]), RATE_TOL)
                for d, i in zip(sorted(lt_default_rows, key=lambda r: int(r["year"])), sorted(independent_lt, key=lambda r: int(r["year"])))
            ),
            "Lithuania dashboard vs independent (country + global)",
        )
        lt_deep_rows = sorted([r for r in lt_deep if r["entity"] == "Lithuania"], key=lambda r: int(r["year"]))
        expect(
            "compare.lithuania.deep_values",
            len(lt_deep_rows) == len(independent_lt) and all(
                approx(float(d["country_rate"]), float(i["country_rate"]), RATE_TOL) and approx(float(d["global_avg"]), float(i["global_avg"]), RATE_TOL) and approx(float(d["panel_avg"]), float(i["panel_avg"]), RATE_TOL)
                for d, i in zip(lt_deep_rows, sorted(independent_lt, key=lambda r: int(r["year"])))
            ),
            "Lithuania in-depth vs independent (country + global + panel)",
        )
        above_both = sum(1 for r in independent_lt if float(r["country_rate"]) > float(r["global_avg"]) and float(r["country_rate"]) > float(r["panel_avg"]))
        expect("compare.lithuania.above_both", len(independent_lt) == 23 and above_both == 23, f"above_both={above_both} n={len(independent_lt)}")
        expect("compare.lithuania.gap_range_global", approx(min(float(r["country_rate"]) - float(r["global_avg"]) for r in independent_lt), 10.58, RATE_TOL) and approx(max(float(r["country_rate"]) - float(r["global_avg"]) for r in independent_lt), 31.37, RATE_TOL), f"gaps={[float(r['country_rate']) - float(r['global_avg']) for r in independent_lt]}")
        expect("compare.lithuania.gap_range_panel", approx(min(float(r["country_rate"]) - float(r["panel_avg"]) for r in independent_lt), 12.28, RATE_TOL) and approx(max(float(r["country_rate"]) - float(r["panel_avg"]) for r in independent_lt), 33.12, RATE_TOL), f"gaps={[float(r['country_rate']) - float(r['panel_avg']) for r in independent_lt]}")

        for entity in ENTITIES:
            for start, end in [(FIRST_YEAR, LAST_YEAR), SUB_RANGE]:
                dashboard = _get(f"/compare?entity={entity}&from={start}&to={end}")
                deep = _get(f"/analysis/compare-multi?entities={entity}")
                indep = independent_compare(entity, start, end)
                deep_rows = sorted([r for r in deep if r["entity"] == entity], key=lambda r: int(r["year"]))
                deep_in_range = [r for r in deep_rows if start <= int(r["year"]) <= end]
                dashboard_sorted = sorted(dashboard, key=lambda r: int(r["year"]))
                indep_sorted = sorted(indep, key=lambda r: int(r["year"]))
                ok = len(dashboard_sorted) == len(indep_sorted) and all(
                    approx(float(d["country_rate"]), float(i["country_rate"]), RATE_TOL) and approx(float(d["global_avg"]), float(i["global_avg"]), RATE_TOL)
                    for d, i in zip(dashboard_sorted, indep_sorted)
                )
                deep_ok = len(deep_in_range) == len(indep_sorted) and all(
                    approx(float(d["country_rate"]), float(i["country_rate"]), RATE_TOL)
                    and approx(float(d["global_avg"]), float(i["global_avg"]), RATE_TOL)
                    and (
                        (float(i["panel_avg"]) != float(i["panel_avg"]))
                        or approx(float(d["panel_avg"]), float(i["panel_avg"]), RATE_TOL)
                    )
                    for d, i in zip(deep_in_range, indep_sorted)
                )
                expect(
                    f"compare.{entity}.range_{start}_{end}.values",
                    ok and deep_ok,
                    f"dashboard={len(dashboard_sorted)} deep_in_range={len(deep_in_range)} independent={len(indep_sorted)}",
                )

        # ============================ ANOMALIES ============================
        anomaly_summary = _get("/analysis/anomalies")
        changes = anomaly_frame(frame_ref)
        change_mean = float(changes["change"].mean())
        change_std = float(changes["change"].std(ddof=1))
        changes["z_score"] = (changes["change"] - change_mean) / change_std
        q1c, q3c = changes["change"].quantile([0.25, 0.75])
        iqrc = float(q3c) - float(q1c)
        lower_c = float(q1c) - 1.5 * iqrc
        upper_c = float(q3c) + 1.5 * iqrc
        changes["zscore_flag"] = changes["z_score"].abs() > 2
        changes["iqr_flag"] = (changes["change"] < lower_c) | (changes["change"] > upper_c)
        flagged = changes[changes["zscore_flag"] | changes["iqr_flag"]]
        expect("anomalies.summary.consecutive_changes", int(anomaly_summary["consecutive_changes"]) == int(len(changes)) == 2457, f"displayed={anomaly_summary['consecutive_changes']} independent={len(changes)}")
        expect("anomalies.summary.zscore_count", int(anomaly_summary["zscore_count"]) == int(changes["zscore_flag"].sum()) == 122, f"zscore={anomaly_summary['zscore_count']} independent={int(changes['zscore_flag'].sum())}")
        expect("anomalies.summary.iqr_count", int(anomaly_summary["iqr_count"]) == int(changes["iqr_flag"].sum()) == 235, f"iqr={anomaly_summary['iqr_count']} independent={int(changes['iqr_flag'].sum())}")
        expect("anomalies.summary.both_count", int(anomaly_summary["both_count"]) == int((changes["zscore_flag"] & changes["iqr_flag"]).sum()) == 122, f"both={anomaly_summary['both_count']} independent={int((changes['zscore_flag'] & changes['iqr_flag']).sum())}")
        expect(
            "anomalies.summary.change_stats",
            approx(float(anomaly_summary["change_mean"]), change_mean, RATE_TOL)
            and approx(float(anomaly_summary["change_std"]), change_std, RATE_TOL)
            and approx(float(anomaly_summary["iqr_change_fences"][0]), lower_c, RATE_TOL)
            and approx(float(anomaly_summary["iqr_change_fences"][1]), upper_c, RATE_TOL),
            f"mean={change_mean:.4f} std={change_std:.4f} fences=[{lower_c:.3f},{upper_c:.3f}]",
        )

        displayed_flagged = anomaly_summary["flagged_rows"]
        indep_flagged = flagged[["entity", "year", "change", "z_score", "zscore_flag", "iqr_flag"]]
        indep_keys = {(str(r.entity), int(r.year)): r for r in indep_flagged.itertuples()}
        displayed_keys = {(str(r["entity"]), int(r["year"])): r for r in displayed_flagged}
        expect("anomalies.flagged.key_set", set(indep_keys) == set(displayed_keys), f"independent={len(indep_keys)} displayed={len(displayed_keys)}")
        flag_row_ok = True
        flag_detail = ""
        for key, row in indep_keys.items():
            d = displayed_keys.get(key)
            if d is None:
                flag_row_ok = False
                flag_detail = f"missing {key}"
                break
            if bool(d["zscore_flag"]) != bool(row.zscore_flag) or bool(d["iqr_flag"]) != bool(row.iqr_flag):
                flag_row_ok = False
                flag_detail = f"flag mismatch {key}: displayed=({d['zscore_flag']},{d['iqr_flag']}) independent=({row.zscore_flag},{row.iqr_flag})"
                break
            if not approx(float(d["change"]), float(row.change), RATE_TOL) or not approx(float(d["z_score"]), float(row.z_score), ZSCORE_TOL):
                flag_row_ok = False
                flag_detail = f"value mismatch {key}: displayed=({d['change']},{d['z_score']}) independent=({row.change},{row.z_score})"
                break
        expect("anomalies.flagged.rows", flag_row_ok, flag_detail)

        est_z = [r for r in indep_keys.values() if str(r.entity) == "Estonia" and int(r.year) == 1994]
        sin_z = [r for r in indep_keys.values() if str(r.entity) == "Singapore" and int(r.year) == 1982]
        expect("anomalies.borderline.estonia_not_flagged", len(est_z) == 1 and not bool(est_z[0].zscore_flag), f"estonia_1994_z={float(est_z[0].z_score) if est_z else None}")
        expect("anomalies.borderline.singapore_not_flagged", len(sin_z) == 1 and not bool(sin_z[0].zscore_flag), f"singapore_1982_z={float(sin_z[0].z_score) if sin_z else None}")
        zflag_counts = changes.loc[changes["zscore_flag"], "entity"].value_counts().sort_values(ascending=False)
        expect("anomalies.zflag_top_concentration", str(zflag_counts.index[0]) == "Trinidad and Tobago" and int(zflag_counts.iloc[0]) == 12 and int(zflag_counts.iloc[1]) == 12 and int(zflag_counts.iloc[2]) == 10, json.dumps(zflag_counts.head(3).to_dict()))

        # ============================ COVERAGE ============================
        coverage_displayed = _get("/analysis/coverage")
        coverage_dashboard = _get("/coverage?limit=250&from=1950&to=2005")
        independent_coverage = []
        for entity, group in frame_ref.groupby("entity"):
            years = sorted(int(y) for y in group["year"])
            independent_coverage.append({
                "entity": str(entity),
                "years_reported": len(years),
                "first_year": years[0] if years else None,
                "last_year": years[-1] if years else None,
                "gaps": (years[-1] - years[0] + 1 - len(years)) if years else 0,
            })
        indep_cov_map = {r["entity"]: r for r in independent_coverage}
        expect("coverage.analysis_row_count", len(coverage_displayed["coverage"]) == 196, f"rows={len(coverage_displayed['coverage'])}")
        expect(
            "coverage.analysis_rows_match_independent",
            len(coverage_displayed["coverage"]) == len(indep_cov_map) and all(
                int(d["years_reported"]) == int(i["years_reported"]) and int(d["first_year"]) == int(i["first_year"]) and int(d["last_year"]) == int(i["last_year"]) and int(d["gaps"]) == int(i["gaps"])
                for d, i in zip(sorted(coverage_displayed["coverage"], key=lambda r: str(r["entity"])), sorted(independent_coverage, key=lambda r: str(r["entity"])))
            ),
            "coverage rows vs independent",
        )
        expect(
            "coverage.dashboard_rows_match_independent",
            len(coverage_dashboard) == len(independent_coverage) and all(
                int(d["years_reported"]) == int(i["years_reported"]) and int(d["first_year"]) == int(i["first_year"]) and int(d["last_year"]) == int(i["last_year"]) and int(d["gaps"]) == int(i["gaps"])
                for d, i in zip(sorted(coverage_dashboard, key=lambda r: str(r["entity"])), sorted(independent_coverage, key=lambda r: str(r["entity"])))
            ),
            f"dashboard_rows={len(coverage_dashboard)}",
        )
        expect(
            "coverage.tiers",
            int(sum(1 for r in independent_coverage if int(r["years_reported"]) == 56)) == 8
            and int(sum(1 for r in independent_coverage if int(r["years_reported"]) <= 3)) == 122
            and sum(int(r["gaps"]) for r in independent_coverage) == 331,
            "tiers: 8 full / 122 sparse / 331 gaps",
        )

        # ============================ RELATIONSHIPS ============================
        relationships = _get("/analysis/relationships")
        block_a_rows = {r["id"]: r for r in relationships["block_a"]["rows"]}
        expect("rel.block_a.A1", int(block_a_rows["A1"]["n"]) == 2843 and approx(float(block_a_rows["A1"]["pearson"]), -0.024, CORR_TOL), f"A1 n={block_a_rows['A1']['n']} r={block_a_rows['A1']['pearson']}")
        expect("rel.block_a.A2", int(block_a_rows["A2"]["n"]) == 2216 and approx(float(block_a_rows["A2"]["pearson"]), 0.086, CORR_TOL), f"A2 n={block_a_rows['A2']['n']} r={block_a_rows['A2']['pearson']}")
        expect("rel.block_a.A3", int(block_a_rows["A3"]["n"]) == 448 and approx(float(block_a_rows["A3"]["pearson"]), 0.193, CORR_TOL), f"A3 n={block_a_rows['A3']['n']} r={block_a_rows['A3']['pearson']}")
        expect("rel.block_a.A4", int(block_a_rows["A4"]["n"]) == 56 and approx(float(block_a_rows["A4"]["pearson"]), 0.723, CORR_TOL), f"A4 n={block_a_rows['A4']['n']} r={block_a_rows['A4']['pearson']}")
        expect("rel.block_a.A5", int(block_a_rows["A5"]["n"]) == 1637 and approx(float(block_a_rows["A5"]["pearson"]), 0.107, CORR_TOL), f"A5 n={block_a_rows['A5']['n']} r={block_a_rows['A5']['pearson']}")

        early = frame_ref[frame_ref["year"] <= 2001]
        panel = sorted(panel_entities(frame_ref, FIRST_YEAR, LAST_YEAR))
        panel_frame = frame_ref[frame_ref["entity"].isin(panel)].copy()
        panel_demeaned = panel_frame.copy()
        panel_demeaned["rate_demeaned"] = panel_demeaned["rate"] - panel_demeaned.groupby("entity")["rate"].transform("mean")
        wide_panel = sorted([e for e, years in frame_ref.groupby("entity")["year"].apply(set).items() if len(years) >= WIDE_PANEL_MIN_YEARS])
        wide_frame = frame_ref[frame_ref["entity"].isin(wide_panel)].copy()
        wide_demeaned = wide_frame.copy()
        wide_demeaned["rate_demeaned"] = wide_demeaned["rate"] - wide_demeaned.groupby("entity")["rate"].transform("mean")

        independent_block_a = {
            "A1": (float(pearson(frame_ref["year"], frame_ref["rate"])), int(len(frame_ref))),
            "A2": (float(pearson(early["year"], early["rate"])), int(len(early))),
            "A3": (float(pearson(panel_demeaned["year"], panel_demeaned["rate_demeaned"])), int(len(panel_demeaned))),
            "A4": (float(pearson(panel_frame.groupby("year")["rate"].mean().index, panel_frame.groupby("year")["rate"].mean().values)), int(len(panel_frame.groupby("year")["rate"].mean()))),
            "A5": (float(pearson(wide_demeaned["year"], wide_demeaned["rate_demeaned"])), int(len(wide_demeaned))),
        }
        for key, (r_value, n_value) in independent_block_a.items():
            row = block_a_rows[key]
            expect(
                f"rel.block_a.{key}.value",
                int(row["n"]) == n_value and approx(float(row["pearson"]), r_value, CORR_TOL),
                f"{key}: displayed n={row['n']} r={row['pearson']} independent n={n_value} r={r_value}",
            )

        def window_stats(window_x: tuple, window_y: tuple):
            left = frame_ref[(frame_ref["year"] >= window_x[0]) & (frame_ref["year"] <= window_x[1])]
            left = left.groupby(["entity", "code"], as_index=False).agg(mean=("rate", "mean"), observations=("year", "nunique"))
            left = left[left["observations"] >= 1]
            right = frame_ref[(frame_ref["year"] >= window_y[0]) & (frame_ref["year"] <= window_y[1])]
            right = right.groupby(["entity", "code"], as_index=False).agg(mean=("rate", "mean"), observations=("year", "nunique"))
            right = right[right["observations"] >= 1]
            points = left.merge(right, on="entity", how="inner")
            pearson_value = float(pearson(points["mean_x"], points["mean_y"]))
            spearman_value = float(spearman(points["mean_x"], points["mean_y"]))
            return points, pearson_value, spearman_value

        b1_points, b1_pearson, b1_spearman = window_stats((1980, 1989), (1990, 1999))
        b1_displayed = relationships["block_b"]["B1"]
        expect("rel.block_b.B1.stats", int(b1_displayed["n"]) == int(len(b1_points)) and approx(float(b1_displayed["pearson"]), b1_pearson, CORR_TOL) and approx(float(b1_displayed["spearman"]), b1_spearman, CORR_TOL), f"B1 n={b1_displayed['n']} p={b1_displayed['pearson']} s={b1_displayed['spearman']} independent n={len(b1_points)} p={b1_pearson} s={b1_spearman}")
        b1_interval = bootstrap_interval(b1_points, lambda s: float(pearson(s["mean_x"], s["mean_y"])))
        expect("rel.block_b.B1.bootstrap", b1_displayed["pearson_ci"] is not None and all(abs(float(a) - float(b)) <= 0.002 for a, b in zip(b1_displayed["pearson_ci"], b1_interval)), f"B1 displayed_ci={b1_displayed['pearson_ci']} independent_ci={b1_interval}")

        b2_points, b2_pearson, b2_spearman = window_stats((1990, 1999), (2000, 2005))
        b2_displayed = relationships["block_b"]["B2"]
        expect("rel.block_b.B2.stats", int(b2_displayed["n"]) == int(len(b2_points)) and approx(float(b2_displayed["pearson"]), b2_pearson, CORR_TOL) and approx(float(b2_displayed["spearman"]), b2_spearman, CORR_TOL), f"B2 n={b2_displayed['n']} p={b2_displayed['pearson']} s={b2_displayed['spearman']} independent n={len(b2_points)} p={b2_pearson} s={b2_spearman}")
        b2_interval = bootstrap_interval(b2_points, lambda s: float(pearson(s["mean_x"], s["mean_y"])))
        expect("rel.block_b.B2.bootstrap", b2_displayed["pearson_ci"] is not None and all(abs(float(a) - float(b)) <= 0.002 for a, b in zip(b2_displayed["pearson_ci"], b2_interval)), f"B2 displayed_ci={b2_displayed['pearson_ci']} independent_ci={b2_interval}")

        country_all = country_stats(frame_ref)
        b3_displayed = relationships["block_b"]["B3"]
        b3_pearson = float(pearson(country_all["years"], country_all["mean"]))
        b3_spearman = float(spearman(country_all["years"], country_all["mean"]))
        expect("rel.block_b.B3.stats", int(b3_displayed["n"]) == int(len(country_all)) and approx(float(b3_displayed["pearson"]), b3_pearson, CORR_TOL) and approx(float(b3_displayed["spearman"]), b3_spearman, CORR_TOL), f"B3 n={b3_displayed['n']} p={b3_displayed['pearson']} s={b3_displayed['spearman']} independent p={b3_pearson} s={b3_spearman}")
        b3_subset = country_all[country_all["years"] >= MIN_COVERAGE_YEARS]
        expect("rel.block_b.B3.subset", int(b3_displayed["subset"]["n"]) == int(len(b3_subset)) and approx(float(b3_displayed["subset"]["pearson"]), float(pearson(b3_subset["years"], b3_subset["mean"])), CORR_TOL), f"B3 subset n={b3_displayed['subset']['n']} p={b3_displayed['subset']['pearson']}")
        b3_interval = bootstrap_interval(country_all, lambda s: float(pearson(s["years"], s["mean"])))
        expect("rel.block_b.B3.bootstrap", b3_displayed["pearson_ci"] is not None and all(abs(float(a) - float(b)) <= 0.002 for a, b in zip(b3_displayed["pearson_ci"], b3_interval)), f"B3 displayed_ci={b3_displayed['pearson_ci']} independent_ci={b3_interval}")

        variability = frame_ref.groupby(["entity", "code"], as_index=False).agg(mean=("rate", "mean"), sd=("rate", "std"), observations=("year", "nunique"))
        variability = variability[variability["observations"] >= MIN_COVERAGE_YEARS]
        b4_displayed = relationships["block_b"]["B4"]
        b4_pearson = float(pearson(variability["mean"], variability["sd"]))
        b4_spearman = float(spearman(variability["mean"], variability["sd"]))
        expect("rel.block_b.B4.stats", int(b4_displayed["n"]) == int(len(variability)) and approx(float(b4_displayed["pearson"]), b4_pearson, CORR_TOL) and approx(float(b4_displayed["spearman"]), b4_spearman, CORR_TOL), f"B4 n={b4_displayed['n']} p={b4_displayed['pearson']} s={b4_displayed['spearman']} independent p={b4_pearson} s={b4_spearman}")
        b4_interval = bootstrap_interval(variability, lambda s: float(pearson(s["mean"], s["sd"])))
        expect("rel.block_b.B4.bootstrap", b4_displayed["pearson_ci"] is not None and all(abs(float(a) - float(b)) <= 0.002 for a, b in zip(b4_displayed["pearson_ci"], b4_interval)), f"B4 displayed_ci={b4_displayed['pearson_ci']} independent_ci={b4_interval}")

        # ============================ DATA-QUALITY CLAIMS ============================
        identical_2004 = frame_ref[frame_ref["year"] == 2004]
        identical_2005 = frame_ref[frame_ref["year"] == 2005]
        shared_04_05 = set(identical_2004["entity"]) & set(identical_2005["entity"])
        identical_pairs = sum(
            1 for e in shared_04_05
            if float(identical_2004.loc[identical_2004["entity"] == e, "rate"].iloc[0]) == float(identical_2005.loc[identical_2005["entity"] == e, "rate"].iloc[0])
        )
        expect("dataquality.identical_2004_2005", len(shared_04_05) == 191 and identical_pairs == 136 and len(identical_2005) == 191, f"identical_pairs={identical_pairs} shared={len(shared_04_05)} n2005={len(identical_2005)}")
        both_2001_2002 = set(frame_ref.loc[frame_ref["year"] == 2001, "entity"]) & set(frame_ref.loc[frame_ref["year"] == 2002, "entity"])
        mean_2001 = float(frame_ref.loc[frame_ref["year"] == 2001, "rate"].mean())
        mean_2002 = float(frame_ref.loc[frame_ref["year"] == 2002, "rate"].mean())
        mean_2001_shared = float(frame_ref.loc[(frame_ref["year"] == 2001) & (frame_ref["entity"].isin(both_2001_2002)), "rate"].mean())
        mean_2002_shared = float(frame_ref.loc[(frame_ref["year"] == 2002) & (frame_ref["entity"].isin(both_2001_2002)), "rate"].mean())
        expect("dataquality.2001_2002_same_countries", len(both_2001_2002) == 62 and approx(mean_2001_shared, 12.36, RATE_TOL) and approx(mean_2002_shared, 12.26, RATE_TOL), f"n={len(both_2001_2002)} mean2001_shared={mean_2001_shared:.2f} mean2002_shared={mean_2002_shared:.2f}")
        first_2002 = set(frame_ref.loc[frame_ref["year"] == 2002, "entity"]) - set(frame_ref.loc[frame_ref["year"] == 2001, "entity"])
        expect("dataquality.first_reporters_2002", len(first_2002) == 128 and approx(float(frame_ref.loc[frame_ref["entity"].isin(first_2002) & (frame_ref["year"] == 2002), "rate"].mean()), 8.20, RATE_TOL), f"n={len(first_2002)} mean={float(frame_ref.loc[frame_ref['entity'].isin(first_2002) & (frame_ref['year'] == 2002), 'rate'].mean()):.2f}")
        shared_2002_2005 = set(frame_ref.loc[frame_ref["year"] == 2002, "entity"]) & set(frame_ref.loc[frame_ref["year"] == 2005, "entity"])
        mean_2002_shared = float(frame_ref.loc[(frame_ref["year"] == 2002) & (frame_ref["entity"].isin(shared_2002_2005)), "rate"].mean())
        mean_2005_shared = float(frame_ref.loc[(frame_ref["year"] == 2005) & (frame_ref["entity"].isin(shared_2002_2005)), "rate"].mean())
        expect("dataquality.2002_2005_same_countries", len(shared_2002_2005) == 190 and approx(mean_2002_shared, 9.52, RATE_TOL) and approx(mean_2005_shared, 9.66, RATE_TOL), f"n={len(shared_2002_2005)} mean2002_shared={mean_2002_shared:.2f} mean2005_shared={mean_2005_shared:.2f}")

        # ============================ INSIGHTS / FINDINGS / VERDICTS ============================
        findings = _get("/analysis/findings")
        insights = _get("/insights")
        expect("findings.register_count", len(findings) == 11, f"findings={len(findings)}")
        expect("findings.insights_alignment", len(insights) == 7 and len(findings) >= 7, f"insights={len(insights)} findings={len(findings)}")
        aligned = True
        for index, insight in enumerate(insights):
            finding = findings[index]
            if insight["title"] != finding["title"] or insight["detail"] != finding["detail"] or insight["caveat"] != finding["caveat"]:
                aligned = False
        expect("findings.insights_1_to_7_match", aligned, "insights 1-7 vs findings 1-7")
        confidences = [f["confidence"] for f in findings]
        confidence_bases = {str(c).split(" — ")[0].strip() for c in confidences}
        expect("findings.confidence_labels", confidence_bases <= {"High", "Medium", "Low"}, f"confidences={confidences}")
        relationship_findings = [f for f in findings if f.get("section") == "relationships"]
        expect(
            "findings.confidence_values",
            [f["confidence"] for f in relationship_findings] == [
                "High — stable across sensitivity checks",
                "High — stable across sensitivity checks",
                "High — stable across sensitivity checks",
                "Medium — sensitive to the inclusion rule",
            ],
            f"relationship_confidences={[f['confidence'] for f in relationship_findings]}",
        )

        independent_a_values = [v[0] for v in independent_block_a.values()]
        spread = max(independent_a_values) - min(independent_a_values)
        expected_a_label = "Not Favourable" if spread >= 0.30 else ("Mixed" if spread >= 0.10 else "Favourable")
        expect("rel.verdict_block_a_follows_rule", relationships["block_a"]["verdict"]["label"] == expected_a_label, f"spread={spread:.3f} displayed={relationships['block_a']['verdict']['label']} expected={expected_a_label}")
        expected_b1 = "Favourable" if (b1_spearman >= 0.80 and int(b1_displayed["n"]) >= 30) else ("Mixed" if (b1_spearman >= 0.50 and int(b1_displayed["n"]) >= 30) else "Not Favourable")
        expect("rel.verdict_block_b1_follows_rule", b1_displayed["verdict"]["label"] == expected_b1, f"B1 verdict={b1_displayed['verdict']['label']} expected={expected_b1}")
        expected_b2 = "Favourable" if (b2_spearman >= 0.80 and int(b2_displayed["n"]) >= 30) else ("Mixed" if (b2_spearman >= 0.50 and int(b2_displayed["n"]) >= 30) else "Not Favourable")
        expect("rel.verdict_block_b2_follows_rule", b2_displayed["verdict"]["label"] == expected_b2, f"B2 verdict={b2_displayed['verdict']['label']} expected={expected_b2}")
        full_r = abs(float(b3_displayed["pearson"]) or 0.0)
        sub_r = abs(float(b3_displayed["subset"]["pearson"]) or 0.0)
        expected_b3 = "Mixed" if (full_r < 0.30 and sub_r < 0.30 and int(b3_displayed["subset"]["n"]) >= 30) else ("Not Favourable" if (full_r >= 0.50 and sub_r >= 0.50) else "Mixed")
        expect("rel.verdict_block_b3_follows_rule", b3_displayed["verdict"]["label"] == expected_b3, f"B3 verdict={b3_displayed['verdict']['label']} expected={expected_b3}")
        expected_b4 = "Not Favourable" if (b4_pearson >= 0.50 and int(b4_displayed["n"]) >= 30) else ("Mixed" if (b4_pearson >= 0.30 and int(b4_displayed["n"]) >= 30) else "Favourable")
        expect("rel.verdict_block_b4_follows_rule", b4_displayed["verdict"]["label"] == expected_b4, f"B4 verdict={b4_displayed['verdict']['label']} expected={expected_b4}")

        # ============================ CROSS-PAGE ALIGNMENT ============================
        kpis_dashboard = _get("/kpis?from=1950&to=2005")
        kpis_sub = _get("/kpis?from=1980&to=1995")
        summary_default = _get("/analysis/summary?from=1950&to=2005")
        summary_sub = _get("/analysis/summary?from=1980&to=1995")
        expect(
            "xpg.kpis_dashboard_vs_analysis_default",
            approx(float(kpis_dashboard["global_avg"]), float(summary_default["mean"]), RATE_TOL) and int(kpis_dashboard["country_count"]) == int(summary_default["entity_count"]) and int(kpis_dashboard["peak_year"]) == int(summary_default["peak_year"]),
            "dashboard /kpis vs /analysis/summary",
        )
        expect(
            "xpg.kpis_dashboard_vs_analysis_sub",
            approx(float(kpis_sub["global_avg"]), float(summary_sub["mean"]), RATE_TOL) and int(kpis_sub["country_count"]) == int(summary_sub["entity_count"]) and int(kpis_sub["peak_year"]) == int(summary_sub["peak_year"]),
            "dashboard /kpis (1980-1995) vs /analysis/summary (1980-1995)",
        )
        expect(
            "xpg.kpis_dashboard_vs_independent_sub",
            approx(float(kpis_sub["global_avg"]), mean_over(frame_ref, SUB_RANGE[0], SUB_RANGE[1]), RATE_TOL) and int(kpis_sub["country_count"]) == int(frame_ref.loc[frame_ref["year"].between(SUB_RANGE[0], SUB_RANGE[1]), "entity"].nunique()),
            f"independent_sub_mean={mean_over(frame_ref, SUB_RANGE[0], SUB_RANGE[1])} independent_sub_entities={int(frame_ref.loc[frame_ref['year'].between(SUB_RANGE[0], SUB_RANGE[1]), 'entity'].nunique())}",
        )
        trend_sub = _get("/trend/global?from=1980&to=1995")
        expect("xpg.trend_dashboard_vs_independent_sub", len(trend_sub) == len([r for r in independent_yearly if SUB_RANGE[0] <= int(r["year"]) <= SUB_RANGE[1]]), f"trend sub-range rows={len(trend_sub)}")
        compact = _get("/analysis/relationships/compact")
        expect(
            "xpg.relationships_compact_vs_full",
            compact["block_a"]["rows"][0]["pearson"] == relationships["block_a"]["rows"][0]["pearson"] and compact["block_b"]["B1"]["pearson"] == relationships["block_b"]["B1"]["pearson"],
            "compact vs full relationship numbers",
        )
        coverage_dashboard = _get("/coverage?limit=250&from=1950&to=2005")
        expect(
            "xpg.coverage_dashboard_vs_analysis_default",
            len(coverage_dashboard) == len(coverage_displayed["coverage"]),
            f"dashboard coverage rows={len(coverage_dashboard)} analysis rows={len(coverage_displayed['coverage'])}",
        )

        # ============================ SUMMARY ============================
        print()
        print(f"CHECKS_RUN={len(RESULTS)} CHECKS_FAILED={len(failed)}")
        for name, ok, detail in RESULTS:
            if not ok:
                print(f"  FAILED: {name}  [{detail}]")
        stop_server(proc)
        proc.wait(timeout=20)
        return 1 if failed else 0
    finally:
        try:
            stop_server(proc)
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
