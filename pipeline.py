"""
Fantasy Football data pipeline.

Replaces the 15-step manual README process with a single CLI command.
Each step checks its input files before running and writes canonical output
files that the next step reads.

Usage:
    py pipeline.py --year 2025
    py pipeline.py --year 2025 --steps scrape,positions,faab
    py pipeline.py --year 2025 --from-step players
    py pipeline.py --year 2025 --steps players --dry-run

Steps (run in this order):
    scrape      API + Selenium: matchups, standings -> consolidated_master.csv,
                all_regular_season_thru_YEAR.csv, all_playoffs_thru_YEAR.csv
    positions   Selenium: season-total player scores -> position_ranks_thru_YEAR.csv
    faab        Selenium: FAAB transactions -> faab_thru_YEAR.csv
    players     Fuzzy name reconciliation -- interactive review of any new
                players not yet in lkup_player.csv / names_dict.csv
    draft       Draft data compilation -> full_seasons_draft_df.csv,
                plus adds is_drafted column to regular season data
    composite   Verify all inputs for composite_ranks.ipynb are present
                (open the notebook and run all cells to generate rankings)
"""

import argparse
import sys
import os
import traceback
import pandas as pd

import config
from config import (
    LEAGUE_URLS,
    LKUP_PLAYER_PATH,
    NAMES_DICT_PATH,
    CONSOLIDATED_MASTER_PATH,
    STANDINGS_PATH,
    LEAGUE_DF_PATH,
    MANAGERS_DF_PATH,
    rs_matchups_path,
    playoffs_path,
    position_ranks_path,
    faab_path,
    year_rs_path,
    year_playoffs_path,
    year_positions_path,
    year_faab_path,
)

STEP_ORDER = ["pre_auth", "scrape", "positions", "faab", "players", "draft", "composite"]

LOG_PATH = "pipeline.log"


# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

class _Tee:
    """Write to both the original stream and a log file simultaneously."""
    def __init__(self, stream, log_file):
        self._stream = stream
        self._log = log_file

    def write(self, data):
        self._stream.write(data)
        self._log.write(data)
        self._log.flush()

    def flush(self):
        self._stream.flush()
        self._log.flush()

    def __getattr__(self, attr):
        return getattr(self._stream, attr)


def _setup_logging() -> None:
    """Redirect stdout/stderr to pipeline.log (appends; timestamped header per run)."""
    log_file = open(LOG_PATH, "a", encoding="utf-8", buffering=1)
    import datetime
    log_file.write(f"\n{'='*70}\nPipeline run: {datetime.datetime.now()}\n{'='*70}\n")
    sys.stdout = _Tee(sys.__stdout__, log_file)
    sys.stderr = _Tee(sys.__stderr__, log_file)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _require_file(path: str, step: str) -> None:
    if not os.path.exists(path):
        print(f"[{step}] ERROR: required input file not found: {path}")
        sys.exit(1)


def _prev_year(year: int) -> int:
    """Return the previous year that has data (skip 2008)."""
    seasons = config.SEASONS
    idx = seasons.index(year) if year in seasons else -1
    return seasons[idx - 1] if idx > 0 else year


def _append_and_save(existing_path: str, new_df: pd.DataFrame, key_col: str = None) -> pd.DataFrame:
    """Append new_df to existing CSV, dedup on key_col if provided, save."""
    if os.path.exists(existing_path):
        existing = pd.read_csv(existing_path)
        combined = pd.concat([existing, new_df], ignore_index=True)
    else:
        combined = new_df.copy()
    if key_col and key_col in combined.columns:
        combined.drop_duplicates(subset=[key_col], inplace=True)
    combined.to_csv(existing_path, index=False)
    return combined


# ---------------------------------------------------------------------------
# Step: pre_auth
# ---------------------------------------------------------------------------

def step_pre_auth(year: int, dry_run: bool = False) -> None:
    """
    Open Chrome and navigate to the Yahoo Fantasy league page for manual login.

    Yahoo requires authentication before any Selenium scraping can proceed.
    Run this step once in your own terminal, log in when the browser opens,
    then press Enter. The Chrome profile saves the session so that all
    subsequent Selenium steps (scrape, positions, faab) skip the login page.

    This step MUST be run in a terminal where you can type (not via Claude Code),
    because it calls input() to wait for your confirmation.

    Usage:
        py pipeline.py --year 2025 --steps pre_auth
    """
    if year not in LEAGUE_URLS:
        print(f"[pre_auth] ERROR: no league URL configured for {year}.")
        sys.exit(1)

    league_url = LEAGUE_URLS[year]

    print(f"\n[pre_auth] Opening Chrome to: {league_url}")

    if dry_run:
        print("[pre_auth] DRY RUN — no browser opened.")
        return

    from scrapers.driver import get_driver, quit_driver

    driver = get_driver()
    driver.get(league_url)

    print("\n[pre_auth] Browser is open.")
    print("  1. Log in to Yahoo if prompted")
    print("  2. Confirm you can see the fantasy league page")
    print("  3. Press Enter here to save the session and close the browser")
    input()

    quit_driver(driver)
    print("[pre_auth] Session saved to Chrome profile.")
    print("  You can now run scrape/positions/faab without re-authenticating.")


# ---------------------------------------------------------------------------
# Step: scrape
# ---------------------------------------------------------------------------

def step_scrape(year: int, dry_run: bool = False) -> None:
    """
    Scrape league settings, managers, standings via Yahoo API.
    Scrape weekly matchups (RS + playoffs) via Selenium.
    Append new year's data to master files.
    """
    if year not in LEAGUE_URLS:
        print(f"[scrape] ERROR: no league URL configured for {year}. Add it to config.py.")
        sys.exit(1)

    league_url = LEAGUE_URLS[year]
    prev = _prev_year(year)

    print(f"\n[scrape] Year: {year}  League: {league_url}")

    if dry_run:
        print("[scrape] DRY RUN — no network calls or file writes.")
        return

    # --- API: league settings + managers + standings ---
    from scrapers.yahoo_api import connect, get_leagues, get_or_update_league_settings
    from scrapers.yahoo_api import get_or_update_managers, get_standings

    print("[scrape] Connecting to Yahoo API...")
    football = connect()

    # yahoo_fantasy_api's league_ids() calls users;use_login=1/games/teams which
    # can fail with auth errors unrelated to the OAuth token itself. Fall back to
    # the local league_df_master.csv cache, then to a single known key derived
    # from the league URL + the cache entry for this year.
    try:
        leagues = get_leagues(football)
    except RuntimeError as exc:
        print(f"[scrape] WARNING: league_ids() failed ({exc!s:.120})")
        print("[scrape] Falling back to local league key cache...")
        if os.path.exists(LEAGUE_DF_PATH):
            import pandas as _pd
            _ldf = _pd.read_csv(LEAGUE_DF_PATH)
            _keys = _ldf[_ldf['season'] == year]['league_key'].tolist()
            if _keys:
                leagues = _keys
                print(f"[scrape] Using cached league key(s): {leagues}")
            else:
                print(f"[scrape] ERROR: no league key found in {LEAGUE_DF_PATH} for {year}.")
                print("  Run the API once with a working token, or add the key manually.")
                sys.exit(1)
        else:
            print(f"[scrape] ERROR: {LEAGUE_DF_PATH} not found. Cannot determine league key.")
            sys.exit(1)

    print("[scrape] Fetching league settings...")
    get_or_update_league_settings(football, leagues, LEAGUE_DF_PATH)

    print("[scrape] Fetching manager data...")
    manager_df = get_or_update_managers(football, leagues, MANAGERS_DF_PATH)

    print("[scrape] Fetching standings...")
    use_selenium_standings = False
    try:
        standings = get_standings(football, leagues, manager_df)
        standings.to_csv(STANDINGS_PATH, index=False)
        print(f"[scrape] Standings saved → {STANDINGS_PATH}")
    except RuntimeError as exc:
        print(f"[scrape] WARNING: API standings failed ({exc!s:.80})")
        print("[scrape] Will scrape standings via Selenium after matchup scraping.")
        standings = None
        use_selenium_standings = True

    # --- Selenium: regular season matchups ---
    rs_out = year_rs_path(year)
    from scrapers.driver import get_driver, quit_driver
    from scrapers.yahoo_selenium import scrape_regular_season_matchups

    print("[scrape] Opening Chrome for regular season matchups...")
    driver = get_driver()
    try:
        _, rs_fails = scrape_regular_season_matchups(driver, league_url, checkpoint_path=rs_out)
        print(f"[scrape] RS matchups saved → {rs_out}")
    finally:
        quit_driver(driver)

    # --- Selenium: playoff matchups ---
    po_out = year_playoffs_path(year)
    from scrapers.yahoo_selenium import scrape_playoff_matchups

    print("[scrape] Opening Chrome for playoff matchups...")
    driver = get_driver()
    try:
        _, po_fails = scrape_playoff_matchups(driver, league_url, checkpoint_path=po_out)
        print(f"[scrape] Playoff matchups saved → {po_out}")
    finally:
        quit_driver(driver)

    # --- Compile: append to all-season master files ---
    _require_file(rs_out, "scrape")
    _require_file(po_out, "scrape")

    rs_new = pd.read_csv(rs_out)
    po_new = pd.read_csv(po_out)

    # Add derived columns to RS
    rs_new["league_id"] = rs_new["league_url"].str.split("/").str[-1]
    rs_new["manager_key"] = rs_new["league_id"].astype(str) + "." + rs_new["manager_id"].astype(str)
    rs_new["score"] = pd.to_numeric(rs_new["score"], errors="coerce").fillna(0)
    rs_new["season"] = str(year)

    po_new["league_id"] = po_new["league_url"].str.split("/").str[-1]
    po_new["manager_key"] = po_new["league_id"].astype(str) + "." + po_new["manager_id"].astype(str)
    po_new["score"] = pd.to_numeric(po_new["score"], errors="coerce").fillna(0)
    po_new["season"] = str(year)

    # Append to master — use the previous year's file as the base, write as current year
    rs_master_out = rs_matchups_path(year)
    po_master_out = playoffs_path(year)

    rs_prev = rs_matchups_path(prev)
    po_prev = playoffs_path(prev)

    if not os.path.exists(rs_master_out):
        if os.path.exists(rs_prev):
            base_rs = pd.read_csv(rs_prev)
        else:
            base_rs = pd.DataFrame()
        combined_rs = pd.concat([base_rs, rs_new], ignore_index=True)
        combined_rs.to_csv(rs_master_out, index=False)
        print(f"[scrape] RS master saved → {rs_master_out}  ({len(combined_rs)} rows)")
    else:
        print(f"[scrape] {rs_master_out} already exists — not overwriting.")

    if not os.path.exists(po_master_out):
        if os.path.exists(po_prev):
            base_po = pd.read_csv(po_prev)
        else:
            base_po = pd.DataFrame()
        combined_po = pd.concat([base_po, po_new], ignore_index=True)
        combined_po.to_csv(po_master_out, index=False)
        print(f"[scrape] Playoffs master saved → {po_master_out}  ({len(combined_po)} rows)")
    else:
        print(f"[scrape] {po_master_out} already exists — not overwriting.")

    # --- Build consolidated_master ---
    if use_selenium_standings:
        from scrapers.driver import get_driver, quit_driver
        from scrapers.yahoo_selenium import (
            scrape_standings,
            scrape_schedule_results,
            scrape_playoff_seeds,
        )
        from scrapers.yahoo_api import compute_playoff_wins

        print("[scrape] Opening Chrome for standings, schedule results, and playoff seeds...")
        driver = get_driver()
        try:
            raw_std = scrape_standings(driver, league_url)
            manager_ids = raw_std["manager_id"].astype(str).tolist()
            sched_df = scrape_schedule_results(driver, league_url, manager_ids=manager_ids)
            seed_map = scrape_playoff_seeds(driver, league_url)
        finally:
            quit_driver(driver)

        # Derive all columns needed by the composite rank pipeline.
        league_id_str = league_url.rstrip("/").split("/")[-1]
        game_id = ""
        if os.path.exists(LEAGUE_DF_PATH):
            _ldf = pd.read_csv(LEAGUE_DF_PATH)
            _match = _ldf[_ldf["season"] == year]
            if not _match.empty:
                game_id = str(_match.iloc[0]["league_key"]).split(".")[0]

        n_teams = len(raw_std)
        raw_std["season"]       = year
        raw_std["league_id"]    = league_id_str
        raw_std["manager_key"]  = league_id_str + "." + raw_std["manager_id"].astype(str)
        raw_std["league_key"]   = f"{game_id}.l.{league_id_str}" if game_id else ""
        raw_std["team_key"]     = raw_std["manager_id"].apply(
            lambda m: f"{game_id}.l.{league_id_str}.t.{m}" if game_id else ""
        )

        # --- Playoff seeds from bracket scraper ---
        raw_std["playoff_seed"] = raw_std["manager_id"].astype(str).map(seed_map).fillna(raw_std["rank"])
        raw_std["playoff_seed"] = raw_std["playoff_seed"].astype(int)

        # --- W/L/PA/percentage/rs_score from schedule results ---
        if not sched_df.empty:
            sched_df["manager_id"] = sched_df["manager_id"].astype(str)
            # W/L/T counted from any row with a result (even if score is missing)
            wlt_agg = (
                sched_df.groupby("manager_id")
                .agg(
                    wins=("result", lambda x: (x == "W").sum()),
                    losses=("result", lambda x: (x == "L").sum()),
                    ties=("result", lambda x: (x == "T").sum()),
                )
                .reset_index()
            )
            wlt_agg["percentage"] = wlt_agg.apply(
                lambda r: round(r.wins / (r.wins + r.losses + r.ties), 4)
                if (r.wins + r.losses + r.ties) > 0 else 0.0,
                axis=1,
            )
            # Scores only from rows where both values parsed
            score_agg = (
                sched_df.dropna(subset=["score", "opponent_score"])
                .groupby("manager_id")
                .agg(rs_score=("score", "sum"), points_against=("opponent_score", "sum"))
                .reset_index()
            )
            score_agg["rs_score"] = score_agg["rs_score"].round(2)
            score_agg["points_against"] = score_agg["points_against"].round(2)

            sched_agg = wlt_agg.merge(score_agg, on="manager_id", how="left")
            raw_std["manager_id"] = raw_std["manager_id"].astype(str)
            raw_std = raw_std.merge(sched_agg, on="manager_id", how="left")
        else:
            print("[scrape] WARNING: no schedule results collected — W/L/PA/rs_score will be empty.")
            for _col in ("wins", "losses", "ties", "points_against", "percentage", "rs_score"):
                if _col not in raw_std.columns:
                    raw_std[_col] = ""

        raw_std["playoff_wins"] = raw_std.apply(
            lambda r: compute_playoff_wins(n_teams, int(r["rank"]), int(r["playoff_seed"])),
            axis=1,
        )
        for _col in ("outcome_totals", "streak", "moves", "faab_balance", "diff"):
            if _col not in raw_std.columns:
                raw_std[_col] = ""

        standings = raw_std
        _append_season_to_master(year, standings, rs_master_out, po_master_out)
    else:
        _build_consolidated_master(year, standings, rs_master_out, po_master_out)

    # --- Scrape step summary ---
    total_fails = rs_fails + po_fails
    print(f"\n[scrape] ── Scrape summary for {year} ──────────────────────────────")
    print(f"[scrape]   RS matchup failures:      {rs_fails}")
    print(f"[scrape]   Playoff matchup failures:  {po_fails}")
    if total_fails == 0:
        print(f"[scrape]   Result: CLEAN — no failures, no re-run needed.")
    else:
        print(f"[scrape]   Result: {total_fails} failure(s) due to rate limiting — re-run scrape to fill gaps.")
    print(f"[scrape] ────────────────────────────────────────────────────────────")


def _build_consolidated_master(
    year: int,
    standings: pd.DataFrame,
    rs_master_path: str,
    po_master_path: str,
) -> None:
    """Merge standings + RS points + playoff points into consolidated_master.csv."""
    print("[scrape] Building consolidated_master...")

    rs_all = pd.read_csv(rs_master_path)
    po_all = pd.read_csv(po_master_path)

    # Clean manager keys (guard against .1 vs .10 Excel corruption)
    for df in (rs_all, po_all):
        df["manager_key"] = (
            df["league_id"].astype(str) + "." + df["manager_id"].astype(str)
        )

    rs_agg = (
        rs_all[["manager_key", "score"]]
        .groupby("manager_key")["score"]
        .sum()
        .reset_index()
        .rename(columns={"score": "rs_score"})
    )
    po_agg = (
        po_all[["manager_key", "score"]]
        .groupby("manager_key")["score"]
        .sum()
        .reset_index()
        .rename(columns={"score": "p_score"})
    )

    standings = standings.copy()
    standings["manager_key"] = standings["manager_key"].astype(str)

    master = (
        standings
        .merge(rs_agg, on="manager_key", how="left")
        .merge(po_agg, on="manager_key", how="left")
    )
    master.to_csv(CONSOLIDATED_MASTER_PATH, index=False)
    print(f"[scrape] consolidated_master saved → {CONSOLIDATED_MASTER_PATH}  ({len(master)} rows)")
    print(
        "  NOTE: Review for manual overrides (playoff point corrections, co-manager "
        "duplicates) before running composite_ranks."
    )


def _append_season_to_master(
    year: int,
    standings: pd.DataFrame,
    rs_master_path: str,
    po_master_path: str,
) -> None:
    """
    Append one season's rows to consolidated_master.csv (Selenium standings path).

    Used when only the current year's standings are available (API fallback).
    Loads the existing master, removes any stale rows for this year, computes
    rs_score and revised_p_score from the cumulative RS/playoff files, then
    saves the combined result.
    """
    print("[scrape] Building consolidated_master (append mode)...")

    rs_all = pd.read_csv(rs_master_path)
    po_all = pd.read_csv(po_master_path)

    for df in (rs_all, po_all):
        df["manager_key"] = df["league_id"].astype(str) + "." + df["manager_id"].astype(str)

    rs_year = rs_all[rs_all["season"].astype(str) == str(year)]
    po_year = po_all[po_all["season"].astype(str) == str(year)] if "season" in po_all.columns else po_all

    po_agg = (
        po_year.groupby("manager_key")["score"].sum()
        .reset_index().rename(columns={"score": "revised_p_score"})
    )

    new_rows = standings.copy()

    # Only recompute rs_score from matchup data if it wasn't already populated
    # (e.g. from scrape_schedule_results in the Selenium standings path).
    if "rs_score" not in new_rows.columns or new_rows["rs_score"].isna().all():
        rs_agg = (
            rs_year.groupby("manager_key")["score"].sum()
            .reset_index().rename(columns={"score": "rs_score"})
        )
        new_rows = new_rows.merge(rs_agg, on="manager_key", how="left")

    new_rows = new_rows.merge(po_agg, on="manager_key", how="left")

    if os.path.exists(CONSOLIDATED_MASTER_PATH):
        existing = pd.read_csv(CONSOLIDATED_MASTER_PATH)
        existing = existing[existing["season"].astype(str) != str(year)]
        combined = pd.concat([existing, new_rows], ignore_index=True)
    else:
        combined = new_rows

    combined.to_csv(CONSOLIDATED_MASTER_PATH, index=False)
    print(f"[scrape] consolidated_master saved → {CONSOLIDATED_MASTER_PATH}  ({len(combined)} rows)")
    print(
        "  NOTE: Review for manual overrides (playoff point corrections, co-manager "
        "duplicates) before running composite_ranks."
    )


# ---------------------------------------------------------------------------
# Step: positions
# ---------------------------------------------------------------------------

def step_positions(year: int, dry_run: bool = False) -> None:
    """Scrape season-total position scores and append to position_ranks master."""
    if year not in LEAGUE_URLS:
        print(f"[positions] ERROR: no league URL for {year}.")
        sys.exit(1)

    league_url = LEAGUE_URLS[year]
    prev = _prev_year(year)
    out_year = year_positions_path(year)
    master_out = position_ranks_path(year)

    print(f"\n[positions] Year: {year}")

    if dry_run:
        print("[positions] DRY RUN — no network calls or file writes.")
        return

    pos_fails: list[str] = []

    if os.path.exists(out_year):
        print(f"[positions] {out_year} already exists — skipping scrape.")
    else:
        from scrapers.driver import get_driver, quit_driver
        from scrapers.yahoo_selenium import scrape_position_scores

        print("[positions] Opening Chrome...")
        driver = get_driver()
        try:
            pos_df, pos_fails = scrape_position_scores(driver, league_url)
            pos_df["season"] = year
            pos_df.to_csv(out_year, index=False)
            print(f"[positions] Saved → {out_year}")
        finally:
            quit_driver(driver)

    _require_file(out_year, "positions")
    new_pos = pd.read_csv(out_year)

    # Add position_rank within each position group
    rank_dfs = []
    for pos, group in new_pos.groupby("position"):
        group = group.sort_values("score", ascending=False).copy()
        group["position_rank"] = range(1, len(group) + 1)
        rank_dfs.append(group)
    new_pos_ranked = pd.concat(rank_dfs, ignore_index=True)

    if not os.path.exists(master_out):
        prev_master = position_ranks_path(prev)
        if os.path.exists(prev_master):
            base = pd.read_csv(prev_master)
        else:
            base = pd.DataFrame()
        combined = pd.concat(
            [base, new_pos_ranked[["player_name", "position", "player_url", "position_rank", "season"]]],
            ignore_index=True,
        )
        combined.to_csv(master_out, index=False)
        print(f"[positions] Master saved → {master_out}  ({len(combined)} rows)")
    else:
        print(f"[positions] {master_out} already exists — not overwriting.")

    print(f"\n[positions] ── Positions summary for {year} ────────────────────────")
    if pos_fails:
        print(f"[positions]   Failed positions: {pos_fails}")
        print(f"[positions]   Result: INCOMPLETE — re-run positions to retry failed positions.")
    else:
        print(f"[positions]   Result: CLEAN — all positions scraped successfully.")
    print(f"[positions] ─────────────────────────────────────────────────────────")


# ---------------------------------------------------------------------------
# Step: faab
# ---------------------------------------------------------------------------

def step_faab(year: int, dry_run: bool = False) -> None:
    """Scrape FAAB transactions and append to faab master."""
    if year not in LEAGUE_URLS:
        print(f"[faab] ERROR: no league URL for {year}.")
        sys.exit(1)
    if year < config.FAAB_START_YEAR:
        print(f"[faab] Skipping {year} — FAAB not used before {config.FAAB_START_YEAR}.")
        return

    league_url = LEAGUE_URLS[year]
    prev = _prev_year(year)
    out_year = year_faab_path(year)
    master_out = faab_path(year)

    print(f"\n[faab] Year: {year}")

    if dry_run:
        print("[faab] DRY RUN — no network calls or file writes.")
        return

    faab_warnings: list[str] = []

    if os.path.exists(out_year):
        print(f"[faab] {out_year} already exists — skipping scrape.")
    else:
        from scrapers.driver import get_driver, quit_driver
        from scrapers.yahoo_selenium import scrape_faab

        print("[faab] Opening Chrome...")
        driver = get_driver()
        try:
            faab_df, faab_warnings = scrape_faab(driver, league_url)
            faab_df.to_csv(out_year, index=False)
            print(f"[faab] Saved → {out_year}")
        finally:
            quit_driver(driver)

    _require_file(out_year, "faab")
    new_faab = pd.read_csv(out_year)
    new_faab["season"] = str(year)

    if not os.path.exists(master_out):
        prev_master = faab_path(prev)
        if os.path.exists(prev_master):
            base = pd.read_csv(prev_master)
        else:
            base = pd.DataFrame()
        combined = pd.concat([base, new_faab], ignore_index=True)
        combined.to_csv(master_out, index=False)
        print(f"[faab] Master saved → {master_out}  ({len(combined)} rows)")
    else:
        print(f"[faab] {master_out} already exists — not overwriting.")

    print(f"\n[faab] ── FAAB summary for {year} ──────────────────────────────────")
    if faab_warnings:
        for w in faab_warnings:
            print(f"[faab]   WARNING: {w}")
        print(f"[faab]   Result: CHECK WARNINGS — data may be incomplete.")
    else:
        print(f"[faab]   Result: CLEAN — {len(new_faab)} records collected.")
    print(f"[faab] ──────────────────────────────────────────────────────────────")


# ---------------------------------------------------------------------------
# Step: players
# ---------------------------------------------------------------------------

def step_players(year: int, dry_run: bool = False) -> None:
    """
    Find new players from this year's draft + FAAB that aren't in the lookup
    tables, then run the interactive fuzzy-match review.

    After this step, lkup_player.csv and names_dict.csv are up to date and
    the draft step will not have silent blanks.
    """
    print(f"\n[players] Year: {year}")

    from processors.players import PlayerLookup

    # Collect new player names from every source for this year
    new_players: list[tuple[str, str]] = []

    # From draft file
    draft_file_csv = os.path.join(config.DRAFT_RESULTS_DIR, f"{year}.csv")
    draft_file_xlsx = os.path.join(config.DRAFT_RESULTS_DIR, f"{year}.xlsx")
    if os.path.exists(draft_file_csv):
        draft_df = pd.read_csv(draft_file_csv)
    elif os.path.exists(draft_file_xlsx):
        draft_df = pd.read_excel(draft_file_xlsx)
    else:
        draft_df = None

    if draft_df is not None:
        if "Player Raw" in draft_df.columns and "Player" not in draft_df.columns:
            draft_df = draft_df.rename(columns={"Player Raw": "Player"})
        new_players += list(
            draft_df[["Player", "Position"]].drop_duplicates().itertuples(index=False, name=None)
        )

    # From FAAB file
    faab_out = year_faab_path(year)
    if os.path.exists(faab_out):
        faab_df = pd.read_csv(faab_out)
        if "player_name" in faab_df.columns and "position" in faab_df.columns:
            new_players += list(
                faab_df[["player_name", "position"]]
                .drop_duplicates()
                .itertuples(index=False, name=None)
            )

    # Normalize position aliases before checking
    new_players = [
        (name, config.POSITION_ALIASES.get(pos, pos))
        for name, pos in new_players
    ]

    if dry_run:
        print(f"[players] DRY RUN — would check {len(set(new_players))} unique players.")
        return

    _require_file(LKUP_PLAYER_PATH, "players")
    _require_file(NAMES_DICT_PATH, "players")

    lkup = PlayerLookup()
    unmatched = lkup.find_unmatched(list(set(new_players)))

    if not unmatched:
        print(f"[players] All {len(set(new_players))} players already in lookup tables. Nothing to do.")
        return

    print(f"[players] Found {len(unmatched)} player(s) not in lookup tables.")
    print("[players] Starting interactive review...")
    lkup.batch_review(unmatched)


# ---------------------------------------------------------------------------
# Step: draft
# ---------------------------------------------------------------------------

def step_draft(year: int, dry_run: bool = False) -> None:
    """
    Compile draft data for this year, score it, and append to full_seasons_draft_df.csv.
    Also adds is_drafted flag to the regular season master file.
    """
    DRAFT_OUT = "full_seasons_draft_df.csv"
    rs_master = rs_matchups_path(year)

    print(f"\n[draft] Year: {year}")

    _require_file(LKUP_PLAYER_PATH, "draft")
    _require_file(NAMES_DICT_PATH, "draft")
    _require_file(position_ranks_path(year), "draft")
    _require_file(rs_master, "draft")

    if dry_run:
        print("[draft] DRY RUN — no file writes.")
        return

    from processors.players import PlayerLookup
    from processors.draft import compile_season, add_is_drafted, add_position_rank_ids, compute_actual_position_ranks

    print("[draft] Loading reference data...")
    lkup = PlayerLookup()

    position_ranks = pd.read_csv(position_ranks_path(year))
    position_ranks = add_position_rank_ids(position_ranks)
    position_ranks = compute_actual_position_ranks(position_ranks)

    matchup_df = pd.read_csv(year_rs_path(year))

    print(f"[draft] Compiling {year} draft data...")
    season_df = compile_season(year, lkup, position_ranks, matchup_df)

    # Warn about players that couldn't be resolved
    missing = season_df[season_df["player_id"] == ""]
    if not missing.empty:
        print(
            f"[draft] WARNING: {len(missing)} player(s) have no player_id. "
            "Run 'players' step or edit lkup_player.csv manually:"
        )
        for _, row in missing.iterrows():
            print(f"  {row['Owner']:15}  {row['Player']:30}  {row['Position']}")

    # Append / replace current year in full draft file
    if os.path.exists(DRAFT_OUT):
        existing = pd.read_csv(DRAFT_OUT)
        existing = existing[existing["Year"].astype(str) != str(year)]
        combined = pd.concat([existing, season_df], ignore_index=True)
    else:
        combined = season_df

    combined.to_csv(DRAFT_OUT, index=False)
    print(f"[draft] Draft data saved → {DRAFT_OUT}  ({len(combined)} rows total)")

    # Enrich regular season file with is_drafted
    print("[draft] Adding is_drafted flag to regular season data...")
    rs_df = pd.read_csv(rs_master)

    # Need player_id in rs_df
    if "player_id" not in rs_df.columns:
        rs_df["player_id"] = rs_df["player_url"].apply(
            lambda url: str(url).rstrip("/").split("/")[-1] if pd.notna(url) else ""
        )

    # Need manager_name in rs_df (canonical, not team name)
    if "manager_name" not in rs_df.columns:
        if os.path.exists(CONSOLIDATED_MASTER_PATH):
            master = pd.read_csv(CONSOLIDATED_MASTER_PATH)
            name_map = master[["league_id", "name", "manager"]].drop_duplicates()
            rs_df = rs_df.merge(
                name_map, left_on=["league_id", "manager"], right_on=["league_id", "name"], how="left"
            )
            rs_df.rename(columns={"manager_x": "manager", "manager_y": "manager_name"}, inplace=True)
        else:
            print("[draft] WARNING: consolidated_master.csv not found — is_drafted may be incomplete.")
            rs_df["manager_name"] = rs_df.get("manager", "")

    rs_df = add_is_drafted(rs_df, combined)
    rs_df.to_csv(rs_master, index=False)
    print(f"[draft] is_drafted added → {rs_master}")


# ---------------------------------------------------------------------------
# Step: composite
# ---------------------------------------------------------------------------

def step_composite(year: int, dry_run: bool = False) -> None:
    """
    Verify all inputs for composite_ranks.ipynb are present.
    The notebook handles computation and charts; this step ensures the pipeline
    inputs are ready before you open the notebook.
    """
    from config import (
        CONSOLIDATED_MASTER_PATH, OVERRIDES_PATH, DRAFT_DF_PATH,
    )

    print(f"\n[composite] Year: {year}")

    required = [
        CONSOLIDATED_MASTER_PATH,
        rs_matchups_path(year),
        playoffs_path(year),
        faab_path(year),
        DRAFT_DF_PATH,
        OVERRIDES_PATH,
    ]

    all_present = True
    for path in required:
        if os.path.exists(path):
            print(f"[composite]  OK  {path}")
        else:
            print(f"[composite]  MISSING  {path}")
            all_present = False

    if not all_present:
        print("[composite] ERROR: Missing inputs. Run earlier pipeline steps first.")
        sys.exit(1)

    if dry_run:
        print("[composite] DRY RUN -- all input checks complete.")
        return

    print("[composite] All inputs present.")
    print("[composite] Open composite_ranks.ipynb and run all cells to generate rankings.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_args(argv=None):
    parser = argparse.ArgumentParser(
        description="Fantasy Football data pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--year", type=int, required=True,
        help="Season year to process (e.g. 2025)",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--steps",
        help="Comma-separated list of steps to run (e.g. scrape,positions)",
    )
    group.add_argument(
        "--from-step",
        dest="from_step",
        choices=STEP_ORDER,
        help="Run all steps starting from this one",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print what would be done without making network calls or writing files",
    )
    return parser.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    year = args.year
    dry_run = args.dry_run

    # Determine which steps to run
    if args.steps:
        steps = [s.strip() for s in args.steps.split(",")]
        invalid = [s for s in steps if s not in STEP_ORDER]
        if invalid:
            print(f"ERROR: Unknown step(s): {invalid}. Valid: {STEP_ORDER}")
            sys.exit(1)
    elif args.from_step:
        start = STEP_ORDER.index(args.from_step)
        steps = STEP_ORDER[start:]
    else:
        steps = STEP_ORDER

    if not dry_run:
        _setup_logging()

    print(f"Fantasy Football Pipeline — {year}")
    print(f"Steps: {' -> '.join(steps)}")
    if dry_run:
        print("DRY RUN MODE")

    step_fns = {
        "pre_auth":  step_pre_auth,
        "scrape":    step_scrape,
        "positions": step_positions,
        "faab":      step_faab,
        "players":   step_players,
        "draft":     step_draft,
        "composite": step_composite,
    }

    for step in steps:
        try:
            step_fns[step](year, dry_run=dry_run)
        except KeyboardInterrupt:
            print(f"\n[{step}] Interrupted by user. Progress so far has been saved.")
            sys.exit(0)
        except Exception as exc:
            print(f"\n[{step}] FAILED: {exc}")
            traceback.print_exc()
            raise

    print(f"\nPipeline complete for {year}.")
    if "draft" in steps:
        print("Next: open composite_ranks.ipynb to compute and review final rankings.")


if __name__ == "__main__":
    main()
