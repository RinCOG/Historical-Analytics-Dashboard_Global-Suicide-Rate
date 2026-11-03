from __future__ import annotations

"""Relationship statistics for the suicide-rate dataset.

Everything here is computed once, offline, from the raw CSV and written to
``data/relationships.json``.  Request-time code only reads that artefact.
"""

import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

from backend.analysis import CSV_PATH, FORMER_STATES, load_and_validate

ROOT = Path(__file__).resolve().parents[1]
RELATIONSHIPS_PATH = ROOT / "data" / "relationships.json"

BOOTSTRAP_SEED = 20260101
BOOTSTRAP_RESAMPLES = 2000
CONFIDENCE_LEVEL = 0.95
FIXED_PANEL_MIN_YEARS = 56
WIDE_PANEL_MIN_YEARS = 40
MIN_WINDOW_OBSERVATIONS = 1
SENSITIVITY_MIN_OBSERVATIONS = 3
MIN_COVERAGE_YEARS = 10

# Documented, configurable verdict thresholds.  The same dictionary is stored
# in the payload so the methods text and the tests cannot drift apart.
VERDICT_RULES = {
    "A": {
        "judged_on": "Data reliability",
        "favourable": {"spread_below": 0.10},
        "mixed": {"spread_below": 0.30},
        "description": "Not Favourable when the inclusion rules move Pearson r by 0.30 or more; Mixed for 0.10-0.30; Favourable below 0.10.",
    },
    "B1": {
        "judged_on": "Data reliability",
        "favourable": {"spearman_min": 0.80, "n_min": 30},
        "mixed": {"spearman_min": 0.50, "n_min": 30},
        "description": "Favourable when Spearman rho >= 0.80 and n >= 30; Mixed when rho >= 0.50 and n >= 30; otherwise Not Favourable.",
    },
    "B2": {
        "judged_on": "Data reliability",
        "favourable": {"spearman_min": 0.80, "n_min": 30},
        "mixed": {"spearman_min": 0.50, "n_min": 30},
        "description": "Favourable when Spearman rho >= 0.80 and n >= 30; Mixed when rho >= 0.50 and n >= 30; otherwise Not Favourable.",
    },
    "B3": {
        "judged_on": "Data reliability",
        "mixed": {"full_abs_pearson_below": 0.30, "subset_abs_pearson_below": 0.30, "subset_n_min": 30},
        "not_favourable": {"full_abs_pearson_min": 0.50, "subset_abs_pearson_min": 0.50},
        "description": "Mixed when the full-sample |r| < 0.30 and the >=10-year subset |r| < 0.30; Not Favourable when both |r| values are >= 0.50; otherwise Mixed.",
    },
    "B4": {
        "judged_on": "Data reliability",
        "not_favourable": {"pearson_min": 0.50, "n_min": 30},
        "mixed": {"pearson_min": 0.30, "n_min": 30},
        "description": "Not Favourable when Pearson r >= 0.50 and n >= 30; Mixed for 0.30-0.50; Favourable below 0.30.",
    },
}


def _pearson(x, y) -> float:
    x_values = np.asarray(x, dtype=float)
    y_values = np.asarray(y, dtype=float)
    if len(x_values) < 2 or len(y_values) < 2:
        return float("nan")
    if np.std(x_values) == 0 or np.std(y_values) == 0:
        return float("nan")
    return float(np.corrcoef(x_values, y_values)[0, 1])


def _spearman(x, y) -> float:
    x_rank = pd.Series(np.asarray(x, dtype=float)).rank()
    y_rank = pd.Series(np.asarray(y, dtype=float)).rank()
    return _pearson(x_rank, y_rank)


def _bootstrap_cluster(
    frame: pd.DataFrame,
    statistic,
    *,
    entity_column: str = "entity",
    resamples: int = BOOTSTRAP_RESAMPLES,
    seed: int = BOOTSTRAP_SEED,
) -> list[float] | list[None]:
    """Percentile cluster bootstrap, resampling whole entities."""
    if frame.empty:
        return [None, None]
    rng = np.random.default_rng(seed)
    entities = np.array(sorted(frame[entity_column].unique()))
    groups = {entity: group for entity, group in frame.groupby(entity_column)}
    values: list[float] = []
    for _ in range(resamples):
        picked = rng.choice(entities, size=len(entities), replace=True)
        sample = pd.concat([groups[entity] for entity in picked], ignore_index=True)
        try:
            value = float(statistic(sample))
        except (ValueError, ZeroDivisionError, FloatingPointError):
            continue
        if math.isfinite(value):
            values.append(value)
    if not values:
        return [None, None]
    alpha = (1.0 - CONFIDENCE_LEVEL) / 2.0
    return [float(np.quantile(values, alpha)), float(np.quantile(values, 1.0 - alpha))]


def _interval(values: list[float] | list[None]) -> list[float] | None:
    if not values or values[0] is None or values[1] is None:
        return None
    return [round(float(values[0]), 6), round(float(values[1]), 6)]


def _round(value: float | None) -> float | None:
    if value is None or not math.isfinite(float(value)):
        return None
    return round(float(value), 6)


def _demean(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    out["rate_demeaned"] = out["rate"] - out.groupby("entity")["rate"].transform("mean")
    return out


def _row(
    identifier: str,
    label: str,
    description: str,
    frame: pd.DataFrame,
    x_column: str,
    y_column: str,
    *,
    entities: int | None = None,
    statistic=None,
) -> dict:
    if statistic is None:
        statistic = lambda sample: _pearson(sample[x_column], sample[y_column])
    pearson = _pearson(frame[x_column], frame[y_column])
    interval = _interval(_bootstrap_cluster(frame, statistic))
    return {
        "id": identifier,
        "label": label,
        "description": description,
        "n": int(len(frame)),
        "entities": int(entities if entities is not None else frame["entity"].nunique()),
        "pearson": _round(pearson),
        "pearson_ci": interval,
    }


def _window_means(frame: pd.DataFrame, start: int, end: int, min_observations: int) -> pd.DataFrame:
    window = frame[(frame["year"] >= start) & (frame["year"] <= end)]
    grouped = (
        window.groupby(["entity", "code"], as_index=False)
        .agg(mean=("rate", "mean"), observations=("year", "nunique"))
    )
    return grouped[grouped["observations"] >= min_observations].copy()


def _pair_points(
    frame: pd.DataFrame,
    first: tuple[int, int],
    second: tuple[int, int],
    *,
    min_observations: int = MIN_WINDOW_OBSERVATIONS,
    exclude_former_states: bool = False,
) -> pd.DataFrame:
    left = _window_means(frame, first[0], first[1], min_observations)[
        ["entity", "code", "mean", "observations"]
    ].rename(columns={"mean": "x", "observations": "x_obs"})
    right = _window_means(frame, second[0], second[1], min_observations)[
        ["entity", "mean", "observations"]
    ].rename(columns={"mean": "y", "observations": "y_obs"})
    points = left.merge(right, on="entity", how="inner")
    if exclude_former_states:
        points = points[~points["code"].isin(FORMER_STATES.values())].copy()
    points = points.sort_values("entity").reset_index(drop=True)
    points["former_state"] = points["code"].isin(FORMER_STATES.values())
    ranks = points.sort_values(["x", "entity"], ascending=[False, True]).reset_index(drop=True)
    ranks["label_rank"] = ranks.index + 1
    points = points.merge(ranks[["entity", "label_rank"]], on="entity", how="left")
    return points


def _point_rows(points: pd.DataFrame, *, top_labels: int = 0) -> list[dict]:
    rows = []
    for row in points.itertuples():
        rank = int(row.label_rank) if row.label_rank is not None and not pd.isna(row.label_rank) else None
        rows.append(
            {
                "entity": str(row.entity),
                "code": str(row.code),
                "x": round(float(row.x), 6),
                "y": round(float(row.y), 6),
                "x_obs": int(row.x_obs),
                "y_obs": int(row.y_obs),
                "former_state": bool(row.former_state),
                "label_rank": rank if top_labels and rank <= top_labels else None,
            }
        )
    return rows


def _stats(points: pd.DataFrame, x_column: str = "x", y_column: str = "y") -> dict:
    pearson = _pearson(points[x_column], points[y_column])
    spearman = _spearman(points[x_column], points[y_column])
    return {
        "n": int(len(points)),
        "pearson": _round(pearson),
        "pearson_ci": _interval(_bootstrap_cluster(points, lambda sample: _pearson(sample[x_column], sample[y_column]))),
        "spearman": _round(spearman),
        "spearman_ci": _interval(_bootstrap_cluster(points, lambda sample: _spearman(sample[x_column], sample[y_column]))),
    }


def _sensitivity_row(identifier: str, label: str, points: pd.DataFrame) -> dict:
    return {"id": identifier, "label": label, **_stats(points)}


def _verdict(identifier: str, label: str, reason: str, rule: str) -> dict:
    icons = {"Favourable": "✓", "Mixed": "◐", "Not Favourable": "!"}
    return {
        "id": identifier,
        "label": label,
        "judged_on": VERDICT_RULES[identifier]["judged_on"],
        "icon": icons[label],
        "rule": rule,
        "reason": reason,
    }


def _verdict_a(rows: list[dict]) -> dict:
    values = [row["pearson"] for row in rows if row["pearson"] is not None]
    spread = max(values) - min(values)
    rules = VERDICT_RULES["A"]
    if spread >= rules["mixed"]["spread_below"]:
        label = "Not Favourable"
        reason = (
            f"The same year-rate question gives Pearson r values from {min(values):.2f} to "
            f"{max(values):.2f}, a spread of {spread:.2f}. The answer depends on the inclusion rule."
        )
    elif spread >= rules["favourable"]["spread_below"]:
        label = "Mixed"
        reason = f"The inclusion rules move Pearson r by {spread:.2f}, so the answer is partly rule-dependent."
    else:
        label = "Favourable"
        reason = f"Pearson r varies by only {spread:.2f} across the inclusion rules, so the answer is stable."
    return _verdict("A", label, reason, rules["description"])


def _verdict_persistence(identifier: str, stats: dict) -> dict:
    rules = VERDICT_RULES[identifier]
    n = stats["n"]
    rho = stats["spearman"] if stats["spearman"] is not None else -1.0
    if rho >= rules["favourable"]["spearman_min"] and n >= rules["favourable"]["n_min"]:
        label = "Favourable"
        reason = (
            f"Spearman rho = {rho:.2f} with n = {n}: country rankings are stable enough "
            "for country-level comparison across these fixed windows."
        )
    elif rho >= rules["mixed"]["spearman_min"] and n >= rules["mixed"]["n_min"]:
        label = "Mixed"
        reason = f"Spearman rho = {rho:.2f} with n = {n}: rankings are only moderately stable."
    else:
        label = "Not Favourable"
        reason = f"Spearman rho = {rho:.2f} with n = {n}: rankings are not stable enough for country-level comparison."
    return _verdict(identifier, label, reason, rules["description"])


def _verdict_coverage(full: dict, subset: dict) -> dict:
    rules = VERDICT_RULES["B3"]
    full_r = abs(full["pearson"] or 0.0)
    subset_r = abs(subset["pearson"] or 0.0)
    if (
        full_r < rules["mixed"]["full_abs_pearson_below"]
        and subset_r < rules["mixed"]["subset_abs_pearson_below"]
        and subset["n"] >= rules["mixed"]["subset_n_min"]
    ):
        label = "Mixed"
        reason = (
            f"The full-sample association is weak (r = {full['pearson']:.2f}) and it is absent "
            f"among the {subset['n']} countries with at least {MIN_COVERAGE_YEARS} years "
            f"(r = {subset['pearson']:.2f})."
        )
    elif (
        full_r >= rules["not_favourable"]["full_abs_pearson_min"]
        and subset_r >= rules["not_favourable"]["subset_abs_pearson_min"]
    ):
        label = "Not Favourable"
        reason = "A coverage-level association persists among countries with at least 10 years."
    else:
        label = "Mixed"
        reason = "The coverage-level association is weak overall but the subset evidence is not decisive."
    return _verdict("B3", label, reason, rules["description"])


def _verdict_variability(stats: dict) -> dict:
    rules = VERDICT_RULES["B4"]
    r = stats["pearson"] if stats["pearson"] is not None else 0.0
    n = stats["n"]
    if r >= rules["not_favourable"]["pearson_min"] and n >= rules["not_favourable"]["n_min"]:
        label = "Not Favourable"
        reason = (
            f"Pearson r = {r:.2f} with n = {n}: level and variability move together, so one pooled "
            "z-score threshold treats high-variability countries differently."
        )
    elif r >= rules["mixed"]["pearson_min"] and n >= rules["mixed"]["n_min"]:
        label = "Mixed"
        reason = f"Pearson r = {r:.2f} with n = {n}: level and variability are moderately linked."
    else:
        label = "Favourable"
        reason = f"Pearson r = {r:.2f} with n = {n}: level and variability are largely independent."
    return _verdict("B4", label, reason, rules["description"])


def _confidence(stable: bool, *, sparse: bool = False) -> str:
    if sparse:
        return "Low — sensitive to few observations"
    if stable:
        return "High — stable across sensitivity checks"
    return "Medium — sensitive to the inclusion rule"


def _anomaly_sensitivity(frame: pd.DataFrame) -> dict:
    changes = frame.sort_values(["entity", "year"]).copy()
    changes["previous_year"] = changes.groupby("entity")["year"].shift()
    changes["change"] = changes.groupby("entity")["rate"].diff()
    changes = changes[(changes["year"] - changes["previous_year"]) == 1].copy()
    changes["pooled_z"] = (changes["change"] - changes["change"].mean()) / changes["change"].std(ddof=1)
    changes["pooled_flag"] = changes["pooled_z"].abs() > 2
    entity_stats = changes.groupby("entity")["change"].agg(["mean", "std", "count"])
    changes = changes.merge(entity_stats, on="entity", how="left", suffixes=("", "_entity"))
    changes["within_z"] = np.where(
        changes["std"] > 0,
        (changes["change"] - changes["mean"]) / changes["std"],
        0.0,
    )
    changes["within_flag"] = changes["within_z"].abs() > 2
    return {
        "consecutive_changes": int(len(changes)),
        "pooled_zscore_flags": int(changes["pooled_flag"].sum()),
        "within_country_zscore_flags": int(changes["within_flag"].sum()),
        "status_changes": int((changes["pooled_flag"] != changes["within_flag"]).sum()),
        "note": (
            "Sensitivity only. The existing anomaly table is unchanged; it still uses the pooled "
            "z-score rule. Within-country standardisation would flag a different set of changes."
        ),
    }


def compute_relationships(frame: pd.DataFrame) -> dict:
    """Compute every relationship statistic and its stored display payload."""
    counts = frame.groupby("entity")["year"].nunique()
    panel_entities = sorted(counts[counts == FIXED_PANEL_MIN_YEARS].index)
    wide_entities = sorted(counts[counts >= WIDE_PANEL_MIN_YEARS].index)
    panel = frame[frame["entity"].isin(panel_entities)].copy()
    wide = frame[frame["entity"].isin(wide_entities)].copy()

    # Block A ---------------------------------------------------------------
    a1 = _row(
        "A1",
        "All records pooled",
        "Every country-year record from 1950 to 2005.",
        frame,
        "year",
        "rate",
    )
    early = frame[frame["year"] <= 2001].copy()
    a2 = _row(
        "A2",
        "All records, 1950–2001",
        "Records in the period before the late coverage break.",
        early,
        "year",
        "rate",
    )
    panel_demeaned = _demean(panel)
    a3 = _row(
        "A3",
        "Within-country, eight complete panels",
        "Each entity's own mean is subtracted before correlating with year.",
        panel_demeaned,
        "year",
        "rate_demeaned",
        entities=len(panel_entities),
    )
    panel_yearly = panel.groupby("year", as_index=False)["rate"].mean()
    a4_statistic = lambda sample: _pearson(
        sample.groupby("year")["rate"].mean().index,
        sample.groupby("year")["rate"].mean().values,
    )
    a4 = {
        "id": "A4",
        "label": "Yearly mean of the eight panels",
        "description": "The eight entities' yearly mean rate correlated with year.",
        "n": int(len(panel_yearly)),
        "entities": len(panel_entities),
        "pearson": _round(_pearson(panel_yearly["year"], panel_yearly["rate"])),
        "pearson_ci": _interval(_bootstrap_cluster(panel, a4_statistic)),
    }
    wide_demeaned = _demean(wide)
    a5 = _row(
        "A5",
        "Within-country, entities with ≥40 years",
        "Demeaned records for the 32 entities with at least 40 reporting years.",
        wide_demeaned,
        "year",
        "rate_demeaned",
        entities=len(wide_entities),
    )
    a_rows = [a1, a2, a3, a4, a5]
    a_verdict = _verdict_a(a_rows)

    # Block B ---------------------------------------------------------------
    b1_points = _pair_points(frame, (1980, 1989), (1990, 1999))
    b1_stats = _stats(b1_points)
    b1_sensitivity = [
        _sensitivity_row(
            "B1-min3",
            "At least 3 observations in each window",
            _pair_points(frame, (1980, 1989), (1990, 1999), min_observations=3),
        ),
        _sensitivity_row(
            "B1-no-former",
            "Excluding the six OWID former-state entities",
            _pair_points(frame, (1980, 1989), (1990, 1999), exclude_former_states=True),
        ),
    ]
    b1 = {
        "id": "B1",
        "title": "Persistence: 1980s to 1990s",
        "question": "Do countries with higher rates in the 1980s also have higher rates in the 1990s?",
        "x_label": "1980s mean (per 100,000)",
        "y_label": "1990s mean (per 100,000)",
        "windows": {"x": [1980, 1989], "y": [1990, 1999]},
        **b1_stats,
        "points": _point_rows(b1_points, top_labels=10),
        "sensitivity": b1_sensitivity,
        "reference_line": True,
        "verdict": _verdict_persistence("B1", b1_stats),
    }

    b2_points = _pair_points(frame, (1990, 1999), (2000, 2005))
    b2_stats = _stats(b2_points)
    b2_sensitivity = [
        _sensitivity_row(
            "B2-min3",
            "At least 3 observations in each window",
            _pair_points(frame, (1990, 1999), (2000, 2005), min_observations=3),
        ),
        _sensitivity_row(
            "B2-no-former",
            "Excluding the six OWID former-state entities",
            _pair_points(frame, (1990, 1999), (2000, 2005), exclude_former_states=True),
        ),
    ]
    b2 = {
        "id": "B2",
        "title": "Persistence: 1990s to 2000–2005",
        "question": "Do countries with higher rates in the 1990s also have higher rates in 2000–2005?",
        "x_label": "1990s mean (per 100,000)",
        "y_label": "2000–2005 mean (per 100,000)",
        "windows": {"x": [1990, 1999], "y": [2000, 2005]},
        **b2_stats,
        "points": _point_rows(b2_points),
        "sensitivity": b2_sensitivity,
        "reference_line": True,
        "verdict": _verdict_persistence("B2", b2_stats),
    }

    country = (
        frame.groupby(["entity", "code"], as_index=False)
        .agg(mean=("rate", "mean"), years=("year", "nunique"))
        .rename(columns={"mean": "y", "years": "x"})
    )
    country["x_obs"] = country["x"]
    country["y_obs"] = country["x"]
    country["former_state"] = country["code"].isin(FORMER_STATES.values())
    country["label_rank"] = None
    b3_all = _stats(country, "x", "y")
    b3_subset_frame = country[country["x"] >= MIN_COVERAGE_YEARS].copy()
    b3_subset = _stats(b3_subset_frame, "x", "y")
    b3_sensitivity = [
        _sensitivity_row("B3-min5", "At least 5 years reported", country[country["x"] >= 5]),
        _sensitivity_row("B3-min10", "At least 10 years reported (subset)", b3_subset_frame),
        _sensitivity_row("B3-min20", "At least 20 years reported", country[country["x"] >= 20]),
    ]
    b3 = {
        "id": "B3",
        "title": "Coverage vs level",
        "question": "Are countries with more reported years systematically higher or lower?",
        "x_label": "Years reported",
        "y_label": "Country mean (per 100,000)",
        "cutoff": MIN_COVERAGE_YEARS,
        "cutoff_label": "10-year cutoff",
        **b3_all,
        "points": _point_rows(country.sort_values("entity")),
        "subset": {"id": "B3-subset", "label": "At least 10 years reported", **b3_subset},
        "sensitivity": b3_sensitivity,
        "reference_line": False,
        "verdict": _verdict_coverage(b3_all, b3_subset),
    }

    variability = (
        frame.groupby(["entity", "code"], as_index=False)
        .agg(mean=("rate", "mean"), sd=("rate", "std"), observations=("year", "nunique"))
    )
    variability = variability[variability["observations"] >= MIN_COVERAGE_YEARS].copy()
    variability = variability.rename(columns={"mean": "x", "sd": "y", "observations": "x_obs"})
    variability["y_obs"] = variability["x_obs"]
    variability["former_state"] = variability["code"].isin(FORMER_STATES.values())
    variability["label_rank"] = None
    b4_stats = _stats(variability, "x", "y")
    b4_sensitivity = [
        _sensitivity_row("B4-min5", "At least 5 observations", frame.groupby(["entity", "code"], as_index=False).agg(mean=("rate", "mean"), sd=("rate", "std"), observations=("year", "nunique")).query("observations >= 5").rename(columns={"mean": "x", "sd": "y"})),
        _sensitivity_row("B4-min10", "At least 10 observations (main rule)", variability),
        _sensitivity_row("B4-min20", "At least 20 observations", frame.groupby(["entity", "code"], as_index=False).agg(mean=("rate", "mean"), sd=("rate", "std"), observations=("year", "nunique")).query("observations >= 20").rename(columns={"mean": "x", "sd": "y"})),
    ]
    b4 = {
        "id": "B4",
        "title": "Level vs variability",
        "question": "Do countries with higher mean rates also have more variable yearly rates?",
        "x_label": "Country mean (per 100,000)",
        "y_label": "SD of yearly rates (per 100,000)",
        "min_observations": MIN_COVERAGE_YEARS,
        **b4_stats,
        "points": _point_rows(variability.sort_values("entity")),
        "sensitivity": b4_sensitivity,
        "reference_line": False,
        "verdict": _verdict_variability(b4_stats),
    }

    anomaly_sensitivity = _anomaly_sensitivity(frame)

    # Takeaways are generated from the stored numbers, not hard-coded in the UI.
    takeaways = {
        "A": (
            f"Across all records the year–rate correlation is about zero (r = {a1['pearson']:.2f}), "
            f"but it is {a3['pearson']:.2f} within the eight complete panels and {a4['pearson']:.2f} "
            "for their yearly average — the answer depends on who is included."
        ),
        "B1": (
            f"Country means are highly persistent: the 1980s and 1990s means correlate at "
            f"r = {b1['pearson']:.2f} (Spearman {b1['spearman']:.2f}, n = {b1['n']})."
        ),
        "B2": (
            f"Persistence continues into 2000–2005: r = {b2['pearson']:.2f} "
            f"(Spearman {b2['spearman']:.2f}, n = {b2['n']})."
        ),
        "B3": (
            f"Coverage and level are weakly associated overall (r = {b3['pearson']:.2f}), and the "
            f"association is absent among the {b3_subset['n']} countries with at least 10 years "
            f"(r = {b3_subset['pearson']:.2f})."
        ),
        "B4": (
            f"Countries with higher mean rates also tend to have more variable yearly rates "
            f"(r = {b4['pearson']:.2f}, n = {b4['n']}), which matters for pooled anomaly screening."
        ),
    }

    findings = [
        {
            "number": 8,
            "title": "Country rankings are stable across the 1980s and 1990s.",
            "detail": (
                f"The 1980s-to-1990s country means correlate at Pearson r = {b1['pearson']:.2f} "
                f"(95% cluster-bootstrap interval {b1['pearson_ci'][0]:.2f} to {b1['pearson_ci'][1]:.2f}) "
                f"and Spearman rho = {b1['spearman']:.2f} (n = {b1['n']}). The 1990s-to-2000–2005 pair is "
                f"r = {b2['pearson']:.2f}, Spearman rho = {b2['spearman']:.2f} (n = {b2['n']})."
            ),
            "caveat": (
                "One point per entity; window coverage is uneven, and the six OWID former-state entities "
                "are included in the main row but tested separately."
            ),
            "confidence": _confidence(
                all(abs(row["spearman"] - b1["spearman"]) < 0.05 for row in b1_sensitivity)
                and all(abs(row["spearman"] - b2["spearman"]) < 0.05 for row in b2_sensitivity)
            ),
            "section": "relationships",
        },
        {
            "number": 9,
            "title": "Coverage and rate level are not meaningfully associated among countries with at least 10 years.",
            "detail": (
                f"Across all {b3['n']} entities, years reported and country mean correlate at "
                f"Pearson r = {b3['pearson']:.2f} and Spearman rho = {b3['spearman']:.2f}. Among the "
                f"{b3_subset['n']} entities with at least 10 years, Pearson r = {b3_subset['pearson']:.2f} "
                f"and Spearman rho = {b3_subset['spearman']:.2f}."
            ),
            "caveat": "The full sample includes many entities with only three observations; the subset is the relevant comparison.",
            "confidence": _confidence(
                all(abs(row["pearson"] or 0.0) < 0.30 for row in b3_sensitivity[1:])
            ),
            "section": "relationships",
        },
        {
            "number": 10,
            "title": "Level and variability move together, which affects pooled anomaly screening.",
            "detail": (
                f"Among the {b4['n']} entities with at least 10 observations, country mean and the SD of "
                f"yearly rates correlate at Pearson r = {b4['pearson']:.2f} and Spearman rho = {b4['spearman']:.2f}. "
                f"Within-country standardisation would flag {anomaly_sensitivity['within_country_zscore_flags']} "
                f"changes versus {anomaly_sensitivity['pooled_zscore_flags']} under the pooled rule; "
                f"{anomaly_sensitivity['status_changes']} of {anomaly_sensitivity['consecutive_changes']:,} rows "
                "would change status."
            ),
            "caveat": "The existing anomaly table is unchanged; this is a sensitivity note about the screening rule.",
            "confidence": _confidence(
                all((row["pearson"] or 0.0) >= 0.50 for row in b4_sensitivity)
            ),
            "section": "relationships",
        },
        {
            "number": 11,
            "title": "The trend correlation depends on who is included.",
            "detail": (
                f"Pooled Pearson r is {a1['pearson']:.2f} for all {a1['n']:,} records and {a2['pearson']:.2f} "
                f"for 1950–2001 ({a2['n']:,} records). Within the eight complete panels it is {a3['pearson']:.2f} "
                f"(n = {a3['n']}), their yearly average gives {a4['pearson']:.2f} (n = {a4['n']}), and the "
                f"{a5['entities']} entities with at least 40 years give {a5['pearson']:.2f} (n = {a5['n']:,})."
            ),
            "caveat": (
                "A1–A2 mix changing country groups; A4 correlates a yearly average, not individual observations. "
                "These are descriptive associations only."
            ),
            "confidence": _confidence(False),
            "section": "relationships",
        },
    ]

    payload = {
        "version": 1,
        "source": "SDG-3___suicide-rates-by-country.csv",
        "period": {"from": int(frame["year"].min()), "to": int(frame["year"].max())},
        "bootstrap": {
            "method": "entity-cluster percentile bootstrap",
            "resamples": BOOTSTRAP_RESAMPLES,
            "seed": BOOTSTRAP_SEED,
            "confidence": CONFIDENCE_LEVEL,
            "interval": "2.5th to 97.5th percentile",
        },
        "verdict_rules": VERDICT_RULES,
        "block_a": {
            "id": "A",
            "title": "One question, three answers",
            "question": "Is year correlated with the reported suicide rate?",
            "rows": a_rows,
            "verdict": a_verdict,
            "message": takeaways["A"],
            "chart_note": "A1–A2 pool records and mix changing country groups. A4 correlates a yearly average, not individual observations.",
        },
        "block_b": {"B1": b1, "B2": b2, "B3": b3, "B4": b4},
        "takeaways": takeaways,
        "anomaly_sensitivity": anomaly_sensitivity,
        "findings": findings,
        "methods": {
            "block_a": "Pearson r between year and rate, computed on the stated inclusion set. A3 and A5 subtract each entity's own mean rate before correlating with year. A4 correlates the eight-panel yearly mean with year.",
            "windows": {
                "B1": {"x": [1980, 1989], "y": [1990, 1999], "minimum_observations": MIN_WINDOW_OBSERVATIONS},
                "B2": {"x": [1990, 1999], "y": [2000, 2005], "minimum_observations": MIN_WINDOW_OBSERVATIONS},
                "B3": {"coverage_cutoff_years": MIN_COVERAGE_YEARS},
                "B4": {"minimum_observations": MIN_COVERAGE_YEARS},
            },
            "bootstrap": "Each interval resamples whole entities with replacement, 2,000 times, using a fixed seed. The interval is the 2.5th–97.5th percentile of the resampled statistic.",
            "verdict_rules": VERDICT_RULES,
            "no_pvalues": "No p-values are reported on pooled country-year data. Observations from the same country are not independent, so p-values would overstate certainty. All associations are descriptive.",
            "causation": "Correlation does not establish causation.",
        },
    }
    return payload


def write_relationships(frame: pd.DataFrame, output: Path = RELATIONSHIPS_PATH) -> dict:
    payload = compute_relationships(frame)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return payload


def load_relationships() -> dict:
    if not RELATIONSHIPS_PATH.exists():
        raise FileNotFoundError(
            f"Relationship results not found at {RELATIONSHIPS_PATH}; run `python -m backend.relationships` first."
        )
    return json.loads(RELATIONSHIPS_PATH.read_text(encoding="utf-8"))


def compact_payload(full: dict) -> dict:
    block_a = full["block_a"]
    return {
        "version": full["version"],
        "source": full["source"],
        "period": full["period"],
        "bootstrap": full["bootstrap"],
        "note": "Fixed periods; not affected by the year range.",
        "anchors": {
            "A": "#relationships-a",
            "B1": "#relationships-b1",
            "B2": "#relationships-b2",
            "B3": "#relationships-b3",
            "B4": "#relationships-b4",
        },
        "block_a": {
            "id": block_a["id"],
            "title": block_a["title"],
            "question": block_a["question"],
            "rows": block_a["rows"][:4],
            "verdict": block_a["verdict"],
            "message": block_a["message"],
        },
        "block_b": {
            key: {
                field: full["block_b"][key][field]
                for field in (
                    "id",
                    "title",
                    "question",
                    "x_label",
                    "y_label",
                    "n",
                    "pearson",
                    "pearson_ci",
                    "spearman",
                    "spearman_ci",
                    "points",
                    "sensitivity",
                    "cutoff",
                    "cutoff_label",
                    "reference_line",
                    "verdict",
                )
                if field in full["block_b"][key]
            }
            for key in ("B1", "B3", "B4")
        },
        "takeaways": {key: full["takeaways"][key] for key in ("A", "B1", "B3", "B4")},
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Compute relationship statistics and write the stored payload.")
    parser.add_argument("--csv", type=Path, default=CSV_PATH)
    parser.add_argument("--output", type=Path, default=RELATIONSHIPS_PATH)
    args = parser.parse_args()
    payload = write_relationships(load_and_validate(args.csv), args.output)
    print(
        json.dumps(
            {
                "output": str(args.output),
                "A1": payload["block_a"]["rows"][0]["pearson"],
                "A3": payload["block_a"]["rows"][2]["pearson"],
                "A4": payload["block_a"]["rows"][3]["pearson"],
                "B1": payload["block_b"]["B1"]["pearson"],
                "B2": payload["block_b"]["B2"]["pearson"],
                "B3": payload["block_b"]["B3"]["pearson"],
                "B4": payload["block_b"]["B4"]["pearson"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
