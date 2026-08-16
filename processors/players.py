"""
Player name reconciliation.

The core annual pain point: draft sheets and scraped data use dozens of name
variants (abbreviations, misspellings, special characters) while position_ranks
and player IDs need a single canonical form.

PlayerLookup wraps the two reference files and adds fuzzy matching so that
unrecognized names are surfaced immediately — with ranked suggestions — rather
than silently becoming blanks that only surface later as wrong composite scores.

Reference files:
  lkup_player.csv  — Name + Position → Standard Name  (variant spellings)
  names_dict.csv   — player_conc (StandardName+Position) → player_id

Usage:
    lkup = PlayerLookup()
    standard = lkup.standardize("Aaron Rogers", "QB")   # → "Aaron Rodgers"
    pid = lkup.get_player_id("Aaron Rodgers", "QB")     # → "7200"

    unmatched = lkup.find_unmatched([("Derick Henry", "RB"), ("Josh Allen", "QB")])
    lkup.batch_review(unmatched)   # interactive CLI
"""

import difflib
import os
import re
import pandas as pd
from config import LKUP_PLAYER_PATH, NAMES_DICT_PATH


# ---------------------------------------------------------------------------
# Name normalization helpers
# ---------------------------------------------------------------------------

def _normalize(name: str) -> str:
    """Lower-case, strip punctuation, collapse whitespace — for fuzzy comparison only."""
    name = name.lower()
    name = re.sub(r"[^a-z0-9 ]", " ", name)
    return re.sub(r"\s+", " ", name).strip()


def _read_csv(path: str) -> pd.DataFrame:
    """pd.read_csv with pandas' default NA-sentinel list disabled.

    lkup_player.csv uses the literal string "#N/A" as a manual placeholder in
    an unused column; pandas treats that as a null by default and rewrites it
    as blank on every save, silently corrupting the file over repeated saves.
    """
    return pd.read_csv(path, keep_default_na=False, na_values=[])


# ---------------------------------------------------------------------------
# PlayerLookup
# ---------------------------------------------------------------------------

class PlayerLookup:
    """
    Wraps lkup_player.csv and names_dict.csv with fuzzy-match augmentation.

    All mutations are immediately written back to disk so that partial runs
    leave the reference files in a consistent state.
    """

    def __init__(
        self,
        lkup_path: str = LKUP_PLAYER_PATH,
        names_dict_path: str = NAMES_DICT_PATH,
    ) -> None:
        self.lkup_path = lkup_path
        self.names_dict_path = names_dict_path
        self._load()

    # ------------------------------------------------------------------
    # Load / reload
    # ------------------------------------------------------------------

    def _load(self) -> None:
        lkup_df = _read_csv(self.lkup_path)
        # Key: Name + Position  →  Standard Name
        self._lkup: dict[str, str] = {}
        for _, row in lkup_df.iterrows():
            key = str(row["Name"]) + str(row["Position"])
            self._lkup[key] = str(row["Standard Name"])

        # Also track normalized form for fuzzy matching
        self._known_standards: list[tuple[str, str, str]] = []  # (standard_name, position, player_id)
        names_df = _read_csv(self.names_dict_path)
        self._names_dict: dict[str, str] = {}
        for _, row in names_df.iterrows():
            self._names_dict[str(row["player_conc"])] = str(row["player_id"])
            pname = str(row.get("player_name", ""))
            pos = str(row.get("position", ""))
            pid = str(row["player_id"])
            if pname and pos:
                self._known_standards.append((pname, pos, pid))

    def reload(self) -> None:
        self._load()

    # ------------------------------------------------------------------
    # Core lookups
    # ------------------------------------------------------------------

    def standardize(self, name: str, position: str) -> str:
        """Return the canonical name for a draft/variant name, or the name itself."""
        key = str(name) + str(position)
        return self._lkup.get(key, name)

    def get_player_id(self, standard_name: str, position: str) -> str:
        """Return Yahoo player_id for a canonical name+position pair."""
        key = str(standard_name) + str(position)
        return self._names_dict.get(key, "")

    def lookup(self, name: str, position: str) -> tuple[str, str]:
        """Convenience: return (standard_name, player_id) in one call."""
        standard = self.standardize(name, position)
        pid = self.get_player_id(standard, position)
        return standard, pid

    def is_known(self, name: str, position: str) -> bool:
        return (str(name) + str(position)) in self._lkup

    # ------------------------------------------------------------------
    # Finding unmatched players
    # ------------------------------------------------------------------

    def find_unmatched(
        self, players: list[tuple[str, str]]
    ) -> list[tuple[str, str]]:
        """
        Return (name, position) pairs that have no entry in lkup_player.

        Call this after loading a new season's draft file or FAAB data.
        """
        return [
            (name, pos)
            for name, pos in players
            if not self.is_known(name, pos)
        ]

    def find_unmatched_from_df(
        self, df: pd.DataFrame, name_col: str = "Player", pos_col: str = "Position"
    ) -> list[tuple[str, str]]:
        """Convenience wrapper that accepts a DataFrame."""
        pairs = list(df[[name_col, pos_col]].drop_duplicates().itertuples(index=False, name=None))
        return self.find_unmatched(pairs)

    # ------------------------------------------------------------------
    # Fuzzy suggestions
    # ------------------------------------------------------------------

    def suggest_matches(
        self,
        name: str,
        position: str,
        n: int = 5,
        threshold: float = 0.5,
    ) -> list[tuple[str, float, str]]:
        """
        Return up to n fuzzy candidates for an unrecognized (name, position).

        Returns list of (candidate_name, similarity_score, player_id), sorted
        descending by score. Only candidates for the same position are considered.

        Uses difflib.SequenceMatcher (no external deps required). Install
        rapidfuzz and swap in WRatio for better results on nicknames / initials.
        """
        norm_query = _normalize(name)
        candidates = [
            (std_name, pos, pid)
            for std_name, pos, pid in self._known_standards
            if pos == position
        ]
        # Also pull from lkup Standard Name column to catch existing variants
        lkup_df = _read_csv(self.lkup_path)
        for _, row in lkup_df[lkup_df["Position"] == position].iterrows():
            std = str(row["Standard Name"])
            pid = str(row.get("player_id", ""))
            if not any(c[0] == std for c in candidates):
                candidates.append((std, position, pid))

        scored = []
        for std_name, pos, pid in candidates:
            score = difflib.SequenceMatcher(
                None, norm_query, _normalize(std_name)
            ).ratio()
            if score >= threshold:
                scored.append((std_name, round(score, 3), pid))

        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:n]

    # ------------------------------------------------------------------
    # Adding new mappings
    # ------------------------------------------------------------------

    def add_mapping(
        self,
        name: str,
        position: str,
        standard_name: str,
        player_id: str,
        save: bool = True,
    ) -> None:
        """
        Record that `name` + `position` maps to `standard_name` and `player_id`.

        Updates in-memory state and optionally writes both CSV files.
        Safe to call if the mapping already exists (no-op).
        """
        lkup_key = str(name) + str(position)
        names_key = str(standard_name) + str(position)

        if lkup_key not in self._lkup:
            self._lkup[lkup_key] = standard_name

        if names_key not in self._names_dict and player_id:
            self._names_dict[names_key] = str(player_id)
            self._known_standards.append((standard_name, position, str(player_id)))

        if save:
            self._save_lkup_entry(name, position, standard_name, player_id)
            self._save_names_dict_entry(standard_name, position, player_id)

    def _save_lkup_entry(
        self, name: str, position: str, standard_name: str, player_id: str
    ) -> None:
        lkup_df = _read_csv(self.lkup_path)
        conc = standard_name + position
        new_row = {
            "Name": name,
            "Position": position,
            "Standard Name": standard_name,
            "conc": conc,
            "player_id": player_id,
        }
        # Fill any columns present in existing file but not in new_row
        for col in lkup_df.columns:
            if col not in new_row:
                new_row[col] = ""
        mask = (lkup_df["Name"] == name) & (lkup_df["Position"] == position)
        if mask.any():
            return  # already present
        lkup_df = pd.concat([lkup_df, pd.DataFrame([new_row])], ignore_index=True)
        lkup_df.to_csv(self.lkup_path, index=False)

    def _save_names_dict_entry(
        self, standard_name: str, position: str, player_id: str
    ) -> None:
        if not player_id:
            return
        names_df = _read_csv(self.names_dict_path)
        conc = standard_name + position
        if conc in names_df["player_conc"].values:
            return  # already present
        new_row = {
            "player_conc": conc,
            "player_name": standard_name,
            "position": position,
            "player_id": player_id,
        }
        names_df = pd.concat([names_df, pd.DataFrame([new_row])], ignore_index=True)
        names_df.to_csv(self.names_dict_path, index=False)

    # ------------------------------------------------------------------
    # Interactive batch review
    # ------------------------------------------------------------------

    def batch_review(
        self,
        unmatched: list[tuple[str, str]],
        n_suggestions: int = 5,
    ) -> dict[tuple[str, str], tuple[str, str]]:
        """
        Interactive CLI to review unmatched (name, position) pairs.

        For each unmatched player:
          - Shows fuzzy match candidates with scores
          - User enters a number to pick a suggestion, or types a custom name
          - Optionally provides the Yahoo player_id
          - Mapping is immediately saved to both CSV files

        Returns a dict mapping (name, position) → (standard_name, player_id)
        for all confirmed entries.

        Pass `--skip` or hit Enter to skip a player (leaves it unresolved).
        """
        if not unmatched:
            print("No unmatched players to review.")
            return {}

        confirmed: dict[tuple[str, str], tuple[str, str]] = {}
        total = len(unmatched)

        print(f"\n{'='*60}")
        print(f"Player Name Reconciliation — {total} unmatched player(s)")
        print(f"{'='*60}\n")

        for i, (name, position) in enumerate(unmatched, 1):
            print(f"[{i}/{total}]  {name!r}  ({position})")
            suggestions = self.suggest_matches(name, position, n=n_suggestions)

            if suggestions:
                print("  Suggestions (score, name, player_id):")
                for idx, (std_name, score, pid) in enumerate(suggestions, 1):
                    pid_str = f"id={pid}" if pid else "no id"
                    print(f"    {idx}. [{score:.0%}] {std_name}  ({pid_str})")
            else:
                print("  No close matches found.")

            print("  Enter: number to pick suggestion | custom name | 's' to skip")
            raw = input("  > ").strip()

            if raw.lower() in ("s", "skip", ""):
                print("  Skipped.\n")
                continue

            # User picked a numbered suggestion
            if raw.isdigit() and 1 <= int(raw) <= len(suggestions):
                std_name, _, pid = suggestions[int(raw) - 1]
            else:
                std_name = raw
                pid = input(f"  Player ID for '{std_name}' (Enter to leave blank): ").strip()

            # Confirm and save
            self.add_mapping(name, position, std_name, pid)
            confirmed[(name, position)] = (std_name, pid)
            print(f"  Saved: {name!r} → {std_name!r}  (id={pid or 'none'})\n")

        resolved = len(confirmed)
        skipped = total - resolved
        print(f"\nDone. {resolved} resolved, {skipped} skipped.")
        if skipped:
            print("Run again or edit lkup_player.csv manually for skipped entries.")
        return confirmed

    # ------------------------------------------------------------------
    # Bulk apply to a DataFrame
    # ------------------------------------------------------------------

    def apply_to_df(
        self,
        df: pd.DataFrame,
        name_col: str = "Player",
        pos_col: str = "Position",
    ) -> pd.DataFrame:
        """
        Add 'standard_player', 'standard_player_conc', and 'player_id' columns.

        Call after batch_review to get a fully resolved DataFrame.
        """
        df = df.copy()
        std_names, concs, pids = [], [], []
        for _, row in df.iterrows():
            std = self.standardize(str(row[name_col]), str(row[pos_col]))
            pid = self.get_player_id(std, str(row[pos_col]))
            std_names.append(std)
            concs.append(std + str(row[pos_col]))
            pids.append(pid)
        df["standard_player"] = std_names
        df["standard_player_conc"] = concs
        df["player_id"] = pids
        return df
