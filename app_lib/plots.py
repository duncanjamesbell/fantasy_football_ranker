"""
Trend and ranking chart builders, using Plotly for hover tooltips (manager
name on the line/segment, value on the point) -- ported from
composite_ranks.ipynb's matplotlib/seaborn yearly-trend cells, and a new
sorted stacked-bar view for the Rankings tab.

Keeps the load-bearing fixes from the notebook intact:
- last_season_by_manager / truncate_to_last_season: calculate_composite_ranks
  carries a manager's last-known career average forward into every later
  thru-year snapshot even after they stop appearing in the source data (e.g.
  Mark and David individually, after merging into "Mark+David" for 2025) --
  plotted naively that's a flat line continuing forward, which looks like
  they kept playing. This cuts each manager's line off at their real last
  season.
- A manager with only one season of data (Mark+David, Waidmann -- 2025 only)
  has no second point to draw a line segment between; Plotly's
  mode="lines+markers" still renders a visible marker for a lone point.
- hue_order (color_discrete_map keyed off it): alphabetical, so color
  assignment doesn't depend on incidental list ordering (which previously
  put Mark+David and Waidmann back-to-back with near-identical hues).
"""

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from app_lib.reporting import METRIC_DISPLAY_NAMES
from metrics.composite import MANAGER_DISPLAY_NAMES

# Consistent color per manager across every chart, keyed by alphabetical
# position -- built once a hue_order is known, via color_map_for().
_PALETTE = px.colors.qualitative.Dark24


def color_map_for(hue_order: list) -> dict:
    return {manager: _PALETTE[i % len(_PALETTE)] for i, manager in enumerate(hue_order)}


def build_last_season_by_manager(master_df: pd.DataFrame) -> pd.Series:
    last_season = master_df.groupby("manager").season.max()
    last_season.index = [MANAGER_DISPLAY_NAMES.get(m, m) for m in last_season.index]
    return last_season


def truncate_to_last_season(df: pd.DataFrame, last_season_by_manager: pd.Series) -> pd.DataFrame:
    cutoff = df.index.map(last_season_by_manager)
    return df[df["thru"] <= cutoff]


def build_ranking_bar(compiled_final_scores: pd.DataFrame, thru_year: int, score_cols: list):
    """
    Stacked bar chart for one thru-year snapshot, sorted left-to-right by
    total_score (highest first). Each stacked segment is one metric's raw
    weighted score (not merged with its points-against counterpart, unlike
    the notebook's snapshot chart) -- hover shows the metric name and value.
    """
    snap = compiled_final_scores[compiled_final_scores.thru == thru_year]
    order = snap.sort_values("total_score", ascending=False).index.tolist()

    fig = go.Figure()
    for metric in score_cols:
        label = METRIC_DISPLAY_NAMES.get(metric, metric)
        fig.add_trace(go.Bar(
            x=order,
            y=snap.loc[order, metric],
            name=label,
            hovertemplate="%{x}<br>" + label + ": %{y:.2f}<extra></extra>",
        ))
    fig.update_layout(
        barmode="relative",
        xaxis_title="Manager",
        yaxis_title="Score",
        title=f"Composite Scores Thru {thru_year} (sorted by total_score)",
        legend_title="Metric",
        # Bottom (not top) placement: with up to 10 metrics this legend wraps
        # to several rows on narrow widths, and a top legend of unknown
        # wrapped height collides with the title above it. Bottom has no
        # collision risk regardless of row count -- it just pushes further
        # down, which the extra height below accommodates.
        legend=dict(orientation="h", yanchor="top", y=-0.15, xanchor="center", x=0.5),
        height=750,
        margin=dict(b=160),
    )
    return fig


def build_trend(
    compiled_final_scores: pd.DataFrame,
    column: str,
    last_season_by_manager: pd.Series,
    hue_order: list,
    color_map: dict,
    ylabel: str,
    title: str,
    axhline: float | None = None,
):
    """One line-over-time chart for `column` (total_score or a *_score
    metric), one line per manager, hover shows manager name and value."""
    data = truncate_to_last_season(compiled_final_scores[[column, "thru"]], last_season_by_manager).reset_index()
    data = data.rename(columns={"index": "manager"})

    fig = go.Figure()
    for manager in hue_order:
        m_data = data[data.manager == manager].sort_values("thru")
        if m_data.empty:
            continue
        fig.add_trace(go.Scatter(
            x=m_data["thru"], y=m_data[column], mode="lines+markers", name=manager,
            line=dict(color=color_map[manager], width=3),
            marker=dict(size=9),
            hovertemplate=f"{manager}<br>Season: " + "%{x}<br>" + f"{ylabel}: " + "%{y:.2f}<extra></extra>",
        ))
    if axhline is not None:
        fig.add_hline(y=axhline, line_dash="dash", line_color="grey")
    fig.update_layout(
        xaxis_title="Season", yaxis_title=ylabel, title=title,
        hovermode="closest", height=750,
        # See build_ranking_bar's comment: bottom placement avoids the
        # title-collision risk a wrapped top legend has -- relevant here too,
        # since this chart can have up to ~14 manager entries.
        legend=dict(orientation="h", yanchor="top", y=-0.15, xanchor="center", x=0.5),
        margin=dict(b=180),
    )
    return fig


# Red (worst) -> white (average) -> green (best), diverging around 0 so a
# manager's below/above-average seasons for a metric are visible at a glance
# without reading the axis.
_RED_GREEN_SCALE = [[0, "#d73027"], [0.5, "#f7f7f7"], [1, "#1a9850"]]


def build_manager_metric_trend(manager: str, raw_scores: pd.DataFrame, metric: str):
    """
    One manager's normalized_score (the recency-adjusted z-score that
    actually feeds the weighting) for a single metric, over every season
    they have data for -- the same numbers as the z-score pivot table in
    Manager Lookup, one row of it turned into a chart. A dashed line at 0
    marks league-average for that metric/season. Markers are colored on a
    red (worst season shown) -> white (average) -> green (best season shown)
    scale, symmetric around 0, so performance reads at a glance.
    """
    m_data = raw_scores[(raw_scores.manager == manager) & (raw_scores.metric == metric)].sort_values("season")

    cap = max(abs(m_data["normalized_score"].min()), abs(m_data["normalized_score"].max()), 0.01)

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=m_data["season"], y=m_data["normalized_score"], mode="lines+markers",
        line=dict(width=2, color="rgba(140,140,140,0.55)"),
        marker=dict(
            size=11,
            color=m_data["normalized_score"],
            colorscale=_RED_GREEN_SCALE,
            cmin=-cap, cmax=cap,
            line=dict(width=1, color="rgba(0,0,0,0.35)"),
        ),
        hovertemplate="Season: %{x}<br>Z-score: %{y:.2f}<extra></extra>",
    ))
    fig.add_hline(y=0, line_dash="dash", line_color="grey")
    fig.update_layout(
        xaxis_title="Season", yaxis_title="Z-score", title=METRIC_DISPLAY_NAMES.get(metric, metric),
        hovermode="closest", height=350,
    )
    return fig


def build_metric_comparison_trend(managers: list, raw_scores: pd.DataFrame, metric: str, color_map: dict):
    """
    Two (or more) managers' normalized_score for a single metric, overlaid on
    one chart, one line per manager in their app-wide color -- the Manager
    Comparison tab's answer to "why is X higher/lower than me on this
    metric": lets you see whether a gap is a recent trend or long-standing.
    """
    fig = go.Figure()
    for manager in managers:
        m_data = raw_scores[(raw_scores.manager == manager) & (raw_scores.metric == metric)].sort_values("season")
        if m_data.empty:
            continue
        color = color_map.get(manager)
        fig.add_trace(go.Scatter(
            x=m_data["season"], y=m_data["normalized_score"], mode="lines+markers", name=manager,
            line=dict(width=3, color=color),
            marker=dict(size=9, color=color),
            hovertemplate=f"{manager}<br>Season: " + "%{x}<br>Z-score: %{y:.2f}<extra></extra>",
        ))
    fig.add_hline(y=0, line_dash="dash", line_color="grey")
    fig.update_layout(
        xaxis_title="Season", yaxis_title="Z-score", title=METRIC_DISPLAY_NAMES.get(metric, metric),
        hovermode="closest", height=350,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    return fig
