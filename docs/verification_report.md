# Verification Report — Suicide Rates Dashboard (`/`) and In-Depth Analysis (`/analysis`)

**Task:** Confirm, using Python pandas, that every result shown on the project's two
pages is correct against the raw data in `data/SDG-3___suicide-rates-by-country.csv`.

**Scope:** All metrics displayed on the main dashboard (`/`) and the In-Depth Analysis page
(`/analysis`), including cross-page alignment between the two pages.

**Verification method:** Independent recomputation directly from the raw CSV with pandas
(`pd.read_csv` + group/aggregate operations implemented in the script itself, not via the
application's service/aggregation functions) compared against the values served by the running
FastAPI backend through its REST endpoints (the values the frontend displays).

**Deliverables of this task (the only two new files created):**
- `analysis/verify_with_pandas.py`
- `docs/verification_report.md`

No existing file was modified.

---

## 1. Audit of existing verification evidence

| # | Path | What it covers | Independent? | Currently passing? |
|---|---|---|---|---|
| 1 | `backend/tests/test_services.py` | Dashboard data endpoints (`/kpis`, trend, top countries, compare, anomalies, coverage, findings, summary) — via the app's own services over a temporary SQLite ingest | **No** — imports and calls the application's own aggregation functions; compares the app against its own outputs / stored values | Yes (ran once: `python -m unittest backend.tests.test_services backend.tests.test_relationships` → `Ran 25 tests in 141.682s OK`) |
| 2 | `backend/tests/test_relationships.py` | Relationship statistics (Pearson/Spearman), cluster bootstrap, verdict rules, sensitivity | **No** — imports the app's `_pearson`, `_spearman`, `_bootstrap_cluster`, `compute_relationships` | Yes (same 25-test run: OK) |
| 3 | `data/analysis_report.json` | Stored generated analysis report consumed by several endpoints | **No** — stored artefact, not recomputed from the raw CSV | n/a (artifact, not a test) |
| 4 | `data/relationships.json` | Stored relationship payload (blocks A/B, findings, verdicts) | **No** — stored artefact | n/a |
| 5 | `data/metric_registry.json` | Stored metric registry (labels, formats, caveats, verdicts) | **No** — stored artefact | n/a |
| 6 | `README.md` | Documentation of metrics/claims | **No** — documentation only | n/a |
| 7 | *(none found)* | Any standalone pandas verification script, notebook, CI job, or verification report | — | — |

**Audit conclusion:** No pre-existing check satisfied all four independence criteria
(a) raw-CSV pandas recomputation, (b) no use of app aggregation functions for the expected
value, (c) comparison against user-displayed values, and (d) reproducibility with a fixed seed.
The existing tests were therefore treated as **not independent verification** and were re-run
once to confirm they still pass, but they did not replace the need for the new pandas check.

---

## 2. Coverage matrix

| Metric group | Status | Evidence |
|---|---|---|
| Data foundation (rows, entities, ISO/former states, nulls, dups, years, ISO validation, mean/median/quartiles/IQR/fences, outliers, histogram, gaps) | **VERIFIED** | `analysis/verify_with_pandas.py` → `data.foundation.*` (13 checks) |
| Top countries (≥10 observations, former states excluded, ranking variants, Guyana short series) | **VERIFIED** | `analysis/verify_with_pandas.py` → `top.countries.*` (incl. `min_years_1/3/5/10/20`) |
| Global trend (yearly rows, raw peak, fixed panel, wide panel, median, reporting counts, panel-vs-raw direction) | **VERIFIED** | `analysis/verify_with_pandas.py` → `trend.*` |
| Global-mean decomposition (pairs, within/composition components) | **VERIFIED** | `analysis/verify_with_pandas.py` → `decomposition.*` |
| Country comparison (Lithuania full period; sub-range 1980–1995; Japan, Mauritius, Guyana, Dominica) | **VERIFIED** | `analysis/verify_with_pandas.py` → `compare.*` |
| Anomalies (consecutive changes, z-score flags, IQR flags, flagged rows, borderline rows, top concentrations) | **VERIFIED** | `analysis/verify_with_pandas.py` → `anomalies.*` |
| Coverage (analysis + dashboard rows, tiers) | **VERIFIED** | `analysis/verify_with_pandas.py` → `coverage.*` |
| Relationships (blocks A1–A5, B1–B4, bootstrap intervals, verdict rules, sensitivity) | **VERIFIED** | `analysis/verify_with_pandas.py` → `rel.*` |
| Data-quality claims (identical 2004/2005, 2001/2002 move, first reporters 2002, 2002/2005 move) | **VERIFIED** | `analysis/verify_with_pandas.py` → `dataquality.*` |
| Findings / confidence labels / verdicts | **VERIFIED** | `analysis/verify_with_pandas.py` → `findings.*`, `rel.verdict_*` |
| Cross-page alignment (dashboard vs in-depth vs independent, default + sub-range 1980–1995, selected countries) | **VERIFIED** | `analysis/verify_with_pandas.py` → `xpg.*`, `compare.*.range_*` |

**Coverage-matrix decision:** All metrics above are **VERIFIED** by the new independent
pandas script (the new script satisfies criteria (a)–(d): raw CSV via pandas, app-independent
implementations of Pearson/Spearman/bootstrap, comparison against the live API payloads, fixed
bootstrap seed 20260101 / 2000 resamples / 95 % percentile intervals).

---

## 3. Decision taken

**Decision:** Independent recomputation was still required — no pre-existing independent
pandas verification existed in the repository — so the new read-only script
`analysis/verify_with_pandas.py` was written and run to cover the required metrics.

**Final outcome:** `CHECKS_RUN=115 CHECKS_FAILED=0` — the script exited successfully (no failing
check) and every metric it covers reproduces exactly against the values displayed through the API.

---

## 4. Verification table (displayed vs independent pandas value vs result)

Tolerances used: rates ±0.005 (2 decimals), z-scores ±0.0005 (3 decimals), correlations ±0.002,
exact equality for counts and strings.

### 4.1 Data foundation

| Metric | Displayed value | Independent pandas value | Match | Note |
|---|---|---|---|---|
| Row count | 2,843 | 2,843 | ✅ | |
| Entity count | 196 | 196 | ✅ | |
| ISO entity count (excl. former states) | 190 | 190 | ✅ | |
| Former-state entities | 6 (OWID_*) | 6 (OWID_*) | ✅ | |
| Null cells / duplicate entity-year rows / invalid codes / negative rates | 0 / 0 / 0 / 0 | 0 / 0 / 0 / 0 | ✅ | ISO codes validated against `pycountry` (16,090 countries available; no unrecognized codes) |
| Years covered | 1950–2005 (56 years) | 1950–2005 (56 years) | ✅ | |
| Global mean | 11.9502 | 11.9502 | ✅ | |
| Global median | 10.6410 | 10.6410 | ✅ | |
| Q1 / Q3 / IQR | 6.22 / 16.10 / 9.88 | 6.22 / 16.10 / 9.88 | ✅ | pandas default linear quantile method |
| IQR fences | −8.60 / 30.92 | −8.60 / 30.92 | ✅ | Tukey fences (Q1 − 1.5·IQR, Q3 + 1.5·IQR) |
| Outlier count | 82 | 82 | ✅ | |
| Outlier maximum | 44.35 (Lithuania, 1996) | 44.35 (Lithuania, 1996) | ✅ | |
| Outlier top entities | Hungary 22, Lithuania 17, Russia 14 | same | ✅ | |
| Histogram bins | all bins sum to 2,843; 5–10 bin = 820 (28.8 %) | same | ✅ | 5–10: 820; 5–15 (5–10 + 10–15): 1,534 (54.0 %) |
| Yearly gaps within observed span | 331 | 331 | ✅ | |

### 4.2 Top countries

| Metric | Displayed value | Independent pandas value | Match | Note |
|---|---|---|---|---|
| Top-10 (min 10 obs, former states excluded) | Lithuania 35.13 (n=23) #1; Russia 30.77 (n=24) #2 | same | ✅ | |
| Top-10 full list | LT, RU, HU, EE, LV, KZ, BY, SI, FI, UA | same | ✅ | |
| Guyana excluded from top-10; n=3 mean 30.85 | — | 30.85 (3 obs) | ✅ | |
| Rankings at min_years ∈ {1, 3, 5, 10, 20} | all reproduced | same | ✅ | |

### 4.3 Global trend

| Metric | Displayed value | Independent pandas value | Match | Note |
|---|---|---|---|---|
| Raw yearly mean peak | 1982, 14.76, 52 reporters | 1982, 14.76, 52 | ✅ | |
| Fixed panel peak | 1998, 12.21; panel mean of yearly values 10.67 | same | ✅ | Panel = 8 full-period entities |
| Wide panel (≥40 yrs) peak | 1984, 13.01, n=32 | same | ✅ | |
| Annual median peak | 1988, 13.64 | same | ✅ | |
| Reporting counts | reproduced for all 56 years (1950: 10 … 2005: 191) | same | ✅ | |
| Panel below raw mean in 52/52 pre-2002 years; above in 3/4 post-2002 years | reproduced | same | ✅ | |

### 4.4 Decomposition

| Metric | Displayed value | Independent pandas value | Match | Note |
|---|---|---|---|---|
| Decomposition pair count | 22 | 22 | ✅ | |
| 2002→2003 global-mean change | total 2.97 = −0.31 within + 3.29 composition | same | ✅ | |
| 2000→2002 global-mean change | total −2.57 = −0.29 within + −2.28 composition | same | ✅ | |
| Components sum to total | yes (within + composition = total) | yes | ✅ | |

### 4.5 Country comparison

| Metric | Displayed value | Independent pandas value | Match | Note |
|---|---|---|---|---|
| Lithuania vs global & panel (23 reported years) | above both in 23/23; gap vs global 10.58–31.37; vs panel 12.28–33.12 | same | ✅ | |
| Sub-range 1980–1995 — Lithuania/Japan/Mauritius/Guyana/Dominica (dashboard vs in-depth vs independent) | all values equal | same | ✅ | |

### 4.6 Anomalies

| Metric | Displayed value | Independent pandas value | Match | Note |
|---|---|---|---|---|
| Consecutive changes | 2,457 | 2,457 | ✅ | |
| \|z\| > 2 flags | 122 | 122 | ✅ | |
| 1.5×IQR flags | 235 | 235 | ✅ | |
| Both flags | 122 | 122 | ✅ | |
| Change stats (mean/std/fences) | −0.02 / 1.27 / −1.96 / 1.87 | same | ✅ | |
| Flagged rows (all 235: change, z to 3 dp, flags) | reproduced | same | ✅ | |
| Borderline: Estonia 1994 \|z\|=1.999 and Singapore 1982 \|z\|=1.995 not flagged | ✅ | ✅ | ✅ | |
| Top z-flag concentrations | Trinidad & Tobago 12, Mauritius 12, Singapore 10 | same | ✅ | |

### 4.7 Coverage

| Metric | Displayed value | Independent pandas value | Match | Note |
|---|---|---|---|---|
| Coverage rows | 196 | 196 | ✅ | |
| Tiers | 8 full / 122 sparse (≤3 obs) / 331 gaps | same | ✅ | |

### 4.8 Relationships

| Metric | Displayed value | Independent pandas value | Match | Note |
|---|---|---|---|---|
| A1 (all records): r | −0.024, n=2,843 | −0.024, n=2,843 | ✅ | |
| A2 (≤2001): r | 0.086, n=2,216 | 0.086, n=2,216 | ✅ | |
| A3 (8 full-panel entities): r | 0.193, n=448 | 0.193, n=448 | ✅ | |
| A4 (panel yearly mean vs year): r | 0.723, n=56 | 0.723, n=56 | ✅ | |
| A5 (wide panel ≥40 yrs): r | 0.107, n=1,637 | 0.107, n=1,637 | ✅ | |
| B1 (1980s vs 1990s): r | 0.924, n=63; Spearman 0.959 | same | ✅ | Bootstrap 95 % CI reproduced: [0.897, 0.951] |
| B2 (1990s vs 2000–2005): r | 0.946, n=67; Spearman 0.936 | same | ✅ | Bootstrap CI reproduced: [0.914, 0.971] |
| B3 (coverage vs level): r | 0.228 (n=196); subset (n=68) r=−0.047 | same | ✅ | Bootstrap CI reproduced: [0.112, 0.354] |
| B4 (level vs variability): r | 0.715, n=68; Spearman 0.769 | same | ✅ | Bootstrap CI reproduced: [0.592, 0.859] |
| Verdicts | A: Not Favourable; B1: Favourable; B2: Favourable; B3: Mixed; B4: Not Favourable | recomputed from independent values | ✅ | |
| Confidence labels (F8–F11) | High / High / High / Medium | High / High / High / Medium | ✅ | Suffixes: “High — stable across sensitivity checks”, “Medium — sensitive to the inclusion rule” (Unicode em dash preserved correctly in data) |

### 4.9 Data-quality claims

| Metric | Displayed value | Independent pandas value | Match | Note |
|---|---|---|---|---|
| Entities with identical 2004 & 2005 values | 136 of 191 | 136 | ✅ | |
| 62 countries reporting in both 2001 & 2002 moved | 12.36 → 12.26 | same | ✅ | |
| 128 first-reporters in 2002 average | 8.20 | same | ✅ | |
| 190 countries reporting in both 2002 & 2005 moved | 9.52 → 9.66 | same | ✅ | |

### 4.10 Cross-page alignment

| Metric | Displayed value | Independent pandas value | Match | Note |
|---|---|---|---|---|
| Dashboard `/kpis` vs In-depth `/analysis/summary` (default + sub-range) | equal | equal | ✅ | |
| Dashboard `/kpis` (sub-range) vs independent sub-range mean | 13.56 / 71 entities | 13.56 / 71 | ✅ | Sub-range 1980–1995 |
| Dashboard trend vs independent (sub-range) | 16 rows in range | 16 rows in range | ✅ | |
| Relationships compact vs full | equal | equal | ✅ | |
| Coverage dashboard vs in-depth | equal | equal | ✅ | |
| Country comparison sub-range (dashboard vs in-depth vs independent) | equal | equal | ✅ | |

---

## 5. Discrepancies found

**None.**

Every displayed value that was recomputed independently from the raw CSV reproduced exactly
(0 failed checks out of 115). No number, flag, correlation, verdict, or confidence label that the
pages display was found to be wrong against the raw data.

During development of the verification script itself, three sub-range country-comparison checks
reported failures. After root-cause analysis these were confirmed to be **bugs in the verification
script**, not in the application:

1. The fixed-panel baseline was initially recomputed over the *selected sub-range* instead of the
   full observed period (1950–2005), whereas the panel is a fixed full-period construct by design.
2. A sub-range tuple was passed where a year was expected.
3. A NaN-vs-zero comparison for missing panel baselines.

After correcting the script, all sub-range comparisons passed. Final run: **115 checks, 0 failures**.

---

## 6. Unverifiable items and limitations

- **Dataset provenance:** The original source/URL of the underlying data could not be verified
  from the repository alone; only the in-repository CSV was used.
- **Frontend rendering:** Values were compared at the API-payload level (the values rendered by the
  pages). Frontend formatting was checked in source (`formatRate` → 2 decimals via
  `toLocaleString('en', {minimumFractionDigits: 2, maximumFractionDigits: 2})`; `formatZScore` →
  3 decimals via `toFixed(3)`), which is consistent with the stated tolerances. The pages were not
  executed in a browser.
- **Bootstrap randomness:** Reproduced with the repository's documented settings (seed `20260101`,
  2000 cluster-bootstrap resamples, 95 % percentile intervals); intervals matched exactly.
- **Existing tests:** Treated as non-independent (they import app code); run once and passing
  (`Ran 25 tests in 141.682s OK`), but not used as the source of expected values.

---

## 7. Git status confirmation

Pre-existing (unrelated to this verification task, left untouched):

```
 M backend/main.py
 M backend/services.py
 M backend/tests/test_services.py
 M frontend/src/Analysis.tsx
 M frontend/src/App.tsx
 M frontend/src/api.ts
 M frontend/src/styles.css
 M pyproject.toml
 M vercel.json
?? backend/registry.py
?? backend/relationships.py
?? backend/tests/test_relationships.py
?? data/metric_registry.json
?? data/relationships.json
?? frontend/src/RelationshipViews.tsx
?? frontend/src/shared.ts
```

Files created by this verification task (the only permitted new files):

```
?? analysis/verify_with_pandas.py
?? docs/verification_report.md
```

No existing file was modified by this verification task.

---

## 8. Final result

- Independent pandas verification script: `analysis/verify_with_pandas.py`
- Result: **115 checks run, 0 failed** — all displayed values on the dashboard and the
  In-Depth Analysis page were confirmed correct against the raw CSV.
- Conclusion: **Every result shown on the two pages was verified and found correct.**
- Exit code: **0** (script exits non-zero on any failure).
