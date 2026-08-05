"""
Draft data compilation.

Extracted from draft_data_compiler.ipynb. Reads per-season draft Excel/CSV
files, standardizes names via PlayerLookup, joins position ranks, and
calculates draft efficiency scores.

Main entry point:
    compile_season(year, lkup, position_ranks_df, matchup_df) → DataFrame
    compile_all(years, lkup, position_ranks_df, matchup_df)   → DataFrame
"""

import os
import pandas as pd
from config import MANAGER_NAME_MAP, POSITION_ALIASES, DRAFT_RESULTS_DIR
from processors.players import PlayerLookup


# ---------------------------------------------------------------------------
# Position rank helpers
# ---------------------------------------------------------------------------

def add_position_rank_ids(position_ranks: pd.DataFrame) -> pd.DataFrame:
    """Extract a player_id column from the player_url column."""
    position_ranks = position_ranks.copy()
    ids = []
    for url in position_ranks["player_url"]:
        parts = str(url).rstrip("/").split("/")
        ids.append(parts[-1])
    position_ranks["player_id"] = ids
    return position_ranks


def compute_actual_position_ranks(position_ranks: pd.DataFrame) -> pd.DataFrame:
    """
    Add 'actual_pos_rank' — a simple sequential rank within each position/season,
    ignoring the Yahoo-assigned rank values (which aren't always reliable).
    """
    position_ranks = position_ranks.copy().sort_values(
        ["season", "position", "position_rank"], ascending=[True, True, True]
    )
    actual_ranks = []
    actual_rank = 0
    prev_pos = None
    for _, row in position_ranks.iterrows():
        if row["position"] != prev_pos:
            actual_rank = 1
        else:
            actual_rank += 1
        actual_ranks.append(actual_rank)
        prev_pos = row["position"]
    position_ranks["actual_pos_rank"] = actual_ranks
    return position_ranks


# ---------------------------------------------------------------------------
# Position counts from a matchup file
# ---------------------------------------------------------------------------

def get_position_counts(matchup_df: pd.DataFrame) -> dict[str, int]:
    """
    Count starting roster slots per position from a single matchup.
    Flex slots (W/R/T, Q/W/R/T) are rolled into RB and QB respectively.
    """
    single_matchup = matchup_df[matchup_df.matchup_url == matchup_df.matchup_url.iloc[0]].copy()
    single_matchup["position"] = single_matchup["position"].str.strip()
    counts = single_matchup["position"].value_counts().to_dict()

    if "Q/W/R/T" in counts:
        counts["QB"] = counts.get("QB", 0) + counts.pop("Q/W/R/T")
    if "W/R/T" in counts:
        counts["RB"] = counts.get("RB", 0) + counts.pop("W/R/T")

    return counts


# ---------------------------------------------------------------------------
# Draft scoring
# ---------------------------------------------------------------------------

def _spend_ranks(season_df: pd.DataFrame) -> pd.Series:
    """Rank each player's draft price within their position group."""
    season_df = season_df.sort_values(["Position", "Price"], ascending=[True, False])
    spend_ranks = []
    prev_pos = prev_price = prev_rank = None
    player_num = 1

    for _, row in season_df.iterrows():
        if row["Position"] != prev_pos:
            player_num = 1
            current_rank = 1
        elif row["Price"] == prev_price:
            current_rank = prev_rank
        else:
            current_rank = player_num

        spend_ranks.append(current_rank)
        player_num += 1
        prev_pos = row["Position"]
        prev_price = row["Price"]
        prev_rank = current_rank

    season_df = season_df.copy()
    season_df["spend_rank"] = spend_ranks
    return season_df


def _position_rank_normalized(season_df: pd.DataFrame) -> pd.Series:
    """Sequential normalized rank within each position group (handles ties)."""
    season_df = season_df.sort_values(["Position", "position_rank"])
    norm_ranks = []
    prev_pos = prev_pos_rank = None
    norm_rank = 1

    for _, row in season_df.iterrows():
        if row["Position"] != prev_pos:
            norm_rank = 1
        elif row["position_rank"] != prev_pos_rank:
            norm_rank += 1
        norm_ranks.append(norm_rank)
        prev_pos = row["Position"]
        prev_pos_rank = row["position_rank"]

    season_df = season_df.copy()
    season_df["position_rank_normalized"] = norm_ranks
    return season_df


def _add_draft_scores(
    season_df: pd.DataFrame, position_counts: dict[str, int]
) -> pd.DataFrame:
    """Add spend_rank, position_rank_normalized, differential, and draft_score."""
    season_df = _spend_ranks(season_df)
    season_df = _position_rank_normalized(season_df)
    season_df["differential"] = season_df["spend_rank"] - season_df["position_rank_normalized"]

    num_managers = season_df["Owner"].nunique()
    bonus_points = []
    for _, row in season_df.iterrows():
        max_bonus = position_counts.get(row["Position"], 1) * num_managers
        bonus = max_bonus - row["position_rank"] + 1
        bonus_points.append(max(0, bonus))
    season_df["top_pos_bonus"] = bonus_points
    season_df["draft_score"] = season_df["differential"] + season_df["top_pos_bonus"]
    return season_df


# ---------------------------------------------------------------------------
# Reading draft source files
# ---------------------------------------------------------------------------

def _read_draft_file(year: int) -> pd.DataFrame:
    csv_path = os.path.join(DRAFT_RESULTS_DIR, f"{year}.csv")
    xlsx_path = os.path.join(DRAFT_RESULTS_DIR, f"{year}.xlsx")
    if os.path.exists(csv_path):
        df = pd.read_csv(csv_path)
    elif os.path.exists(xlsx_path):
        df = pd.read_excel(xlsx_path)
    else:
        raise FileNotFoundError(
            f"No draft file found for {year} in '{DRAFT_RESULTS_DIR}'"
        )

    if "Player Raw" in df.columns and "Player" not in df.columns:
        df = df.rename(columns={"Player Raw": "Player"})

    if "Year" not in df.columns:
        df["Year"] = year
    if "Actual" not in df.columns:
        df["Actual"] = ""

    required = ["Year", "Owner", "Player", "Position", "Price", "Actual"]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Draft file for {year} is missing columns: {missing}")

    return df[required]


def _normalize_draft(df: pd.DataFrame) -> pd.DataFrame:
    """Apply position aliases and price type fixes."""
    df = df.copy()
    df["Position"] = df["Position"].map(lambda p: POSITION_ALIASES.get(p, p))
    int_prices = []
    for price in df["Price"]:
        if isinstance(price, str):
            price = int(price.replace(",", "").strip() or 0)
        int_prices.append(int(price))
    df["Price"] = int_prices
    return df


def _normalize_manager_names(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["owner_normalized"] = df["Owner"].map(
        lambda o: MANAGER_NAME_MAP.get(o, o)
    )
    return df


# ---------------------------------------------------------------------------
# Per-season compilation
# ---------------------------------------------------------------------------

def compile_season(
    year: int,
    lkup: PlayerLookup,
    position_ranks: pd.DataFrame,
    matchup_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Compile and score the draft data for a single season.

    Args:
        year:            Season year (int).
        lkup:            Loaded PlayerLookup.
        position_ranks:  Full position_ranks_thru_YEAR.csv as a DataFrame.
        matchup_df:      The year's pre_matchups.csv (used to get position counts).

    Returns:
        DataFrame with columns: Year, Owner, Player, Position, Price, Actual,
        standard_player, standard_player_conc, player_id, spend_rank,
        position_rank, position_rank_normalized, differential, top_pos_bonus,
        draft_score, owner_normalized.
    """
    raw = _read_draft_file(year)
    df = _normalize_draft(raw)

    # Resolve player names
    df = lkup.apply_to_df(df, name_col="Player", pos_col="Position")

    # Merge position ranks
    pos_ranks_year = position_ranks[position_ranks["season"] == year].copy()
    pos_rank_map = (
        pos_ranks_year.set_index("player_id")["actual_pos_rank"].to_dict()
    )

    position_rank_values = []
    for _, row in df.iterrows():
        if row["Actual"] != "":
            position_rank_values.append(row["Actual"])
        else:
            rank = pos_rank_map.get(str(row["player_id"]), None)
            if rank is None:
                print(
                    f"  WARNING: no position rank for {row['Player']!r} "
                    f"({row['Position']}) in {year} — using 999"
                )
                rank = 999
            position_rank_values.append(rank)
    df["position_rank"] = position_rank_values

    position_counts = get_position_counts(matchup_df)
    df = _add_draft_scores(df, position_counts)
    df = _normalize_manager_names(df)
    return df


# ---------------------------------------------------------------------------
# Multi-season compilation
# ---------------------------------------------------------------------------

def compile_all(
    years: list[int],
    lkup: PlayerLookup,
    position_ranks: pd.DataFrame,
    matchup_dfs: dict[int, pd.DataFrame],
) -> pd.DataFrame:
    """
    Compile draft data for multiple seasons.

    Args:
        years:         List of season years to compile.
        lkup:          Loaded PlayerLookup.
        position_ranks: Full position_ranks DataFrame (all years).
        matchup_dfs:   Dict mapping year → matchup DataFrame.

    Returns:
        Concatenated DataFrame for all seasons.
    """
    dfs = []
    for year in years:
        print(f"Compiling draft data for {year}...")
        try:
            df = compile_season(year, lkup, position_ranks, matchup_dfs[year])
            dfs.append(df)
        except FileNotFoundError as e:
            print(f"  Skipping {year}: {e}")
    return pd.concat(dfs, ignore_index=True)


# ---------------------------------------------------------------------------
# is_drafted enrichment for regular season data
# ---------------------------------------------------------------------------

def add_is_drafted(
    rs_df: pd.DataFrame,
    draft_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Add an 'is_drafted' flag to the regular-season matchup DataFrame.

    A player appearance is considered drafted when (season, manager_name, player_id)
    exists in the draft data.
    """
    rs_df = rs_df.copy()
    draft_df = draft_df.copy()

    draft_df["Year"] = draft_df["Year"].astype(str)
    draft_df["conc"] = draft_df["Year"] + draft_df["owner_normalized"] + draft_df["player_id"].astype(str)
    draft_concs = set(draft_df["conc"].dropna())

    is_drafted = []
    for _, row in rs_df.iterrows():
        conc = str(row.get("season", "")) + str(row.get("manager_name", "")) + str(row.get("player_id", ""))
        is_drafted.append(1 if conc in draft_concs else 0)

    rs_df["is_drafted"] = is_drafted
    return rs_df
