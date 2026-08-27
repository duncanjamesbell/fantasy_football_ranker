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
from app_lib.plots import build_last_season_by_manager, build_manager_metric_trend, build_metric_comparison_trend, build_ranking_bar, build_trend, color_map_for
from app_lib.reporting import METRIC_DISPLAY_NAMES, RAW_METRIC_COLS, SCORE_COLS, compare_managers_view, explain_manager_view, full_table_height, metric_scoreboard, style_signed
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
LATEST_YEAR = max(SEASONS)

st.sidebar.header("Controls")

with st.sidebar.expander("Advanced"):
    start_year = st.number_input("Start year", min_value=2007, max_value=LATEST_YEAR, value=2015)
    recency_bonus = st.slider(
        "Recency bonus", 0.0, 1.0, 0.25, step=0.01,
        help=(
            "How much extra weight a manager's own most-recent seasons (see "
            "'Recency window' below) get in their career average for every "
            "metric. 0.25 means those seasons count 25% more than a plain "
            "average would give them -- 0 disables the boost entirely."
        ),
    )
    recency_window = st.slider(
        "Recency window (years)", 1, 10, 4,
        help=(
            "How many of a manager's own most-recent *played* seasons get "
            "the recency bonus -- anchored to that manager's own career, not "
            "a shared calendar cutoff, and counted seasons played rather "
            "than calendar span, so a break-and-return still lands on the "
            "actual most-recent N seasons played (gaps skipped). Only "
            "applies to managers with more career seasons than this window, "
            "so a brand-new manager's whole (thin) history isn't entirely "
            "boosted."
        ),
    )

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
    weight_scale = 1.0
    if score_method == "capped_linear":
        capped_linear_cap = st.slider("Z-score cap (standard deviations)", 0.5, 4.0, 2.0, step=0.1)
        weight_scale = st.slider(
            "Weight scale", 0.1, 1.0, 0.5, step=0.05,
            help=(
                "Uniformly scales every metric's weight. Since capped_linear's score "
                "is exactly linear in weight, this can never change rank order (verified: "
                "Spearman correlation of 1.0 between full- and half-weight rankings) -- "
                "it only rescales how large the numbers look. Defaults to 0.5 to keep "
                "totals closer to cascade's historical scale."
            ),
        )
        score_offset = st.slider("Score offset", 0, 100, 25, step=5, help="Added to total_score only, to keep totals positive.")

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
            METRIC_DISPLAY_NAMES[metric], min_value=0, max_value=50, value=default, key=f"weight_{metric}",
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
    weight_scale=weight_scale,
)

PLOT_METRIC_COLS = SCORE_COLS[:-1]  # exclude total_score, handled separately

tab_rankings, tab_manager, tab_comparison, tab_trends, tab_methodology = st.tabs(
    ["Rankings", "Manager Lookup", "Manager Comparison", "Trends", "Methodology"]
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
    scoreboard = metric_scoreboard(compiled_final_scores, thru_year)
    score_cols = [c for c in scoreboard.columns if c != "rank"]
    st.dataframe(
        style_signed(scoreboard, subset=score_cols, exclude_cols=["Total Score"]),
        use_container_width=True, height=full_table_height(scoreboard),
    )

with tab_manager:
    manager = st.selectbox("Manager", sorted(compiled_final_scores.index.unique()))
    view = explain_manager_view(manager, raw_scores, compiled_final_scores, thru_year)
    if view is None:
        st.info(f"No data for {manager} thru {thru_year}.")
    else:
        st.metric("Rank", f"{view['rank']} of {view['of']}")
        st.subheader("Final weighted scores")
        if score_offset:
            st.caption(
                f"Total Score includes a +{score_offset:.0f} offset applied only at the total "
                "(to keep totals positive) -- the metric rows above it will not sum to it exactly; "
                f"they sum to Total Score minus {score_offset:.0f}."
            )
        st.dataframe(
            style_signed(view["score_breakdown"], exclude_rows=["Total Score"]),
            use_container_width=True, height=full_table_height(view["score_breakdown"]),
        )
        st.subheader("Z-scores by metric x season")
        st.caption("The recency-adjusted z-score that actually feeds the weighting.")
        zscore_display = view["zscore_pivot"].rename(index=METRIC_DISPLAY_NAMES)
        st.dataframe(style_signed(zscore_display), use_container_width=True)

        st.subheader("Metric trends")
        st.caption(f"Each chart is one row of the table above, {manager}'s z-score by season for that metric.")
        metric_names = view["zscore_pivot"].index.tolist()
        for i in range(0, len(metric_names), 2):
            cols = st.columns(2)
            for col, metric in zip(cols, metric_names[i:i + 2]):
                with col:
                    st.plotly_chart(build_manager_metric_trend(manager, raw_scores, metric), use_container_width=True)

with tab_comparison:
    all_managers = sorted(compiled_final_scores.index.unique())
    cmp_color_map = color_map_for(all_managers)

    st.caption("Compare two managers side by side to see exactly which metrics are driving the gap between them.")
    col_a, col_b = st.columns(2)
    with col_a:
        manager_a = st.selectbox("Manager A", all_managers, index=0, key="cmp_manager_a")
    with col_b:
        default_b = 1 if len(all_managers) > 1 else 0
        manager_b = st.selectbox("Manager B", all_managers, index=default_b, key="cmp_manager_b")

    if manager_a == manager_b:
        st.info("Select two different managers to compare.")
    else:
        cmp = compare_managers_view(manager_a, manager_b, compiled_final_scores, thru_year)
        if cmp is None:
            st.info(f"No data for {manager_a} and/or {manager_b} thru {thru_year}.")
        else:
            rank_col_a, rank_col_b = st.columns(2)
            rank_col_a.metric(f"{manager_a} rank", f"{cmp['rank_a']} of {cmp['of']}")
            rank_col_b.metric(f"{manager_b} rank", f"{cmp['rank_b']} of {cmp['of']}")

            st.subheader("Score breakdown")
            caption = (
                f"Positive in '{cmp['diff_col']}' means {manager_a} scores higher on that metric; "
                f"negative means {manager_b} does. Sorted by the size of the gap, biggest driver first."
            )
            if score_offset:
                caption += (
                    f" Total Score includes a +{score_offset:.0f} offset applied only at the total -- "
                    "the metric rows above it don't include it."
                )
            st.caption(caption)
            st.dataframe(
                style_signed(
                    cmp["comparison"], subset=[manager_a, manager_b, cmp["diff_col"]],
                    exclude_rows=["Total Score"], exclude_rows_cols=[manager_a, manager_b],
                ),
                use_container_width=True, height=full_table_height(cmp["comparison"]),
            )

            st.subheader("Total Score over time")
            master_df = load_all_data()["master"]
            last_season_by_manager = build_last_season_by_manager(master_df)
            cmp_axhline = score_offset if score_method == "capped_linear" else None
            st.plotly_chart(
                build_trend(
                    compiled_final_scores, "total_score", last_season_by_manager, [manager_a, manager_b],
                    cmp_color_map, "Score", f"{manager_a} vs {manager_b} -- Total Score Over Time", cmp_axhline,
                ),
                use_container_width=True,
            )

            st.subheader("Metric trends")
            st.caption(f"Each chart overlays {manager_a} and {manager_b}'s z-score by season for that metric.")
            for i in range(0, len(RAW_METRIC_COLS), 2):
                cols = st.columns(2)
                for col, metric in zip(cols, RAW_METRIC_COLS[i:i + 2]):
                    with col:
                        st.plotly_chart(
                            build_metric_comparison_trend([manager_a, manager_b], raw_scores, metric, cmp_color_map),
                            use_container_width=True,
                        )

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
        label = METRIC_DISPLAY_NAMES.get(metric, metric)
        st.plotly_chart(
            build_trend(compiled_final_scores, metric, last_season_by_manager, hue_order, color_map, label, f"{label} Over Time", metric_axhline),
            use_container_width=True,
        )

with tab_methodology:
    st.markdown(full_methodology_markdown())
