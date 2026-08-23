"""
Presentation glue over calculate_composite_ranks's already-computed output --
ported from composite_ranks.ipynb's metric_scoreboard/explain_manager cells.
Pure formatting (pivot table, row lookup, rank), no scoring logic, so it
lives here rather than in metrics/composite.py.
"""

import pandas as pd

SCORE_COLS = [
    "rs_win_percent_score", "rs_points_score", "rs_points_against_score",
    "p_win_percent_score", "p_points_score", "p_points_against_score",
    "weighted_rank_score", "draft_efficiency_score", "undrafted_savvy_score",
    "faab_efficiency_score", "total_score",
]


def metric_scoreboard(compiled_final_scores: pd.DataFrame, thru_year: int | None = None) -> pd.DataFrame:
    """
    Every manager's per-metric weighted score side by side for one thru-year
    snapshot, sorted by total_score (i.e. the final composite rank).
    """
    thru_year = thru_year or compiled_final_scores.thru.max()
    snap = compiled_final_scores[compiled_final_scores.thru == thru_year][SCORE_COLS].copy()
    snap = snap.sort_values("total_score", ascending=False)
    snap.insert(0, "rank", range(1, len(snap) + 1))
    return snap.round(2)


def explain_manager_view(
    manager: str,
    raw_scores: pd.DataFrame,
    compiled_final_scores: pd.DataFrame,
    thru_year: int | None = None,
) -> dict | None:
    """
    One manager's full metric -> z-score -> final weighted score chain, as
    structured data instead of composite_ranks.ipynb's print()-based version.

    Returns None if the manager has no data thru the given year. Otherwise:
      zscore_pivot    -- metric x season table of normalized_score (the
                          recency-adjusted z-score that actually feeds the
                          weighting).
      score_breakdown -- that manager's final weighted *_score columns for
                          the thru-year snapshot.
      rank, of        -- rank among all managers thru that year.
    """
    thru_year = thru_year or compiled_final_scores.thru.max()

    snap = compiled_final_scores[compiled_final_scores.thru == thru_year]
    row = snap[snap.index == manager]
    if row.empty:
        return None

    m_raw = raw_scores[raw_scores.manager == manager]
    zscore_pivot = m_raw.pivot_table(index="metric", columns="season", values="normalized_score").round(3)
    # Season columns come out as floats (2007.0, 2009.0, ...) from the pivot
    # since some seasons are entirely absent for a given metric (e.g. no
    # draft_efficiency before 2012) -- cast to plain ints for display so
    # headers read "2007" not "2007.0".
    zscore_pivot.columns = [int(c) for c in zscore_pivot.columns]

    score_breakdown = row[SCORE_COLS].T.rename(columns={manager: "score"}).round(3)

    ranked = snap.sort_values("total_score", ascending=False)
    rank = list(ranked.index).index(manager) + 1

    return {
        "zscore_pivot": zscore_pivot,
        "score_breakdown": score_breakdown,
        "rank": rank,
        "of": len(ranked),
    }
