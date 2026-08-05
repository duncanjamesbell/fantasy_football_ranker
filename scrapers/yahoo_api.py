"""
Yahoo Fantasy API wrapper.

Handles OAuth, league discovery, manager/team data, and standings.
All network calls go through the yahoo_fantasy_api library (not Selenium).
"""

import os
import pandas as pd
from dotenv import load_dotenv
import yahoo_fantasy_api as yfa
from yahoo_oauth import OAuth2

load_dotenv()

OAUTH_FILE = os.getenv("OAUTH_FILE", "oauth2.json")

# Playoff wins lookup table keyed by (num_managers, final_rank, playoff_seed).
# seed <= 2 means the team entered as a top-2 seed.
_PLAYOFF_WINS: dict[tuple, int] = {
    # 10-team league
    (10, 1, "top"): 2, (10, 1, "other"): 3,
    (10, 2, "top"): 1, (10, 2, "other"): 2,
    (10, 3, "top"): 1, (10, 3, "other"): 2,
    (10, 4, "top"): 0, (10, 4, "other"): 1,
    (10, 5, "any"): 1, (10, 6, "any"): 0,
    (10, 7, "any"): 2, (10, 8, "any"): 1,
    (10, 9, "any"): 1, (10, 10, "any"): 0,
    # 8-team league
    (8, 1, "top"): 2, (8, 1, "other"): 3,
    (8, 2, "top"): 1, (8, 2, "other"): 2,
    (8, 3, "top"): 1, (8, 3, "other"): 2,
    (8, 4, "top"): 0, (8, 4, "other"): 1,
    (8, 5, "any"): 1, (8, 6, "any"): 0,
    (8, 7, "any"): 1, (8, 8, "any"): 0,
    # 6-team league
    (6, 1, "any"): 2, (6, 2, "any"): 1,
    (6, 3, "any"): 1, (6, 4, "any"): 0,
    (6, 5, "any"): 1, (6, 6, "any"): 0,
}


def connect(oauth_file: str = OAUTH_FILE) -> yfa.game.Game:
    oauth = OAuth2(None, None, from_file=oauth_file)
    return yfa.game.Game(oauth, "nfl")


def get_leagues(football: yfa.game.Game) -> list[str]:
    return football.league_ids()


# ---------------------------------------------------------------------------
# League settings
# ---------------------------------------------------------------------------

def get_or_update_league_settings(
    football: yfa.game.Game,
    leagues: list[str],
    output_path: str = "league_df_master.csv",
) -> pd.DataFrame:
    """Load cached league settings, append any new leagues, and save."""
    try:
        existing = pd.read_csv(output_path)
        loaded = set(existing.league_key)
    except FileNotFoundError:
        existing = pd.DataFrame()
        loaded = set()

    new_rows = []
    for league in leagues:
        if league not in loaded:
            print(f"Fetching settings for league {league}")
            settings = football.to_league(league).settings()
            row = {k: v for k, v in settings.items() if k != "league_premium_features"}
            new_rows.append(row)

    if new_rows:
        combined = pd.concat([existing, pd.DataFrame(new_rows)], ignore_index=True)
        combined.to_csv(output_path, index=False)
        return combined

    return existing


# ---------------------------------------------------------------------------
# Manager / team data
# ---------------------------------------------------------------------------

def get_or_update_managers(
    football: yfa.game.Game,
    leagues: list[str],
    output_path: str = "managers_df_master.csv",
) -> pd.DataFrame:
    """Load cached manager data, append any new leagues, and save."""
    try:
        existing = pd.read_csv(output_path).drop_duplicates()
        loaded = set(existing.league_key)
    except FileNotFoundError:
        existing = pd.DataFrame()
        loaded = set()

    new_rows = []
    for league in leagues:
        if league not in loaded:
            print(f"Fetching managers for league {league}")
            lg = football.to_league(league)
            season = lg.settings()["season"]
            league_name = lg.settings()["name"]
            for k, team in lg.teams().items():
                manager = team["managers"][0]["manager"]
                new_rows.append({
                    "l_manager_key": k,
                    "league_key": league,
                    "season": season,
                    "league_name": league_name,
                    "team_id": team["team_id"],
                    "team": team["name"],
                    "manager": manager.get("nickname", ""),
                    "felo_score": manager.get("felo_score", ""),
                    "url": team.get("url", ""),
                    "draft_grade": team.get("draft_grade", ""),
                    "number_of_moves": team.get("number_of_moves", ""),
                    "number_of_trades": team.get("number_of_trades", ""),
                    "faab_balance": team.get("faab_balance", ""),
                    "roster_adds": team.get("roster_adds", {}).get("coverage_value", ""),
                })

    if new_rows:
        combined = pd.concat([existing, pd.DataFrame(new_rows)], ignore_index=True)
        combined.to_csv(output_path, index=False)
        return combined

    return existing


# ---------------------------------------------------------------------------
# Standings
# ---------------------------------------------------------------------------

def compute_playoff_wins(num_managers: int, rank: int, seed: int) -> int | str:
    """Public wrapper — used by the Selenium standings fallback in pipeline.py."""
    return _playoff_wins(num_managers, rank, seed)


def _playoff_wins(num_managers: int, rank: int, seed: int) -> int | str:
    seed_bucket = "top" if seed <= 2 else "other"
    result = _PLAYOFF_WINS.get((num_managers, rank, seed_bucket))
    if result is None:
        result = _PLAYOFF_WINS.get((num_managers, rank, "any"), "")
    return result


def get_standings(
    football: yfa.game.Game,
    leagues: list[str],
    manager_df: pd.DataFrame,
) -> pd.DataFrame:
    """Compile standings for all leagues, including calculated playoff_wins."""
    standings_dfs = []

    for league in leagues:
        lg = football.to_league(league)
        raw = pd.DataFrame(lg.standings())

        outcome_expanded = pd.concat(
            [pd.DataFrame([row]) for row in raw.outcome_totals],
            ignore_index=True,
        )
        full = pd.merge(raw, outcome_expanded, left_index=True, right_index=True)

        league_managers = manager_df[manager_df.l_manager_key.isin(full.team_key)]
        moves_map = league_managers.set_index("l_manager_key")["number_of_moves"]
        faab_map = league_managers.set_index("l_manager_key")["faab_balance"]

        full["moves"] = full.team_key.map(moves_map)
        full["faab_balance"] = full.team_key.map(faab_map)
        full["league_key"] = league

        league_id = league.split(".")[-1]
        full["league_id"] = league_id
        full["manager_id"] = full.team_key.str.split(".").str[-1]
        full["manager_key"] = league_id + "." + full["manager_id"]

        num_managers = full.shape[0]
        playoff_wins = []
        for _, row in full.iterrows():
            try:
                wins = _playoff_wins(num_managers, int(row["rank"]), int(row["playoff_seed"]))
            except (ValueError, TypeError):
                wins = ""
            playoff_wins.append(wins)
        full["playoff_wins"] = playoff_wins

        standings_dfs.append(full)

    standings = pd.concat(standings_dfs, ignore_index=True)
    standings.drop_duplicates(subset=["team_key"], inplace=True)
    return standings
