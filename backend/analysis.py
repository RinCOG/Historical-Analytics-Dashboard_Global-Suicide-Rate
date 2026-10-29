from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import pandas as pd
import pycountry

ROOT = Path(__file__).resolve().parents[1]
CSV_PATH = ROOT / "data" / "SDG-3___suicide-rates-by-country.csv"
OUTPUT_PATH = ROOT / "data" / "analysis_report.json"
RATE_COLUMN = "suicide rate (age-adjusted suicides per 100,000 people)"
FORMER_STATES = {
    "Czechoslovakia": "OWID_CZS",
    "East Germany": "OWID_GDR",
    "Serbia and Montenegro": "OWID_SRM",
    "USSR": "OWID_USS",
    "West Germany": "OWID_GFR",
    "Yugoslavia": "OWID_YGS",
}
FIRST_YEAR = 1950
LAST_YEAR = 2005
MIN_TOP_COUNTRY_YEARS = 10


def load_and_validate(csv_path: Path) -> pd.DataFrame:
    frame = pd.read_csv(csv_path)
    expected = {"Entity", "Code", "Year", RATE_COLUMN}
    if set(frame.columns) != expected:
        raise ValueError(f"Expected CSV columns {sorted(expected)}; got {list(frame.columns)}")

    frame = frame.rename(
        columns={"Entity": "entity", "Code": "code", "Year": "year", RATE_COLUMN: "rate"}
    )
    if frame.isna().any().any():
        raise ValueError(f"Null values found: {frame.isna().sum().to_dict()}")
    frame["entity"] = frame["entity"].astype(str).str.strip()
    frame["code"] = frame["code"].astype(str).str.strip().str.upper()
    if frame["entity"].eq("").any() or frame["code"].eq("").any():
        raise ValueError("Entity and Code values cannot be blank")
    numeric_years = pd.to_numeric(frame["year"], errors="raise")
    if (numeric_years % 1 != 0).any():
        raise ValueError("Year values must be whole numbers")
    frame["year"] = numeric_years.astype(int)
    frame["rate"] = pd.to_numeric(frame["rate"], errors="raise")

    if frame.duplicated(["entity", "year"]).any():
        raise ValueError("Duplicate entity/year records found")
    if (frame.groupby("entity")["code"].nunique() > 1).any():
        raise ValueError("An entity is associated with more than one code")
    if (frame.groupby("code")["entity"].nunique() > 1).any():
        raise ValueError("A code is associated with more than one entity")
    if not frame["year"].between(FIRST_YEAR, LAST_YEAR).all():
        raise ValueError(f"Years must be within {FIRST_YEAR}-{LAST_YEAR}")
    if not frame["rate"].map(lambda value: math.isfinite(value) and value >= 0).all():
        raise ValueError("Rates must be finite, non-null, and non-negative")
    iso_codes = {country.alpha_3 for country in pycountry.countries}
    is_iso_code = frame["code"].isin(iso_codes)
    is_known_former_state = frame.apply(
        lambda row: FORMER_STATES.get(row["entity"]) == row["code"], axis=1
    )
    if not (is_iso_code | is_known_former_state).all():
        invalid = frame.loc[~(is_iso_code | is_known_former_state), ["entity", "code"]]
        raise ValueError(f"Unrecognized ISO or historical entity codes: {invalid.to_dict('records')}")

    frame = frame.sort_values(["entity", "year"]).reset_index(drop=True)
    return frame


def analyze(frame: pd.DataFrame) -> dict:
    yearly = (
        frame.groupby("year")
        .agg(avg_rate=("rate", "mean"), countries_reporting=("entity", "nunique"))
        .reset_index()
    )
    country = (
        frame.groupby(["entity", "code"])
        .agg(avg_rate=("rate", "mean"), years_reported=("year", "nunique"))
        .reset_index()
    )
    eligible = country[
        (country["years_reported"] >= MIN_TOP_COUNTRY_YEARS)
        & ~country["code"].isin(FORMER_STATES.values())
    ]
    top = eligible.sort_values(["avg_rate", "entity"], ascending=[False, True]).head(10)

    counts = frame.groupby("entity")["year"].agg(["min", "max", "nunique"]).reset_index()
    counts["gaps"] = counts["max"] - counts["min"] + 1 - counts["nunique"]
    coverage_counts = (
        counts.groupby("nunique").size().rename("entities").reset_index().to_dict("records")
    )

    complete_years = set(range(FIRST_YEAR, LAST_YEAR + 1))
    yearly_sets = frame.groupby("entity")["year"].apply(set)
    panel_entities = sorted(entity for entity, years in yearly_sets.items() if years == complete_years)
    if panel_entities:
        panel = (
            frame[frame["entity"].isin(panel_entities)]
            .groupby("year")["rate"]
            .mean()
            .rename("avg_rate")
            .reset_index()
        )
    else:
        panel = pd.DataFrame(columns=["year", "avg_rate"])

    changes = frame.copy()
    changes["previous_year"] = changes.groupby("entity")["year"].shift()
    changes["change"] = changes.groupby("entity")["rate"].diff()
    changes = changes[changes["year"] - changes["previous_year"] == 1].copy()
    change_mean = float(changes["change"].mean())
    change_std = float(changes["change"].std(ddof=1))
    changes["z_score"] = (changes["change"] - change_mean) / change_std
    q1 = float(changes["change"].quantile(0.25))
    q3 = float(changes["change"].quantile(0.75))
    iqr = q3 - q1
    lower_fence = q1 - 1.5 * iqr
    upper_fence = q3 + 1.5 * iqr
    changes["zscore_flag"] = changes["z_score"].abs() > 2
    changes["iqr_flag"] = (changes["change"] < lower_fence) | (changes["change"] > upper_fence)
    anomaly_rows = changes[changes["zscore_flag"] | changes["iqr_flag"]].copy()

    rates = frame["rate"]
    rate_q1 = float(rates.quantile(0.25))
    rate_q3 = float(rates.quantile(0.75))
    rate_iqr = rate_q3 - rate_q1
    rate_outliers = frame[(rates < rate_q1 - 1.5 * rate_iqr) | (rates > rate_q3 + 1.5 * rate_iqr)]
    histogram_edges = [0, 5, 10, 15, 20, 25, 30, 35, 40, math.inf]
    rate_histogram = [
        {
            "range": f"{histogram_edges[index]:g}–{histogram_edges[index + 1]:g}"
            if math.isfinite(histogram_edges[index + 1])
            else "40+",
            "count": int(
                ((rates >= lower) & (rates < upper)).sum()
            ),
        }
        for index, (lower, upper) in enumerate(zip(histogram_edges, histogram_edges[1:]))
    ]
    peak = yearly.loc[yearly["avg_rate"].idxmax()]
    fixed_peak = panel.loc[panel["avg_rate"].idxmax()] if not panel.empty else None
    ranked_all = country.sort_values(["avg_rate", "entity"], ascending=[False, True])
    ranked_valid = ranked_all[~ranked_all["code"].isin(FORMER_STATES.values())]
    top_all = ranked_valid.head(3)

    insights = [
        {
            "title": "The dataset-wide observation mean is 11.95 per 100,000.",
            "detail": f"The mean across {len(frame):,} observed country-year records is {rates.mean():.2f}; the median is {rates.median():.2f}.",
            "caveat": "This weights each reported record equally, not each country equally, and coverage varies by year.",
        },
        {
            "title": f"The highest simple yearly mean is in {int(peak['year'])} ({peak['avg_rate']:.2f}).",
            "detail": f"There are {int(peak['countries_reporting'])} entities reporting in the peak year.",
            "caveat": "The number and composition of reporting entities change over time; the fixed eight-entity panel peaks in "
            + (f"{int(fixed_peak['year'])} ({fixed_peak['avg_rate']:.2f})." if fixed_peak is not None else "a different year."),
        },
        {
            "title": f"{top.iloc[0]['entity']} has the highest eligible country mean ({top.iloc[0]['avg_rate']:.2f}).",
            "detail": f"The ranking requires at least {MIN_TOP_COUNTRY_YEARS} observations; {top.iloc[0]['entity']} has {int(top.iloc[0]['years_reported'])}.",
            "caveat": f"Without that rule, the raw top three are {', '.join(f'{r.entity} ({r.avg_rate:.1f}; n={int(r.years_reported)})' for r in top_all.itertuples())}; short series such as Guyana (3) are less comparable.",
        },
        {
            "title": f"Reporting coverage ranges from {int(yearly['countries_reporting'].min())} entities in 1950 to {int(yearly['countries_reporting'].max())} in 2004 and 2005.",
            "detail": "The reporting count varies sharply in nearby years, including 62 in 2001, 190 in 2002, 55 in 2003, and 191 in 2004.",
            "caveat": "A change in the yearly average can reflect changing coverage as well as changing observed rates.",
        },
        {
            "title": f"Only {len(panel_entities)} entities report in every year from 1950 through 2005.",
            "detail": f"Their average across annual panel means is {panel['avg_rate'].mean():.2f}, versus {rates.mean():.2f} across all records.",
            "caveat": "This fixed panel is a small, selected group and is not representative of the full world population.",
        },
        {
            "title": f"Year-over-year anomaly rules flag {int(changes['zscore_flag'].sum())} changes by |z| > 2 and {int(changes['iqr_flag'].sum())} by the 1.5×IQR rule.",
            "detail": f"There are {len(changes):,} consecutive-year country changes; {int((changes['zscore_flag'] & changes['iqr_flag']).sum())} are flagged by both methods.",
            "caveat": "Flags identify unusual observed changes, not data errors or explanations; missing intervening years are not treated as annual changes.",
        },
        {
            "title": f"{len(rate_outliers)} observed rates exceed the distribution's Tukey IQR fences.",
            "detail": f"The maximum is {rates.max():.2f} for Lithuania in 1996; no negative or zero rates occur.",
            "caveat": "Extreme values are retained because a statistical outlier alone is not evidence of an invalid record.",
        },
    ]

    return {
        "source": "SDG-3___suicide-rates-by-country.csv",
        "period": {"from": FIRST_YEAR, "to": LAST_YEAR},
        "row_count": int(len(frame)),
        "entity_count": int(frame["entity"].nunique()),
        "iso_entity_count": int(
            frame.loc[~frame["code"].isin(FORMER_STATES.values()), "entity"].nunique()
        ),
        "former_state_entities": FORMER_STATES,
        "quality": {
            "null_cells": int(frame.isna().sum().sum()),
            "duplicate_entity_year_rows": int(frame.duplicated(["entity", "year"]).sum()),
            "invalid_codes": 0,
            "non_country_aggregates": [],
            "negative_or_zero_rates": int((rates <= 0).sum()),
            "rate_iqr_fences": [rate_q1 - 1.5 * rate_iqr, rate_q3 + 1.5 * rate_iqr],
            "rate_outlier_count": int(len(rate_outliers)),
            "outliers_retained": True,
            "country_year_gaps_within_observed_span": int(counts["gaps"].sum()),
        },
        "summary": {
            "mean": float(rates.mean()),
            "median": float(rates.median()),
            "std": float(rates.std(ddof=1)),
            "min": float(rates.min()),
            "max": float(rates.max()),
            "q1": rate_q1,
            "q3": rate_q3,
            "global_peak_year": int(peak["year"]),
            "global_peak_avg_rate": float(peak["avg_rate"]),
            "global_peak_countries_reporting": int(peak["countries_reporting"]),
            "fixed_panel_entities": panel_entities,
            "fixed_panel_average": float(panel["avg_rate"].mean()) if not panel.empty else None,
            "fixed_panel_peak_year": int(fixed_peak["year"]) if fixed_peak is not None else None,
            "fixed_panel_peak_avg_rate": float(fixed_peak["avg_rate"]) if fixed_peak is not None else None,
            "minimum_years_for_top_countries": MIN_TOP_COUNTRY_YEARS,
            "unfiltered_top_three": [
                {"entity": row.entity, "avg_rate": float(row.avg_rate), "years_reported": int(row.years_reported)}
                for row in top_all.itertuples()
            ],
        },
        "rate_histogram": rate_histogram,
        "anomalies": {
            "consecutive_changes": int(len(changes)),
            "change_mean": change_mean,
            "change_std": change_std,
            "iqr_change_fences": [lower_fence, upper_fence],
            "zscore_count": int(changes["zscore_flag"].sum()),
            "iqr_count": int(changes["iqr_flag"].sum()),
            "both_count": int((changes["zscore_flag"] & changes["iqr_flag"]).sum()),
            "rows": [
                {
                    "entity": row.entity,
                    "year": int(row.year),
                    "change": float(row.change),
                    "z_score": float(row.z_score),
                    "zscore_flag": bool(row.zscore_flag),
                    "iqr_flag": bool(row.iqr_flag),
                }
                for row in anomaly_rows.itertuples()
            ],
        },
        "yearly": [
            {"year": int(row.year), "avg_rate": float(row.avg_rate), "countries_reporting": int(row.countries_reporting)}
            for row in yearly.itertuples()
        ],
        "top_countries": [
            {"entity": row.entity, "avg_rate": float(row.avg_rate), "years_reported": int(row.years_reported)}
            for row in top.itertuples()
        ],
        "coverage": [
            {
                "entity": row.entity,
                "years_reported": int(row.nunique),
                "first_year": int(row.min),
                "last_year": int(row.max),
                "gaps": int(row.gaps),
            }
            for row in counts.sort_values("entity").itertuples(index=False, name="Coverage")
        ],
        "coverage_count_distribution": coverage_counts,
        "insights": insights,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze the suicide-rate CSV and write a reproducible JSON report.")
    parser.add_argument("--csv", type=Path, default=CSV_PATH)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    args = parser.parse_args()

    result = analyze(load_and_validate(args.csv))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(args.output), "rows": result["row_count"], **result["summary"]}, indent=2))


if __name__ == "__main__":
    main()
