"""
Cached wrapper around metrics.composite.calculate_composite_ranks.

Takes only scalars/tuples/a dict -- never the source DataFrames themselves
(those come from app_lib.data.load_all_data(), fetched inside this function)
-- so Streamlit's cache-key hashing stays cheap on every widget interaction
instead of re-hashing multi-MB frames each time.
"""

import contextlib
import io

import streamlit as st

from app_lib.data import load_all_data
from metrics.composite import calculate_composite_ranks


@st.cache_data
def get_composite_ranks(
    thru_year: int,
    start_year: int,
    pre_managers: tuple,
    recency_bonus: float,
    recency_window: int,
    use_model_weights: bool,
    manager_controlled_overall_weight: float,
    win_percentages_overall_weight: float,
    points_against_overall_weight: float,
    season_rank_weight: float,
    metrics_dict: dict,
    score_method: str,
    capped_linear_cap: float,
    score_offset: float,
):
    """
    Returns (compiled_final_scores, raw_scores), exactly as
    calculate_composite_ranks does. calculate_composite_ranks prints its
    weights summary and a "Calculating data thru {year}" line per internal
    iteration -- silenced here since none of it reaches the Streamlit UI and
    it would otherwise spam the server logs on every rerun.
    """
    data = load_all_data()
    with contextlib.redirect_stdout(io.StringIO()):
        return calculate_composite_ranks(
            master_df=data["master"],
            rs_df=data["rs_matchups"],
            draft_df=data["draft"],
            faab_df=data["faab"],
            playoffs_df=data["playoffs"],
            thru_year=thru_year,
            overrides=data["overrides"],
            start_year=start_year,
            pre_managers=list(pre_managers),
            recency_bonus=recency_bonus,
            recency_window=recency_window,
            use_model_weights=use_model_weights,
            manager_controlled_overall_weight=manager_controlled_overall_weight,
            win_percentages_overall_weight=win_percentages_overall_weight,
            points_against_overall_weight=points_against_overall_weight,
            season_rank_weight=season_rank_weight,
            Metrics_dict=metrics_dict,
            score_method=score_method,
            capped_linear_cap=capped_linear_cap,
            score_offset=score_offset,
        )
