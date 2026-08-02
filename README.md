## Project Overview

A data science project that ranks fantasy football managers across many seasons using a composite scoring system. The project is specific to a ~10-manager Yahoo league but is structured to be adaptable to any Yahoo league.

Each manager is evaluated across 10 dimensions — points scored, win rate, draft efficiency, FAAB spending, playoff performance, and more. Each dimension is weighted and scored; the sum is a "composite rank" that can be compared across all managers and all seasons.

Data is collected via the Yahoo Fantasy Sports API and Selenium scrapers. All calculation logic is in Python modules; a Jupyter notebook (`composite_ranks.ipynb`) renders the final rankings and charts. Manual data corrections (co-manager accounts, scraping errors) are managed declaratively in `data/reference/overrides.yaml`.

---

## Repository Structure

```
├── composite_ranks.ipynb         # Final rankings notebook (run last)
├── pipeline.py                   # CLI tool for annual data update
├── config.py                     # Central paths, league URLs, name maps
├── CHANGELOG.md                  # Dated record of findings and corrections
│
├── metrics/
│   └── composite.py              # All composite ranking calculation logic
│
├── processors/
│   ├── draft.py                  # Draft data compilation
│   └── players.py                # Player name lookup / fuzzy reconciliation
│
├── scrapers/
│   ├── yahoo_api.py              # Yahoo Fantasy API client
│   ├── yahoo_selenium.py         # Selenium scrapers (matchups, FAAB, positions)
│   └── driver.py                 # Chrome driver setup
│
├── data/
│   ├── processed/                # Canonical compiled files (inputs to composite_ranks.ipynb)
│   │   ├── consolidated_master.csv
│   │   ├── all_regular_season_thru_{YEAR}.csv
│   │   ├── all_playoffs_thru_{YEAR}.csv
│   │   ├── faab_thru_{YEAR}.csv
│   │   ├── full_seasons_draft_df.csv
│   │   └── position_ranks_thru_{YEAR}.csv
│   ├── reference/                # Static inputs checked into git
│   │   ├── overrides.yaml        # Manual data corrections (co-managers, scraping errors)
│   │   ├── lkup_player.csv       # Player ID lookup table
│   │   ├── names_dict.csv        # Player name normalization
│   │   └── draft_results/        # Historical draft sheets by year
│   ├── raw/                      # Year-specific scraped intermediates (gitignored)
│   └── archive/                  # Superseded/dated old files
│
└── docs/
    ├── composite_ranking.md      # Metric definitions, scoring math, recency bonus
    └── pipeline.md               # Annual update guide
```

---

## Annual Update (Quick Reference)

```bash
py pipeline.py --year 2025
```

This runs all six steps in sequence: scrape → positions → faab → players → draft → composite.
Run individual steps with `--steps` or resume from a step with `--from-step`.
See `docs/pipeline.md` for the full guide.

---

## Key Design Decisions

**`overrides.yaml` instead of dated CSV variants**
All manual data corrections (playoff score fixes, co-manager deduplication, row reattributions) live in `data/reference/overrides.yaml`. The pipeline reads and applies them at runtime, so `consolidated_master.csv` is always fully reproducible — no more `consolidated_master_revised_2024_v2.csv` files.

**Module + notebook separation**
All calculation logic lives in `metrics/composite.py`. The notebook (`composite_ranks.ipynb`) only calls the module and renders charts. This makes the logic testable and auditable independent of Jupyter.

**Recency bonus**
Managers are rewarded for recent seasons via a z-score boost applied within a trailing `recency_window` of seasons. The boost is de-normalized correctly as `z_boosted * stdev + mean`. See `docs/composite_ranking.md` for the full math.

---

## Maintenance Notes

- **Special characters**: Yahoo team names sometimes contain Unicode right-single-quote (`'`). The `team_name_fixes` section of `overrides.yaml` normalizes these before any name-based joins.
- **Co-managers**: When a manager shared a Yahoo account, the scraper creates duplicate rows. `overrides.yaml` handles deduplication, row reattribution, and rank/score corrections for all known co-manager seasons (2010–2022).
- **Missing seasons**: 2008 has no data (no league that year). FAAB data starts in 2017.
- **Mike Williams disambiguation**: Two relevant players share this name — handle carefully in `lkup_player.csv`.
