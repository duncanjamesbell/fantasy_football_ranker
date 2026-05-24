"""
One-time data directory migration.

Moves files from the flat root layout into the data/ hierarchy defined in
config.py, archives superseded date-stamped variants, and hard-deletes
definitively junk files.

Usage:
    py migrate.py --dry-run    # preview all actions without writing
    py migrate.py --confirm    # execute; writes migration.log
"""

import argparse
import os
import shutil
import glob
import sys
from datetime import datetime

ROOT = os.path.dirname(os.path.abspath(__file__))

# Destination directories (must match config.py)
DATA_REF     = os.path.join(ROOT, "data", "reference")
DATA_REF_DR  = os.path.join(DATA_REF, "draft_results")
DATA_RAW     = os.path.join(ROOT, "data", "raw")
DATA_PROC    = os.path.join(ROOT, "data", "processed")
DATA_ARCHIVE = os.path.join(ROOT, "data", "archive")

LOG_PATH = os.path.join(ROOT, "migration.log")

log_lines: list[str] = []


def log(msg: str) -> None:
    print(msg)
    log_lines.append(msg)


def _src(name: str) -> str:
    return os.path.join(ROOT, name)


def _ensure_dirs(dry_run: bool) -> None:
    for d in [DATA_REF, DATA_REF_DR, DATA_RAW, DATA_PROC, DATA_ARCHIVE]:
        if not os.path.exists(d):
            log(f"  MKDIR  {os.path.relpath(d, ROOT)}")
            if not dry_run:
                os.makedirs(d, exist_ok=True)


# ---------------------------------------------------------------------------
# Action helpers
# ---------------------------------------------------------------------------

def _copy(src_name: str, dest_dir: str, dry_run: bool, rename: str = None) -> None:
    src = _src(src_name)
    if not os.path.exists(src):
        log(f"  SKIP   {src_name} (not found)")
        return
    dest_name = rename if rename else src_name
    dest = os.path.join(dest_dir, dest_name)
    rel_dest = os.path.relpath(dest, ROOT)
    if os.path.exists(dest):
        log(f"  EXISTS {rel_dest} — skipping copy")
        return
    log(f"  COPY   {src_name} -> {rel_dest}")
    if not dry_run:
        shutil.copy2(src, dest)


def _move_dir_contents(src_dir_name: str, dest_dir: str, dry_run: bool) -> None:
    src_dir = os.path.join(ROOT, src_dir_name)
    if not os.path.exists(src_dir):
        log(f"  SKIP   {src_dir_name}/ (not found)")
        return
    for fname in os.listdir(src_dir):
        src = os.path.join(src_dir, fname)
        if os.path.isfile(src):
            dest = os.path.join(dest_dir, fname)
            rel_dest = os.path.relpath(dest, ROOT)
            if os.path.exists(dest):
                log(f"  EXISTS {rel_dest} — skipping")
            else:
                log(f"  COPY   {src_dir_name}/{fname} -> {rel_dest}")
                if not dry_run:
                    shutil.copy2(src, dest)


def _archive(src_name: str, dry_run: bool) -> None:
    src = _src(src_name)
    if not os.path.exists(src):
        return
    dest = os.path.join(DATA_ARCHIVE, src_name)
    rel_dest = os.path.relpath(dest, ROOT)
    if os.path.exists(dest):
        log(f"  EXISTS {rel_dest} — skipping archive")
        return
    log(f"  ARCHIVE {src_name} -> {rel_dest}")
    if not dry_run:
        shutil.copy2(src, dest)


def _delete(src_name: str, dry_run: bool) -> None:
    src = _src(src_name)
    if not os.path.exists(src):
        return
    log(f"  DELETE {src_name}")
    if not dry_run:
        os.remove(src)


def _glob_archive(pattern: str, dry_run: bool) -> None:
    for path in sorted(glob.glob(os.path.join(ROOT, pattern))):
        _archive(os.path.basename(path), dry_run)


# ---------------------------------------------------------------------------
# Migration steps
# ---------------------------------------------------------------------------

def migrate(dry_run: bool) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    log(f"{'='*60}")
    log(f"Fantasy Football Migration  {'[DRY RUN]' if dry_run else '[LIVE]'}  {ts}")
    log(f"{'='*60}")

    _ensure_dirs(dry_run)

    # ------------------------------------------------------------------
    # 1. Reference data
    # ------------------------------------------------------------------
    log("\n--- Reference files -> data/reference/ ---")
    _copy("lkup_player.csv",    DATA_REF, dry_run)
    _copy("names_dict.csv",     DATA_REF, dry_run)

    log("\n--- Draft Results -> data/reference/draft_results/ ---")
    _move_dir_contents("Draft Results", DATA_REF_DR, dry_run)

    # ------------------------------------------------------------------
    # 2. Processed master files -> data/processed/
    # ------------------------------------------------------------------
    log("\n--- Master files -> data/processed/ ---")
    _copy("consolidated_master.csv",          DATA_PROC, dry_run)
    _copy("standings_master_latest.csv",      DATA_PROC, dry_run)
    _copy("league_df_master.csv",             DATA_PROC, dry_run)
    _copy("managers_df_master.csv",           DATA_PROC, dry_run)
    _copy("all_regular_season_thru_2024.csv", DATA_PROC, dry_run)
    _copy("all_playoffs_thru_2024.csv",       DATA_PROC, dry_run)
    _copy("position_ranks_thru_2024.csv",     DATA_PROC, dry_run)
    _copy("faab_thru_2024.csv",               DATA_PROC, dry_run)

    # Canonical draft master — pick the most recent dated version
    log("\n--- Draft master -> data/processed/full_seasons_draft_df.csv ---")
    for candidate in [
        "full_seasons_draft_df_20250806.csv",
        "full_seasons_draft_df thru 2023.csv",
    ]:
        if os.path.exists(_src(candidate)):
            _copy(candidate, DATA_PROC, dry_run, rename="full_seasons_draft_df.csv")
            break

    # ------------------------------------------------------------------
    # 3. Year-specific raw intermediates -> data/raw/
    # ------------------------------------------------------------------
    log("\n--- Year-specific intermediates -> data/raw/ ---")
    seasons = [
        2007, 2009, 2010, 2011, 2012, 2013, 2014, 2015,
        2016, 2017, 2018, 2019, 2020, 2021, 2022, 2023, 2024,
    ]
    for year in seasons:
        for suffix in ["_pre_matchups.csv", "_pre_playoffs.csv",
                       "_position_scores.csv", "_faab.csv"]:
            _copy(f"{year}{suffix}", DATA_RAW, dry_run)

    # ------------------------------------------------------------------
    # 4. Archive superseded / date-stamped variants
    # ------------------------------------------------------------------
    log("\n--- Archiving superseded files -> data/archive/ ---")

    # Date-stamped consolidated master variants
    _glob_archive("consolidated_master_revised*.csv", dry_run)
    _glob_archive("consolidated_master w consolation*.csv", dry_run)

    # Old season master files (superseded by thru_2024 versions)
    for year in [2021, 2022, 2023]:
        _glob_archive(f"all_regular_season_thru_{year}*.csv", dry_run)
        _glob_archive(f"all_playoffs_thru_{year}*.csv", dry_run)
        _glob_archive(f"position_ranks_thru_{year}*.csv", dry_run)
        _glob_archive(f"faab_thru_{year}*.csv", dry_run)

    # Date-stamped draft data variants
    _glob_archive("full_seasons_draft_df*.csv", dry_run)

    # Other variant / intermediate files
    for name in [
        "all_regular_season_thru_2024_w_is_drafted.csv",
        "all_playoffs_thru_2024_w_season.csv",
        "all_playoffs_thru_2023 w consolation.csv",
        "all_rs_matchups.csv",
        "2022_position_scores2.csv",
        "all_weeks_for_stats.csv",
        "names_dict_missing.csv",
        "2025 news for formatting.csv",
        "2025_news_formatted.csv",
        "Untitled-1.txt",
        "5c words.csv",
    ]:
        _archive(name, dry_run)

    # Old pre-playoff files explicitly marked old
    _glob_archive("2020_pre_playoffs_old.csv", dry_run)
    _glob_archive("2022_pre_playoffs old.csv", dry_run)
    _glob_archive("2022_position_scores2.csv", dry_run)

    # ------------------------------------------------------------------
    # 5. Hard-delete definitively junk files
    # ------------------------------------------------------------------
    log("\n--- Deleting junk files ---")
    junk = [
        "lkup_player (version 1).csv",
        "p_2020.csv",
        "playoff_wins_testing.csv",
        "transformed_pre_fanasy_data.csv",
        "draft_players_needing_cleanup.csv",
    ]
    for name in junk:
        _delete(name, dry_run)

    # ------------------------------------------------------------------
    # 6. Summary
    # ------------------------------------------------------------------
    log(f"\n{'='*60}")
    if dry_run:
        log("DRY RUN complete — no files were written or deleted.")
        log("Re-run with --confirm to execute.")
    else:
        log("Migration complete.")
        log(f"Log written to: {LOG_PATH}")

    if not dry_run:
        with open(LOG_PATH, "w", encoding="utf-8") as f:
            f.write("\n".join(log_lines) + "\n")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--dry-run",  action="store_true", help="Preview actions without writing")
    group.add_argument("--confirm",  action="store_true", help="Execute the migration")
    args = parser.parse_args()
    migrate(dry_run=args.dry_run)


if __name__ == "__main__":
    main()
