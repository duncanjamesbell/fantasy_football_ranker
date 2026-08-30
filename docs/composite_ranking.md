# Composite Ranking System

The composite rank is a single score per manager that aggregates performance across 10 metrics. Higher is better. Scores are computed in `metrics/composite.py` and rendered in `composite_ranks.ipynb`.

---

## Metric Weights

Weights represent the maximum number of points a manager can earn on that dimension. The top-ranked manager on each metric receives the full weight; everyone else receives a fraction based on how close they are (see Scoring below).

| Metric | Default Weight | Category |
|---|---|---|
| `rs_points` | 38 | Manager-controlled |
| `season_rank` | 15 | Manager-controlled |
| `rs_points_against` | 8 | Points-against |
| `playoff_points` | 8 | Manager-controlled |
| `draft_efficiency` | 6 | Manager-controlled |
| `undrafted_savvy` | 6 | Manager-controlled |
| `playoff_win_percentage` | 6 | Win percentages |
| `rs_win_percentage` | 5 | Win percentages |
| `playoff_points_against` | 5 | Points-against |
| `faab_efficiency` | 3 | Manager-controlled |

Weights can be overridden in the notebook. A model-based weight derivation is also available (`use_model_weights=True`), which distributes weights proportionally within three buckets (manager-controlled, win percentages, points-against) using configurable overall bucket weights.

**Model-derived weights were refreshed 2026-08-30.** The original 2023 fit trained on `before_claude/transformed_pre_fanasy_data.csv` (2007-2022, since superseded by data-quality fixes -- playoff-win derivation, rank corrections, co-manager dedup). The refresh rebuilds that same input table from the current, corrected pipeline through 2025 (`before_claude/transformed_pre_fantasy_data_refreshed.csv`) and reruns the identical methodology (see below). A cluster bootstrap (2000 resamples by manager) was then used to sanity-check the single-fit result -- the values now in `metrics/composite.py` are bootstrap-median coefficients, not the raw single-fit output, because the single fit's `undrafted_savvy` and `faab_efficiency` jumps sat near the edge of their own 90% intervals. `win_percentage_weights` and `points_against_weights` barely moved and are unaffected by this distinction. Full rebuild + bootstrap code: `_refresh_model_weights.py` (root).

A separate lagged-outcome experiment (season *N* metrics predicting season *N+1* rank, to sidestep `season_rank` being partly a mechanical function of its own predictors) was tried and abandoned -- it scored negative mean R² in every bucket, i.e. no detectable year-over-year predictive signal at this sample size (146 manager-year pairs across 14 managers). Its coefficients were not used for weighting.

---

## Scoring: `create_metric_dict`

Most metrics use **variance-based cascading**. The top performer receives the full weight; each subsequent manager receives a fraction of the previous manager's score, proportional to the gap between their values.

```
Sort all managers by metric value (best first).
For each manager i (0-indexed):
  if i == 0:
    score = full weight
  else:
    gap_i      = |value[i-1] - value[i]|
    total_gaps = sum of all gaps
    score_i    = score_{i-1} * (1 - gap_i / total_gaps)
```

The practical effect: a manager clustered closely with the top performer loses little score, while a manager far behind loses a large fraction. Ties receive the same score.

**Points-against metrics** (`rs_points_against`, `playoff_points_against`) use **linear scaling** instead: `score = value * weight`. These metrics reward facing tougher opponents, so the raw value (total points surrendered) is directly proportional to the score.

---

## Z-Score Normalization

Most metric inputs are normalized per season before being aggregated across seasons. This controls for year-to-year variation in scoring levels (e.g., a high-scoring 2020 should not artificially inflate managers who played that year).

```
z = (value - season_mean) / season_stdev
```

Season means and stdevs are computed from the set of managers active in that season **after** all `overrides.yaml` exclusions are applied (e.g., the David Casstevens 2009 invalid-season row is excluded before computing the 2009 season mean/stdev).

---

## Recency Bonus

Seasons within the trailing `recency_window` (default: 5 seasons) receive a bonus applied to the z-score before de-normalization:

```
z_boosted = z * (1 + recency_bonus)
```

The boosted z-score is then de-normalized back to original units:

```
modified_value = z_boosted * season_stdev + season_mean
```

This formula applies to `rs_win_percentage`, `playoff_win_percentage`, `season_rank`, and `faab_efficiency`. The de-normalization uses the **same season's** mean and stdev as the original normalization step — each row uses its own season's parameters, not a shared variable.

> **Note:** The original Colab notebook had `mean` and `stdev` swapped in the `playoff_win_percentage` de-normalization, and used a stale loop variable for `faab_efficiency` de-normalization. Both are fixed in `metrics/composite.py`. See `CHANGELOG.md` (2026-08-01) for details.

---

## Data Preprocessing (`_preprocess_master`)

Before any calculation, `consolidated_master.csv` is passed through a correction pipeline that applies all entries in `data/reference/overrides.yaml`. Steps run in this order:

1. **Exclusions** — Remove rows for known invalid entries (e.g., API artifacts, co-managers counted under another account).
2. **Generic dedup** — For any manager with more than one row in a season, keep the row with the lowest (best) rank value.
3. **Row reattributions** — Some scraped rows are attributed to the wrong manager (co-manager account stored as primary manager). These are relabeled before dedup discards the duplicate.
4. **Rank corrections** — Fix rank values that remain wrong after dedup (primarily 2020, where co-manager mix-up scrambled all ranks).
5. **Playoff score corrections** — Overwrite `revised_p_score` with manually verified values. A `corrected: null` entry sets the value to NaN (manager did not make playoffs).
6. **Playoff wins corrections** — Overwrite `playoff_wins` with manually verified values.
7. **Playoff seed corrections** — Overwrite `playoff_seed` with manually verified values.

---

## League Size

The rank-to-score lookup table (`RANK_WEIGHTS`) exists for league sizes 6, 8, and 10. The correct size for each season is resolved by `_get_league_size()`, which prefers `overrides.yaml` over the observed manager count. This matters for early seasons (2007: 6 managers, 2009: 8 managers) and co-manager seasons where post-dedup row counts are lower than actual league size.

---

## Parameters

| Parameter | Default | Description |
|---|---|---|
| `start_year` | 2015 | Earliest season included in composite calculations |
| `thru_year` | (notebook) | Most recent season included |
| `recency_bonus` | 0.15 | Z-score multiplier for recent seasons (15%) |
| `recency_window` | 5 | Number of trailing seasons that receive the bonus |
| `use_model_weights` | True | Use proportional weight distribution across buckets |
| `manager_controlled_overall_weight` | 0.75 | Share of total weight for manager-controlled metrics |
| `win_percentages_overall_weight` | 0.12 | Share for win percentage metrics |
| `points_against_overall_weight` | 0.13 | Share for points-against metrics |
| `season_rank_weight` | 15 | Weight for season rank (set separately from bucket math) |

---

## Output DataFrames

`calculate_composite_ranks()` returns two DataFrames:

- **`compiled_final_scores`** — One row per manager. Columns: one per metric score, plus `total_score`. This is the primary output used for rankings.
- **`raw_scores`** — The intermediate per-manager-per-season metric values before aggregation. Useful for debugging and per-season breakdowns.

---

## Comparison Utility

`_compare_metrics.py` (root level) re-implements the original Colab logic alongside the refactored logic and prints a side-by-side delta table for every metric. Run it to verify that any future changes to `metrics/composite.py` produce expected score differences:

```bash
py _compare_metrics.py
```
