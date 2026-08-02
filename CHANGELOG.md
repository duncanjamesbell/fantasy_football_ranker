# Changelog

All notable changes to this project are documented here, organized by date.

---

## 2026-08-01

### Diagnostic: Composite Ranking Score Discrepancies

Conducted a detailed comparison between the original Google Colab notebook
(`before_claude/PRE_Fantasy_Football_Composite_Ranks_googlecolab.ipynb`) and
the refactored pipeline (`metrics/composite.py` + `composite_ranks.ipynb`) to
identify sources of score differences across all 10 metrics. Three root causes
were identified; two were bugs in the original code now corrected, one is
intentional improved behavior.

---

### Root Cause A — David Casstevens 2009 Invalid Season Excluded (Intentional)

**What changed:** The refactored pipeline suppresses the row
`"David Casstevens (Invalid Season)"` from the 2009 season via the
`exclude_manager_seasons` rule in `data/reference/overrides.yaml`. The original
Colab included this row.

**Why:** This entry is a Yahoo API artifact — David did not actually participate
in the 2009 season. Including it inflated the 2009 `points_for` standard
deviation from 31.33 to 84.93 (a 2.7× distortion), skewing z-scores for all
six real 2009 participants (Duncan, Patrick, Mark, Kevin, Scott, Luke).

**Effect on scores:** All metrics that draw on 2009 data show small but
non-zero deltas versus the original Colab. This is correct behavior — the
refactored numbers are more accurate.

**Relevant config:**
```yaml
# data/reference/overrides.yaml
exclude_manager_seasons:
  - season: 2009
    manager: "David Casstevens (Invalid Season)"
    reason: "Yahoo API artifact; not a real season entry for David"
```

---

### Root Cause B — Playoff Win% Recency Bonus Formula Fixed

**What changed:** The inverse z-score de-normalization for the
`playoff_win_percentage` recency bonus had `mean` and `stdev` swapped.

**Bug (original Colab and initial refactor):**
```python
modified = (z + z * recency_bonus) * p_win_percents_mean + p_win_percents_stdev
```

**Fix (`metrics/composite.py`):**
```python
modified = (z + z * recency_bonus) * p_win_percents_stdev + p_win_percents_mean
```

**Why it matters:** The correct inverse z-score transform is
`z_boosted * stdev + mean`. Swapping them produces a value in entirely the wrong
units and scale. The fix now matches the form used by `rs_win_percentage` and
`season_rank` recency bonuses, which were already correct.

**Affected metric:** `p_win_percent_score` (max |delta| ≈ 0.43 across managers).

---

### Root Cause C — FAAB Recency Bonus Used Stale Loop Variable

**What changed:** In the original Colab, the FAAB efficiency recency bonus
de-normalization used a stale loop variable `season` (the last value from a
preceding `for season in seasons` loop) instead of the current row's season.
This meant all recent-season rows were de-normalized using the same season's
mean/stdev rather than their own.

**Bug (original Colab):**
```python
# `season` retains the last value from a prior loop — wrong for all but the final season
modified = (z + z * recency_bonus) * faab_efficiency_stdev + faab_efficiency_mean
```

**Fix (refactored `metrics/composite.py`):**
```python
f_stdev  = season_data_dict.get(row['season'], {}).get('faab_efficiency_stdev', 1)
f_mean   = season_data_dict.get(row['season'], {}).get('faab_efficiency_mean',  0)
modified = (z + z * recency_bonus) * f_stdev + f_mean
```

**Affected metric:** `faab_efficiency_score` (max |delta| ≈ 0.72 across managers).

---

### Data: 2024 Season Added to Consolidated Master

**What changed:** Appended 10 rows of 2024 season data to
`data/processed/consolidated_master.csv` (146 → 156 rows).

**Details:**
- Luke's raw `p_score` stored as 336.01 (pre-correction value) so the existing
  `overrides.yaml` runtime correction fires to 466.58.
- Fixing `latest_season`: with only thru-2023 data in the master, `latest_season`
  resolved to 2023, causing the recency window to incorrectly include 2019
  instead of 2020. Adding 2024 data corrects this.

**Relevant override:**
```yaml
p_score_overrides:
  - season: 2024
    manager_key: "710941.1"
    manager: "Luke"
    original: 336.01
    corrected: 466.58
```

---

### Utility: Metric Comparison Script Added

`_compare_metrics.py` — standalone script that runs both the original Colab
logic and the refactored `metrics/composite.py` against the same data, then
prints a side-by-side breakdown by metric and by manager showing score deltas.
Useful for validating future changes to the composite ranking pipeline.

---

### Final Score Delta Summary (thru 2024, after all fixes)

| Metric | Identical? | Max \|delta\| | Root Cause |
|---|---|---|---|
| `rs_win_percent_score` | Yes | — | — |
| `draft_efficiency_score` | Yes | — | — |
| `undrafted_savvy_score` | Yes | — | — |
| `rs_points_score` | No | 2.12 | A |
| `rs_points_against_score` | No | 0.07 | A |
| `p_win_percent_score` | No | 0.43 | A + B |
| `p_points_score` | No | 1.39 | A |
| `p_points_against_score` | No | 0.45 | A |
| `weighted_rank_score` | No | 1.45 | A |
| `faab_efficiency_score` | No | 0.72 | C |
| `total_score` | No | 3.45 | A + B + C |

All remaining deltas are attributable to intentional corrections. There are no
unresolved discrepancies.

---

## 2026 (earlier — architecture refactor)

The project was refactored from a monolithic Google Colab notebook into a
module-based Python project. Key changes:

- `metrics/composite.py` — core composite ranking logic extracted into a module
- `composite_ranks.ipynb` — thin notebook that calls the module and renders results
- `data/` hierarchy — structured `raw/`, `processed/`, `reference/` directories
- `data/reference/overrides.yaml` — all manual data corrections made reproducible
  and version-controlled (replaces dated "revised" CSV variants)
- `config.py` — central path configuration
- `_preprocess_master()` pipeline — applies exclusions, deduplication, row
  reattributions, rank corrections, and score overrides in a single auditable pass

See git log for individual commit details.
