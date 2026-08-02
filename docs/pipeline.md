# Annual Update Guide

Each season, run the pipeline to collect new data, reconcile player names, compile draft scores, and verify all inputs are ready for the composite ranking notebook.

---

## Prerequisites

- Chrome installed (Selenium steps open a browser window)
- Yahoo OAuth credentials in `.env` (see `.env.example`)
- New season's league URL added to `LEAGUE_URLS` in `config.py`

---

## Running the Pipeline

```bash
# Run all steps for a new season
py pipeline.py --year 2025

# Run specific steps only
py pipeline.py --year 2025 --steps scrape,positions

# Resume from a specific step (runs that step and all after)
py pipeline.py --year 2025 --from-step players

# Preview what would run without network calls or file writes
py pipeline.py --year 2025 --dry-run
```

---

## Steps

### 1. `scrape`
Connects to the Yahoo Fantasy API and Selenium to collect:
- League settings and manager list
- Weekly regular season matchup scores
- Playoff matchup scores
- Final standings

Outputs (appended to master files in `data/processed/`):
- `consolidated_master.csv` — one row per manager per season
- `all_regular_season_thru_{YEAR}.csv`
- `all_playoffs_thru_{YEAR}.csv`

**After this step:** Review `consolidated_master.csv` for obvious scraping errors before continuing. Known error patterns (co-manager duplicates, wrong playoff totals) are handled automatically via `overrides.yaml`, but new seasons may have new issues.

### 2. `positions`
Scrapes season-total position scores (how many points each player position earned across all rosters in the league). Used by `draft_efficiency` and `undrafted_savvy` metrics.

Output: `data/processed/position_ranks_thru_{YEAR}.csv`

### 3. `faab`
Scrapes FAAB (Free Agent Acquisition Budget) transaction history. FAAB data begins in 2017; earlier seasons are skipped automatically.

Output: `data/processed/faab_thru_{YEAR}.csv`

### 4. `players` *(interactive)*
Finds any players in this year's draft sheet or FAAB log that are not yet in `data/reference/lkup_player.csv`. Runs an interactive fuzzy-match review to resolve them.

**This step requires manual input.** For each unrecognized player, you confirm or override the fuzzy match against the existing player database.

### 5. `draft`
Compiles draft data for the new season and scores it using position ranks. Appends to `data/processed/full_seasons_draft_df.csv`. Also adds an `is_drafted` flag to the regular season matchup data.

Requires the new year's draft sheet at `data/reference/draft_results/{YEAR}.csv` (or `.xlsx`).

### 6. `composite`
Verifies all required input files for `composite_ranks.ipynb` are present. Does not compute rankings itself — that happens in the notebook.

After this step passes, open `composite_ranks.ipynb` and run all cells.

---

## Manual Corrections

Scraping occasionally produces wrong values. Known corrections for all historical seasons are stored in `data/reference/overrides.yaml`. After a new scrape, check these categories and add entries as needed:

| Category | YAML key | When needed |
|---|---|---|
| Invalid season rows | `exclude_manager_seasons` | API artifact or test entry |
| Co-manager duplicates | `co_manager_dedup.row_reattributions` | Yahoo stored both accounts separately |
| Wrong playoff totals | `p_score_overrides` | Scraper summed wrong weeks |
| Wrong playoff wins | `playoff_wins_overrides` | Co-manager mix-up |
| Wrong playoff seeds | `playoff_seed_overrides` | Co-manager mix-up |
| Wrong league size | `league_sizes` | Expansion/contraction year |

The pipeline applies all overrides at runtime — `consolidated_master.csv` stores the raw scraped values, and the composite ranking module corrects them on the fly. This keeps the source data auditable.

---

## Common Issues

**Selenium can't find Chrome driver**
Run `py pipeline.py --year 2025 --steps scrape --dry-run` to confirm the step is recognized, then check `chromedriver/` is present and matches your Chrome version.

**Player name not resolving in draft step**
Run the `players` step first. If a player still can't be resolved, add them manually to `data/reference/lkup_player.csv` using the Yahoo player URL to derive the `player_id`.

**Wrong playoff score for new season**
Add a `p_score_overrides` entry in `overrides.yaml`. Store the raw scraped value in `consolidated_master.csv` and the corrected value in `corrected:`. The pipeline will apply the override at runtime.

**Two managers share the same Yahoo account (co-manager)**
Add entries to `co_manager_dedup.row_reattributions` and `rank_corrections` in `overrides.yaml`. See the 2014–2022 entries as examples.
