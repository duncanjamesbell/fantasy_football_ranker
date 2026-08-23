"""
PRE Fantasy Football Composite Ranks -- Streamlit app.

Presentation layer only. All scoring computation lives in
metrics/composite.py (untouched by this app) and is reused via
app_lib/compute.py; composite_ranks.ipynb remains the primary tool for
iterating on the metric calculations themselves.
"""

import streamlit as st

from app_lib.auth import require_passphrase
from app_lib.compute import get_composite_ranks
from app_lib.data import load_all_data
from app_lib.methodology import full_methodology_markdown
from app_lib.plots import build_last_season_by_manager, build_manager_metric_trend, build_ranking_bar, build_trend, color_map_for
from app_lib.reporting import SCORE_COLS, explain_manager_view, metric_scoreboard
from config import SEASONS

st.set_page_config(page_title="PRE Composite Ranks", layout="wide")
require_passphrase()

# Matches composite_ranks.ipynb's current pre_managers list: the 10 core
# 2014-era league members plus the 2025 additions (Mark+David, Waidmann).
CORE_MEMBERS = (
    "Benjamin", "Bryan", "David Casstevens", "Duncan", "Kevin", "Krista",
    "Luke", "Mark", "Patrick", "Scott Gunter", "Mark+David", "Waidmann",
)

# Defaults matching the notebook's fallback Metrics_dict (sums to 100).
DEFAULT_METRIC_WEIGHTS = {
    "rs_points": 38,
    "season_rank": 15,
    "rs_points_against": 8,
    "playoff_points": 8,
    "draft_efficiency": 6,
    "undrafted_savvy": 6,
    "playoff_win_percentage": 6,
    "rs_win_percentage": 5,
    "playoff_points_against": 5,
    "faab_efficiency": 3,
}
METRIC_LABELS = {
    "rs_points": "RS Points",
    "season_rank": "Season Rank",
    "rs_points_against": "RS Points Against",
    "playoff_points": "Playoff Points",
    "draft_efficiency": "Draft Efficiency",
    "undrafted_savvy": "Undrafted Savvy",
    "playoff_win_percentage": "Playoff Win %",
    "rs_win_percentage": "RS Win %",
    "playoff_points_against": "Playoff Points Against",
    "faab_efficiency": "FAAB Efficiency",
}

LATEST_YEAR = max(SEASONS)

st.sidebar.header("Controls")

with st.sidebar.expander("Advanced"):
    start_year = st.number_input("Start year", min_value=2007, max_value=LATEST_YEAR, value=2015)
    recency_bonus = st.slider("Recency bonus", 0.0, 1.0, 0.25, step=0.01)
    recency_window = st.slider("Recency window (years)", 1, 10, 4)

    st.subheader("Scoring method")
    score_method_label = st.radio(
        "Method", ["Capped linear (symmetric)", "Cascade (original)"],
        help=(
            "Capped linear (default): bounded [-weight, weight], symmetric around "
            "the population mean -- average scores 0, above/below average is "
            "rewarded/penalized symmetrically. Cascade: bounded [0, weight], "
            "asymmetric -- rank #1 in a metric always claims the full weight "
            "regardless of margin, worst performer keeps a floor well above zero."
        ),
    )
    score_method = "capped_linear" if score_method_label.startswith("Capped") else "cascade"

    capped_linear_cap = 2.0
    score_offset = 0.0
    if score_method == "capped_linear":
        capped_linear_cap = st.slider("Z-score cap (standard deviations)", 0.5, 4.0, 2.0, step=0.1)
        score_offset = st.slider("Score offset", 0, 100, 50, step=5, help="Added to total_score only, to keep totals positive.")

thru_year = st.sidebar.slider("Thru year", min_value=start_year, max_value=LATEST_YEAR, value=LATEST_YEAR)

st.sidebar.subheader("Metric weights")
weight_mode = st.sidebar.radio("Weight mode", ["Manual per-metric weights", "Model-derived buckets"])
use_model_weights = weight_mode == "Model-derived buckets"

metric_weights = dict(DEFAULT_METRIC_WEIGHTS)
manager_controlled_overall_weight = 0.75
win_percentages_overall_weight = 0.12
points_against_overall_weight = 0.13

if use_model_weights:
    season_rank_weight = st.sidebar.slider("Season rank weight", 0, 50, 15)
    manager_controlled_overall_weight = st.sidebar.slider("Manager-controlled bucket", 0.0, 1.0, 0.75, step=0.01)
    win_percentages_overall_weight = st.sidebar.slider("Win-percentage bucket", 0.0, 1.0, 0.12, step=0.01)
    points_against_overall_weight = st.sidebar.slider("Points-against bucket", 0.0, 1.0, 0.13, step=0.01)
    st.sidebar.caption(
        "Bucket weights are proportions (not required to sum to 1) of the "
        f"weight remaining after season rank ({100 - season_rank_weight} pts); "
        "each metric's individual weight within a bucket is model-derived."
    )
else:
    st.sidebar.caption("Recommended to sum to 100, not enforced.")
    for metric, default in DEFAULT_METRIC_WEIGHTS.items():
        metric_weights[metric] = st.sidebar.slider(
            METRIC_LABELS[metric], min_value=0, max_value=50, value=default, key=f"weight_{metric}",
        )
    season_rank_weight = metric_weights["season_rank"]

    weight_total = sum(metric_weights.values())
    st.sidebar.metric("Weight total", weight_total, delta=weight_total - 100)
    if weight_total != 100:
        st.sidebar.warning(f"Weights sum to {weight_total}, not 100 -- scores will still compute, just not on a clean 0-100 scale.")

compiled_final_scores, raw_scores = get_composite_ranks(
    thru_year=thru_year,
    start_year=start_year,
    pre_managers=CORE_MEMBERS,
    recency_bonus=recency_bonus,
    recency_window=recency_window,
    use_model_weights=use_model_weights,
    manager_controlled_overall_weight=manager_controlled_overall_weight,
    win_percentages_overall_weight=win_percentages_overall_weight,
    points_against_overall_weight=points_against_overall_weight,
    season_rank_weight=season_rank_weight,
    metrics_dict=metric_weights,
    score_method=score_method,
    capped_linear_cap=capped_linear_cap,
    score_offset=score_offset,
)

PLOT_METRIC_COLS = SCORE_COLS[:-1]  # exclude total_score, handled separately

tab_rankings, tab_manager, tab_trends, tab_methodology = st.tabs(
    ["Rankings", "Manager Lookup", "Trends", "Methodology"]
)

with tab_rankings:
    st.subheader(f"Composite Rankings thru {thru_year}")
    if score_offset:
        st.caption(
            f"Bar segments sum to each manager's raw total (before the +{score_offset:.0f} "
            "score offset applied to total_score below) -- hover a segment for its metric and value."
        )
    else:
        st.caption("Hover a segment for its metric and value.")
    st.plotly_chart(build_ranking_bar(compiled_final_scores, thru_year, PLOT_METRIC_COLS), use_container_width=True)
    st.dataframe(metric_scoreboard(compiled_final_scores, thru_year), use_container_width=True)

with tab_manager:
    manager = st.selectbox("Manager", sorted(compiled_final_scores.index.unique()))
    view = explain_manager_view(manager, raw_scores, compiled_final_scores, thru_year)
    if view is None:
        st.info(f"No data for {manager} thru {thru_year}.")
    else:
        st.metric("Rank", f"{view['rank']} of {view['of']}")
        st.subheader("Final weighted scores")
        st.dataframe(view["score_breakdown"], use_container_width=True)
        st.subheader("Z-scores by metric x season")
        st.caption("The recency-adjusted z-score that actually feeds the weighting.")
        st.dataframe(view["zscore_pivot"], use_container_width=True)

        st.subheader("Metric trends")
        st.caption(f"Each chart is one row of the table above, {manager}'s z-score by season for that metric.")
        metric_names = view["zscore_pivot"].index.tolist()
        for i in range(0, len(metric_names), 2):
            cols = st.columns(2)
            for col, metric in zip(cols, metric_names[i:i + 2]):
                with col:
                    st.plotly_chart(build_manager_metric_trend(manager, raw_scores, metric), use_container_width=True)

with tab_trends:
    hue_order = sorted(compiled_final_scores.index.unique())
    color_map = color_map_for(hue_order)
    master_df = load_all_data()["master"]
    last_season_by_manager = build_last_season_by_manager(master_df)

    st.caption("Hover a line for the manager name and season value.")

    axhline = score_offset if score_method == "capped_linear" else None
    st.subheader("Composite Score Over Time")
    st.plotly_chart(
        build_trend(compiled_final_scores, "total_score", last_season_by_manager, hue_order, color_map, "Score", "Composite Over Time", axhline),
        use_container_width=True,
    )

    metric_axhline = 0 if score_method == "capped_linear" else None
    for metric in PLOT_METRIC_COLS:
        st.plotly_chart(
            build_trend(compiled_final_scores, metric, last_season_by_manager, hue_order, color_map, metric, f"{metric} Over Time", metric_axhline),
            use_container_width=True,
        )

with tab_methodology:
    st.markdown(full_methodology_markdown())
