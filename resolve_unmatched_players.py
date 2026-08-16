"""
Suggest standard_name/player_id pairs for players skipped in the `players`
pipeline step, so you're not looking each one up on Yahoo by hand.

Two kinds of unmatched names come out of the `players` step:
  - Team defenses (e.g. "Commanders") are usually just an unrecognized alias
    for a team that already has a player_id in names_dict.csv (under its
    city name). These are resolved via DEF_NICKNAME_TO_STANDARD below.
  - Real players (mostly rookies) are looked up by exact name+position match
    against data/processed/position_ranks_thru_{YEAR}.csv, which the
    `positions` step already scraped -- the Yahoo player_id is embedded in
    its player_url column.

By default, every confidently-resolved match (a standard_name AND a
player_id, no ambiguity) is written straight to lkup_player.csv and
names_dict.csv via PlayerLookup.add_mapping -- the same write path the
interactive `players` step review uses. Both files are tracked in git, so
`git diff` / `git checkout -- <file>` undoes a bad run. Anything not
confidently resolved is left alone for the interactive review to handle.

Pass --dry-run to only print/save suggestions without writing anything.

Usage:
    py resolve_unmatched_players.py --year 2025
    py resolve_unmatched_players.py --year 2025 --dry-run
"""

import argparse
import os
import pandas as pd

import config
from processors.players import PlayerLookup
from processors.draft import add_position_rank_ids

# NFL team nickname -> the exact Standard Name already used in names_dict.csv
# for that team's DEF entry. Update on relocations/rebrands (e.g. Commanders).
DEF_NICKNAME_TO_STANDARD = {
    "cardinals": "Arizona",
    "falcons": "Atlanta",
    "ravens": "Baltimore",
    "bills": "Buffalo",
    "panthers": "Carolina",
    "bears": "Chicago",
    "bengals": "Cincinnati",
    "browns": "Cleveland",
    "cowboys": "Dallas",
    "broncos": "Denver",
    "lions": "Detroit",
    "packers": "Green Bay",
    "texans": "Houston",
    "colts": "Indianapolis",
    "jaguars": "Jacksonville",
    "chiefs": "Kansas City",
    "chargers": "LA Chargers",
    "rams": "LA Rams",
    "raiders": "Las Vegas",
    "dolphins": "Miami",
    "vikings": "Minnesota",
    "patriots": "New England",
    "saints": "New Orleans",
    "giants": "New York",
    "jets": "New York (NYJ)",
    "commanders": "Washington",
    "eagles": "Philadelphia",
    "steelers": "Pittsburgh",
    "49ers": "San Francisco",
    "niners": "San Francisco",
    "seahawks": "Seattle",
    "buccaneers": "Tampa Bay",
    "bucs": "Tampa Bay",
    "titans": "Tennessee",
}


def _collect_unmatched(year: int, lkup: PlayerLookup) -> list[tuple[str, str, str]]:
    """Reproduce step_players' candidate collection, tagged with source file(s)."""
    tagged: list[tuple[str, str, str]] = []  # (name, position, source)

    draft_csv = os.path.join(config.DRAFT_RESULTS_DIR, f"{year}.csv")
    draft_xlsx = os.path.join(config.DRAFT_RESULTS_DIR, f"{year}.xlsx")
    if os.path.exists(draft_csv):
        draft_df = pd.read_csv(draft_csv)
    elif os.path.exists(draft_xlsx):
        draft_df = pd.read_excel(draft_xlsx)
    else:
        draft_df = None

    if draft_df is not None:
        if "Player Raw" in draft_df.columns and "Player" not in draft_df.columns:
            draft_df = draft_df.rename(columns={"Player Raw": "Player"})
        for name, pos in draft_df[["Player", "Position"]].drop_duplicates().itertuples(index=False, name=None):
            tagged.append((name, pos, "draft"))

    faab_path = config.year_faab_path(year)
    if os.path.exists(faab_path):
        faab_df = pd.read_csv(faab_path)
        if "player_name" in faab_df.columns and "position" in faab_df.columns:
            for name, pos in faab_df[["player_name", "position"]].drop_duplicates().itertuples(index=False, name=None):
                tagged.append((name, pos, "faab"))

    # Normalize position aliases and merge sources for names seen in both files.
    merged: dict[tuple[str, str], set[str]] = {}
    for name, pos, source in tagged:
        pos = config.POSITION_ALIASES.get(pos, pos)
        merged.setdefault((name, pos), set()).add(source)

    return sorted(
        (name, pos, "+".join(sorted(sources)))
        for (name, pos), sources in merged.items()
        if not lkup.is_known(name, pos)
    )


def _resolve_def(name: str, lkup: PlayerLookup) -> tuple[str, str, str]:
    """Try to resolve a team-defense alias to its existing Standard Name/ID."""
    key = name.lower().strip()
    for nickname, standard_name in DEF_NICKNAME_TO_STANDARD.items():
        if nickname in key:
            player_id = lkup.get_player_id(standard_name, "DEF")
            note = "existing DEF alias" if player_id else "existing DEF alias, but no id in names_dict.csv"
            return standard_name, player_id, note
    return "", "", "no nickname match -- resolve manually"


def _resolve_player(name: str, position: str, position_ranks: pd.DataFrame) -> tuple[str, str, str]:
    """Try to find name+position in this year's scraped position_ranks (has player_url)."""
    match = position_ranks[
        (position_ranks["player_name"].str.lower() == name.lower())
        & (position_ranks["position"] == position)
    ]
    if len(match) == 1:
        row = match.iloc[0]
        return row["player_name"], row["player_id"], "found in position_ranks"
    if len(match) > 1:
        row = match.iloc[0]
        return row["player_name"], row["player_id"], f"WARNING: {len(match)} matches, using first"
    return "", "", "NOT FOUND -- check spelling or look up manually on Yahoo"


def _is_confident(standard_name: str, player_id: str, note: str) -> bool:
    """A match is safe to auto-apply only if it's unambiguous and complete."""
    return bool(standard_name) and bool(player_id) and "WARNING" not in note


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Resolve and auto-apply standard_name/player_id pairs for players skipped in the players step."
    )
    parser.add_argument("--year", type=int, required=True)
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Only print/save suggestions -- don't write to lkup_player.csv / names_dict.csv.",
    )
    args = parser.parse_args()
    year = args.year

    lkup = PlayerLookup()
    unmatched = _collect_unmatched(year, lkup)
    if not unmatched:
        print(f"No unmatched players for {year}.")
        return

    pr_path = config.position_ranks_path(year)
    if not os.path.exists(pr_path):
        print(f"ERROR: {pr_path} not found -- run the 'positions' step first.")
        return
    position_ranks = add_position_rank_ids(pd.read_csv(pr_path))
    position_ranks = position_ranks[position_ranks["season"] == year]

    rows = []
    for name, position, source in unmatched:
        if position == "DEF":
            standard_name, player_id, note = _resolve_def(name, lkup)
        else:
            standard_name, player_id, note = _resolve_player(name, position, position_ranks)

        confident = _is_confident(standard_name, player_id, note)
        if confident and not args.dry_run:
            lkup.add_mapping(name, position, standard_name, player_id)
            note = f"APPLIED -- {note}"

        rows.append({
            "name": name,
            "position": position,
            "source": source,
            "suggested_standard_name": standard_name,
            "suggested_player_id": player_id,
            "confident": confident,
            "note": note,
        })

    out_df = pd.DataFrame(rows)
    out_path = f"data/raw/{year}_unmatched_resolutions.csv"
    out_df.to_csv(out_path, index=False)

    print(f"\n{'Name':30} {'Pos':5} {'Source':10} {'Standard Name':16} {'Player ID':10} Note")
    print("-" * 110)
    for _, r in out_df.iterrows():
        print(
            f"{r['name']:30} {r['position']:5} {r['source']:10} "
            f"{r['suggested_standard_name']:16} {str(r['suggested_player_id']):10} {r['note']}"
        )

    n_confident = out_df["confident"].sum()
    n_review = len(out_df) - n_confident
    print(f"\n{n_confident}/{len(out_df)} confidently resolved, {n_review} need manual review. Saved -> {out_path}")
    if args.dry_run:
        print("DRY RUN -- nothing written. Re-run without --dry-run to apply the confident matches.")
    else:
        print(f"{n_confident} mapping(s) written to lkup_player.csv / names_dict.csv.")
    print(f"Run the interactive review for anything left: py pipeline.py --year {year} --steps players")


if __name__ == "__main__":
    main()
