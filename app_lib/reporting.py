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

# Human-readable labels for every metric, covering both naming schemes in
# play: SCORE_COLS (metric_scoreboard, score_breakdown, chart data columns)
# and raw_scores_df's own 'metric' column (zscore_pivot, manager trend
# charts) -- these were originally dev-time variable names (e.g. "rs_points",
# "p_points_against") rather than labels meant for end users. Single shared
# source of truth so every display surface (tables, chart titles/legends,
# sidebar sliders) uses the same wording.
METRIC_DISPLAY_NAMES = {
    "rs_win_percent_score":     "Regular Season Win %",
    "avg_rs_win_percent":       "Regular Season Win %",
    "rs_win_percentage":        "Regular Season Win %",
    "rs_points_score":          "Regular Season Points",
    "rs_points":                "Regular Season Points",
    "rs_points_against_score":  "Regular Season Points Against",
    "rs_points_against":        "Regular Season Points Against",
    "p_win_percent_score":      "Playoff Win %",
    "playoff_win_percentage":   "Playoff Win %",
    "p_points_score":           "Playoff Points",
    "playoff_points":           "Playoff Points",
    "p_points_against_score":   "Playoff Points Against",
    "playoff_points_against":   "Playoff Points Against",
    "weighted_rank_score":      "Season Rank",
    "season_rank":              "Season Rank",
    "draft_efficiency_score":   "Draft Efficiency",
    "draft_efficiency":         "Draft Efficiency",
    "undrafted_savvy_score":    "Undrafted Savvy",
    "undrafted_savvy":          "Undrafted Savvy",
    "faab_efficiency_score":    "FAAB Efficiency",
    "faab_efficiency":          "FAAB Efficiency",
    "total_score":              "Total Score",
}

# raw_scores_df's own 'metric' column values, in the same metric order as
# SCORE_COLS (minus total_score, which has no raw per-season z-score of its
# own) -- a stable order to iterate metric-trend charts in.
RAW_METRIC_COLS = [
    "avg_rs_win_percent", "rs_points", "rs_points_against",
    "playoff_win_percentage", "playoff_points", "playoff_points_against",
    "season_rank", "draft_efficiency", "undrafted_savvy", "faab_efficiency",
]

# Same red/green pair as the metric-trend chart markers (app_lib/plots.py),
# so the "hurting vs. helping" signal reads consistently across charts and
# tables.
_POSITIVE_FONT_COLOR = "#1a9850"
_NEGATIVE_FONT_COLOR = "#d73027"


def _signed_font_color(val) -> str:
    if pd.isna(val) or val == 0:
        return ""
    return f"color: {_POSITIVE_FONT_COLOR}" if val > 0 else f"color: {_NEGATIVE_FONT_COLOR}"


def style_signed(
    df: pd.DataFrame,
    subset=None,
    force_black_cols=None,
    force_black_rows=None,
    force_black_rows_cols=None,
) -> "pd.io.formats.style.Styler":
    """Green font for positive values, red for negative, default (blank) font
    color at exactly 0 -- makes it obvious at a glance which values are
    helping vs. hurting a manager's score. Also rounds the displayed value to
    two decimal places -- a Styler ignores a DataFrame's own .round() and
    shows full float precision unless told otherwise. `subset` restricts both
    the coloring and the number formatting to specific columns (e.g. to
    exclude a non-score 'rank' column). `force_black_cols`/`force_black_rows`
    override the sign-based color back to black for specific columns/index
    labels (e.g. 'Total Score', which -- unlike a per-metric score -- isn't
    itself a signal of something helping or hurting). `force_black_rows_cols`
    narrows `force_black_rows` to only specific columns within those rows
    (default: every column) -- e.g. a comparison table's difference column
    should stay sign-colored even on the 'Total Score' row, while the two
    managers' own raw Total Score values there go black."""
    styler = (
        df.style
        .applymap(_signed_font_color, subset=subset)
        .format("{:.2f}", subset=subset, na_rep="")
    )
    if force_black_cols:
        styler = styler.applymap(lambda v: "color: black", subset=force_black_cols)
    if force_black_rows:
        cols = force_black_rows_cols if force_black_rows_cols is not None else slice(None)
        styler = styler.applymap(lambda v: "color: black", subset=pd.IndexSlice[force_black_rows, cols])
    return styler


def metric_scoreboard(compiled_final_scores: pd.DataFrame, thru_year: int | None = None) -> pd.DataFrame:
    """
    Every manager's per-metric weighted score side by side for one thru-year
    snapshot, sorted by total_score (i.e. the final composite rank).
    """
    thru_year = thru_year or compiled_final_scores.thru.max()
    snap = compiled_final_scores[compiled_final_scores.thru == thru_year][SCORE_COLS].copy()
    snap = snap.sort_values("total_score", ascending=False)
    snap.insert(0, "rank", range(1, len(snap) + 1))
    return snap.round(2).rename(columns=METRIC_DISPLAY_NAMES)


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

    score_breakdown = (
        row[SCORE_COLS].T
        .rename(columns={manager: "score"}, index=METRIC_DISPLAY_NAMES)
        .round(3)
    )

    ranked = snap.sort_values("total_score", ascending=False)
    rank = list(ranked.index).index(manager) + 1

    return {
        "zscore_pivot": zscore_pivot,
        "score_breakdown": score_breakdown,
        "rank": rank,
        "of": len(ranked),
    }


def compare_managers_view(
    manager_a: str,
    manager_b: str,
    compiled_final_scores: pd.DataFrame,
    thru_year: int | None = None,
) -> dict | None:
    """
    Two managers' final weighted scores side by side, for the "why is X
    higher/lower than me" question -- a diff column, with per-metric rows
    sorted by the size of the gap (biggest driver of the difference first)
    and 'Total Score' always pinned last as the summary row, matching
    metric_scoreboard/explain_manager_view's convention of total_score last.

    Returns None if either manager has no data thru the given year.
    """
    thru_year = thru_year or compiled_final_scores.thru.max()

    snap = compiled_final_scores[compiled_final_scores.thru == thru_year]
    row_a = snap[snap.index == manager_a]
    row_b = snap[snap.index == manager_b]
    if row_a.empty or row_b.empty:
        return None

    comparison = pd.DataFrame({
        manager_a: row_a[SCORE_COLS].iloc[0],
        manager_b: row_b[SCORE_COLS].iloc[0],
    })
    comparison.index = [METRIC_DISPLAY_NAMES.get(k, k) for k in comparison.index]
    diff_col = f"{manager_a} minus {manager_b}"
    comparison[diff_col] = comparison[manager_a] - comparison[manager_b]

    is_total = comparison.index == "Total Score"
    per_metric = comparison[~is_total]
    per_metric = per_metric.reindex(per_metric[diff_col].abs().sort_values(ascending=False).index)
    comparison = pd.concat([per_metric, comparison[is_total]]).round(3)

    ranked = snap.sort_values("total_score", ascending=False)
    rank_a = list(ranked.index).index(manager_a) + 1
    rank_b = list(ranked.index).index(manager_b) + 1

    return {
        "comparison": comparison,
        "diff_col": diff_col,
        "rank_a": rank_a,
        "rank_b": rank_b,
        "of": len(ranked),
    }
