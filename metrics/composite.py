"""
metrics/composite.py

Composite ranking computation extracted from composite_ranks.ipynb.
Visualization code (seaborn charts, manager_spotlight) stays in the notebook.
Only calculation lives here.

Public API:
    load_overrides(path)          -> dict
    create_metric_dict(...)       -> dict
    calculate_composite_ranks(...)-> (compiled_df, raw_scores_df)
"""

import math
import statistics as stats

import numpy as np
import pandas as pd
import yaml


# ---------------------------------------------------------------------------
# Display name mapping (full internal name -> short display name)
# This is the inverse of config.MANAGER_NAME_MAP.
# ---------------------------------------------------------------------------
MANAGER_DISPLAY_NAMES: dict[str, str] = {
    'Kevin':            'KJ',
    'David Casstevens': 'David',
    'Scott Gunter':     'Scott',
    'Benjamin':         'Ben',
    'Patrick':          'Pat',
}

# Rank-to-weighted-score tables by league size
RANK_WEIGHTS: dict[int, dict[int, int]] = {
    6:  {1: 15, 2: 10, 3: 7,  4: 4,  5: 1,  6: 0},
    8:  {1: 18, 2: 13, 3: 10, 4: 7,  5: 5,  6: 4,  7: 1,  8: 0},
    10: {1: 20, 2: 15, 3: 12, 4: 9,  5: 7,  6: 6,  7: 3,  8: 2,  9: 1, 10: 0},
}

# Default computation parameters (match notebook defaults)
DEFAULT_START_YEAR                    = 2015
DEFAULT_RECENCY_BONUS                 = 0.15
DEFAULT_RECENCY_WINDOW                = 5
DEFAULT_USE_MODEL_WEIGHTS             = True
DEFAULT_MANAGER_CONTROLLED_WEIGHT     = 0.75
DEFAULT_WIN_PERCENTAGES_WEIGHT        = 0.12
DEFAULT_POINTS_AGAINST_WEIGHT         = 0.13
DEFAULT_SEASON_RANK_WEIGHT            = 15


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------

def load_overrides(path: str) -> dict:
    """Load data/reference/overrides.yaml and return as a dict."""
    with open(path, encoding='utf-8') as f:
        return yaml.safe_load(f) or {}


def create_metric_dict(metrics_dict: dict, values, metric: str, ascending: bool) -> dict:
    """
    Map each unique metric value to a weighted score using variance-based
    cascading for all metrics except points_against (which uses linear scaling).
    Faithful copy of the notebook implementation.
    """
    metric_dict = {}
    df = (
        pd.DataFrame(values, columns=['value'])
        .sort_values(by=['value'], ascending=ascending)
        .drop_duplicates()
        .reset_index(drop=True)
    )

    if metric not in ('rs_points_against', 'playoff_points_against'):
        variances = []
        for index, row in df.iterrows():
            if index == 0:
                variances.append(0)
            else:
                variances.append(abs(df.iloc[index - 1]['value'] - row['value']))

        sum_variance = sum(variances)
        for i in range(len(variances)):
            if i == 0:
                metric_dict[df.iloc[i]['value']] = metrics_dict[metric]
                last_value = metrics_dict[metric]
            else:
                percent_variance = variances[i] / sum_variance
                next_value = last_value - (last_value * percent_variance)
                metric_dict[df.iloc[i]['value']] = next_value
                last_value = next_value
    else:
        for value in df.value:
            metric_dict[value] = value * metrics_dict[metric]

    return metric_dict


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _preprocess_master(master_df: pd.DataFrame, overrides: dict) -> pd.DataFrame:
    """
    Deduplicate co-manager rows and apply manual corrections before computation.

    Steps (in order):
    1. Generic dedup: for each (season, manager) with >1 row keep the one with
       the lowest rank value (best final standing).
    2. Row reattributions: relabel manager on rows the scraper misattributed.
    3. Rank corrections: fix rank values that are still wrong after dedup.
    4. p_score corrections: overwrite revised_p_score with known-good values.
    """
    original = master_df.copy()
    df       = master_df.copy()
    cfg      = overrides.get('co_manager_dedup', {})

    # ---- 1. Generic dedup --------------------------------------------------
    if cfg.get('enabled', False):
        # idxmin() gives one index per group — the row with the smallest rank.
        keep_idx = df.groupby(['season', 'manager'])['rank'].idxmin()
        df = df.loc[keep_idx].reset_index(drop=True)

    # ---- 2. Row reattributions ---------------------------------------------
    for entry in cfg.get('row_reattributions', []):
        season   = entry['season']
        from_mgr = entry['from_manager']
        from_rnk = entry['from_rank']
        to_mgr   = entry['to_manager']

        # Only act if to_manager is absent from this season after dedup
        if df[(df.season == season) & (df.manager == to_mgr)].empty:
            source = original[
                (original.season  == season) &
                (original.manager == from_mgr) &
                (original['rank'] == from_rnk)
            ].copy()
            if not source.empty:
                source['manager'] = to_mgr
                df = pd.concat([df, source], ignore_index=True)

    # ---- 3. Rank corrections -----------------------------------------------
    for entry in cfg.get('rank_corrections', []):
        mask = (df.season == entry['season']) & (df.manager == entry['manager'])
        if mask.any():
            df.loc[mask, 'rank'] = entry['correct_rank']

    # ---- 4. p_score corrections --------------------------------------------
    for entry in overrides.get('p_score_overrides', []):
        manager   = entry.get('manager')
        season    = entry.get('season')
        corrected = entry.get('corrected')
        if manager and season and corrected is not None:
            mask = (df.season == season) & (df.manager == manager)
            if mask.any():
                df.loc[mask, 'revised_p_score'] = corrected

    return df


def _intersection(lst1: list, lst2: list) -> list:
    return [v for v in lst1 if v in lst2]


def _get_league_size(season: int, observed_count: int, overrides: dict) -> int:
    """Return league size, preferring overrides.yaml over observed manager count.

    Supports a special '_default' key for seasons not explicitly listed.
    Co-manager seasons have fewer rows after dedup, so the default (10) ensures
    the correct playoff match structure is used.
    """
    sizes = overrides.get('league_sizes', {})
    if season in sizes:
        return sizes[season]
    return sizes.get('_default', observed_count)


# ---------------------------------------------------------------------------
# Main function
# ---------------------------------------------------------------------------

def calculate_composite_ranks(
    master_df:   pd.DataFrame,
    rs_df:       pd.DataFrame,
    draft_df:    pd.DataFrame,
    faab_df:     pd.DataFrame,
    playoffs_df: pd.DataFrame,
    thru_year:   int,
    overrides:   dict | None = None,
    start_year:  int   = DEFAULT_START_YEAR,
    pre_managers: list | None = None,
    recency_bonus: float = DEFAULT_RECENCY_BONUS,
    recency_window: int  = DEFAULT_RECENCY_WINDOW,
    use_model_weights: bool  = DEFAULT_USE_MODEL_WEIGHTS,
    manager_controlled_overall_weight: float = DEFAULT_MANAGER_CONTROLLED_WEIGHT,
    win_percentages_overall_weight:    float = DEFAULT_WIN_PERCENTAGES_WEIGHT,
    points_against_overall_weight:     float = DEFAULT_POINTS_AGAINST_WEIGHT,
    season_rank_weight: float = DEFAULT_SEASON_RANK_WEIGHT,
    Metrics_dict: dict | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Compute composite fantasy football rankings.

    Parameters
    ----------
    master_df   : consolidated_master.csv — one row per manager per season.
                  Must have: team_key, season, manager, rank, playoff_seed,
                  playoff_wins, points_for, points_against, wins, losses,
                  revised_p_score.
    rs_df       : all_regular_season_thru_{thru_year}.csv — one row per
                  starting roster slot per week. Must have: season,
                  manager_name, is_drafted, score.
    draft_df    : full_seasons_draft_df.csv — one row per drafted player.
                  Must have: Year, Owner, draft_score.
    faab_df     : faab_thru_{thru_year}.csv — FAAB transaction log.
                  Must have: season, awardee_url, faab_dollars, failed_bids.
    playoffs_df : all_playoffs_thru_{thru_year}.csv — one row per playoff
                  starting slot. Must have: season (or derivable from
                  league_id), manager_id, opponent_id, score.
    thru_year   : most recent season included (e.g. 2024).
    overrides   : dict from load_overrides(); used for league_sizes.
    pre_managers: all managers ever in the league (full canonical names).
                  Defaults to all unique managers in master_df.

    Returns
    -------
    (compiled_final_scores_df, raw_scores_df)
    """
    if overrides is None:
        overrides = {}

    Master            = _preprocess_master(master_df, overrides)
    full_rs_matchups_df = rs_df.copy()
    full_seasons_draft_df = draft_df.copy()
    full_faab         = faab_df.copy()
    full_playoffs     = playoffs_df.copy()

    # Derive season from league_id if missing (using config.LEAGUE_URLS)
    if 'season' not in full_playoffs.columns and 'league_id' in full_playoffs.columns:
        from config import LEAGUE_URLS
        lid_to_year = {
            int(url.split('/f1/')[-1].split('/')[0]): yr
            for yr, url in LEAGUE_URLS.items()
        }
        full_playoffs['season'] = full_playoffs['league_id'].map(lid_to_year)

    if pre_managers is None:
        pre_managers = sorted(Master['manager'].unique().tolist())

    # ------------------------------------------------------------------
    # Build metrics_dict from model-derived or user-supplied weights
    # ------------------------------------------------------------------
    manager_controlled_weights = {
        'rs_points':          0.151,
        'playoff_points':     0.103,
        'draft_efficiency':   0.035,
        'faab_efficiency':    0.023,
        'undrafted_savvy':    0.014,
    }
    win_percentage_weights = {
        'rs_win_percentage':    0.209,
        'playoff_win_percentage': 0.129,
    }
    points_against_weights = {
        'rs_points_against':    0.146,
        'playoff_points_against': 0.033,
    }
    invert_manager_uncontrolled_weights = False

    if use_model_weights:
        metrics_dict: dict = {}
        available_weight = 100 - season_rank_weight

        sum_mc = sum(manager_controlled_weights.values())
        for k in manager_controlled_weights:
            proportion = manager_controlled_weights[k] / sum_mc
            metrics_dict[k] = proportion * manager_controlled_overall_weight * available_weight

        sum_wp = sum(win_percentage_weights.values())
        i = 1
        for k in win_percentage_weights:
            if invert_manager_uncontrolled_weights:
                inverted_key = list(win_percentage_weights.keys())[-i]
                proportion = win_percentage_weights[inverted_key] / sum_wp
            else:
                proportion = win_percentage_weights[k] / sum_wp
            metrics_dict[k] = proportion * win_percentages_overall_weight * available_weight
            i += 1

        sum_pa = sum(points_against_weights.values())
        i = 1
        for k in points_against_weights:
            if invert_manager_uncontrolled_weights:
                inverted_key = list(points_against_weights.keys())[-i]
                proportion = points_against_weights[inverted_key] / sum_pa
            else:
                proportion = points_against_weights[k] / sum_pa
            metrics_dict[k] = proportion * points_against_overall_weight * available_weight
            i += 1

        metrics_dict['season_rank'] = season_rank_weight
    else:
        metrics_dict = Metrics_dict or {}

    # Print weights summary
    weights_df = (
        pd.DataFrame({'metric': list(metrics_dict.keys()), 'weight': list(metrics_dict.values())})
        .sort_values('weight', ascending=False)
    )
    print('Using MODEL-derived metric weights:' if use_model_weights else 'Using USER-defined metric weights:')
    for _, row in weights_df.iterrows():
        print(f'    {row["metric"]}: {round(row["weight"], 3)}')
    print()

    total_weight = round(sum(metrics_dict.values()))
    if total_weight != 100:
        print(f'Sum Metric Weights: {total_weight}')
        print('WARNING: Metric weights do not sum to 100.\n')

    # ------------------------------------------------------------------
    # Enrich master with derived features
    # ------------------------------------------------------------------
    latest_season = Master.season.max()

    Master['rs_win_percentage'] = Master.wins / (Master.losses + Master.wins)

    # Playoff match counts per manager per season
    playoff_match_counts = []
    for _, row in Master.iterrows():
        observed = Master[Master.season == row['season']].shape[0]
        num_mgrs = _get_league_size(int(row['season']), observed, overrides)
        if math.isnan(row['playoff_seed']):
            playoff_match_counts.append(np.nan)
            continue
        seed = row['playoff_seed']
        rank = row['rank']
        if num_mgrs == 6:
            matches = 2 if seed <= 4 else 1
        elif num_mgrs in (8, 10):
            if seed <= 2:
                matches = 2
            elif seed <= 6:
                matches = 2 if rank in (5, 6) else 3
            else:
                matches = 1 if num_mgrs == 8 else 2
        else:
            matches = np.nan
        playoff_match_counts.append(matches)

    Master['playoff_matches']         = playoff_match_counts
    Master['avg_playoff_points']      = Master['revised_p_score'] / Master['playoff_matches']
    Master['playoff_win_percent']     = Master['playoff_wins'] / Master['playoff_matches']

    # Playoff points against per manager per season
    sum_p_points_against = []
    for _, row in Master.iterrows():
        manager_id = int(row['team_key'].split('.')[-1])
        season     = row['season']
        p_df = full_playoffs[full_playoffs.season == season]
        p_df = p_df[p_df.score != '�']
        p_df = p_df.copy()
        p_df['score'] = p_df['score'].astype(float)
        opponent_scores = p_df[p_df.opponent_id == manager_id].score
        sum_p_points_against.append(sum(opponent_scores))

    Master['p_points_against']          = sum_p_points_against
    Master['avg_playoff_points_against'] = Master['p_points_against'] / Master['playoff_matches']

    # ------------------------------------------------------------------
    # Per-season stats dict (used for z-score and recency bonus calc)
    # ------------------------------------------------------------------
    season_data_dict: dict = {}
    for season in Master.season.unique():
        s_df   = Master[Master.season == season]
        s_dict = {}

        win_percents = s_df.rs_win_percentage
        s_dict['win_percent_mean']  = win_percents.mean()
        s_dict['win_percent_stdev'] = stats.stdev(win_percents)

        s_pts = s_df.points_for
        s_dict['rs_points_mean']  = s_pts.mean()
        s_dict['rs_points_stdev'] = stats.stdev(s_pts)

        s_pta = s_df.points_against
        s_dict['rs_points_against_mean']  = s_pta.mean()
        s_dict['rs_points_against_stdev'] = stats.stdev(s_pta)

        p_wp = s_df[s_df.playoff_win_percent.notnull()].playoff_win_percent
        s_dict['p_win_percents_mean']  = p_wp.mean()
        s_dict['p_win_percents_stdev'] = stats.stdev(p_wp)

        a_pp = s_df[s_df.avg_playoff_points.notnull()].avg_playoff_points
        s_dict['p_points_mean']  = a_pp.mean()
        s_dict['p_points_stdev'] = stats.stdev(a_pp)

        a_ppa = s_df[s_df.avg_playoff_points_against > 0].avg_playoff_points_against
        s_dict['p_points_against_mean']  = a_ppa.mean()
        s_dict['p_points_against_stdev'] = stats.stdev(a_ppa)

        season_data_dict[season] = s_dict

    # ------------------------------------------------------------------
    # Main loop: build scores from start_year through thru_year
    # ------------------------------------------------------------------
    final_score_dfs = []

    for iteration in range(latest_season - start_year + 1):
        current_max = start_year + iteration
        print(f'Calculating data thru {current_max}')
        master = Master[Master.season <= current_max]
        season_managers = _intersection(list(master.manager.unique()), pre_managers)

        compile_raw = (master.season.max() == Master.season.max())
        if compile_raw:
            raw_seasons, raw_managers, raw_metrics, raw_values = [], [], [], []

        # ---- RS WIN PERCENTAGE ----------------------------------------
        win_percent_dict: dict = {}
        for manager in season_managers:
            values_list = []
            for _, row in master[master.manager == manager].iterrows():
                if row['season'] < (latest_season - recency_window):
                    values_list.append(row['rs_win_percentage'])
                else:
                    z = (row['rs_win_percentage'] - season_data_dict[row['season']]['win_percent_mean']) / season_data_dict[row['season']]['win_percent_stdev']
                    modified = (z + z * recency_bonus) * season_data_dict[row['season']]['win_percent_stdev'] + season_data_dict[row['season']]['win_percent_mean']
                    values_list.append(modified)
                if compile_raw:
                    raw_seasons.append(row['season']); raw_managers.append(manager)
                    raw_metrics.append('avg_rs_win_percent'); raw_values.append(row['rs_win_percentage'])
            win_percent_dict[manager] = sum(values_list) / len(values_list)

        wp_score_dict = create_metric_dict(metrics_dict, win_percent_dict.values(), 'rs_win_percentage', False)
        final_scores_df = pd.DataFrame(index=win_percent_dict.keys(), data=win_percent_dict.values(), columns=['avg_rs_win_percent'])
        final_scores_df['rs_win_percent_score'] = final_scores_df.avg_rs_win_percent.map(wp_score_dict)

        # ---- RS POINTS ------------------------------------------------
        rs_pts_z: dict = {}
        for manager in season_managers:
            z_scores = []
            for _, row in master[master.manager == manager].iterrows():
                z = (row['points_for'] - season_data_dict[row['season']]['rs_points_mean']) / season_data_dict[row['season']]['rs_points_stdev']
                z_scores.append(z if row['season'] < (latest_season - recency_window) else z * (1 + recency_bonus))
                if compile_raw:
                    raw_seasons.append(row['season']); raw_managers.append(manager)
                    raw_metrics.append('rs_points'); raw_values.append(z)
            rs_pts_z[manager] = sum(z_scores) / len(z_scores)

        pts_score_dict = create_metric_dict(metrics_dict, rs_pts_z.values(), 'rs_points', False)
        final_scores_df['rs_points_z_score'] = final_scores_df.index.map(rs_pts_z)
        final_scores_df['rs_points_score']   = final_scores_df.rs_points_z_score.map(pts_score_dict)

        # ---- RS POINTS AGAINST ----------------------------------------
        rs_pta_z: dict = {}
        for manager in season_managers:
            z_scores = []
            for _, row in master[master.manager == manager].iterrows():
                z = (row['points_against'] - season_data_dict[row['season']]['rs_points_against_mean']) / season_data_dict[row['season']]['rs_points_against_stdev']
                z_scores.append(z if row['season'] < (latest_season - recency_window) else z * (1 + recency_bonus))
                if compile_raw:
                    raw_seasons.append(row['season']); raw_managers.append(manager)
                    raw_metrics.append('rs_points_against'); raw_values.append(z)
            rs_pta_z[manager] = sum(z_scores) / len(z_scores)

        pta_score_dict = create_metric_dict(metrics_dict, rs_pta_z.values(), 'rs_points_against', True)
        final_scores_df['rs_points_against_z_score'] = final_scores_df.index.map(rs_pta_z)
        final_scores_df['rs_points_against_score']   = final_scores_df.rs_points_against_z_score.map(pta_score_dict)

        # ---- PLAYOFF WIN PERCENTAGE -----------------------------------
        playoff_wins_dict: dict = {}
        for manager in season_managers:
            p_values = []
            for _, row in master[master.manager == manager].iterrows():
                if not math.isnan(row['playoff_win_percent']):
                    if row['season'] < (latest_season - recency_window):
                        p_values.append(row['playoff_win_percent'])
                    else:
                        z = (row['playoff_win_percent'] - season_data_dict[row['season']]['p_win_percents_mean']) / season_data_dict[row['season']]['p_win_percents_stdev']
                        modified = (z + z * recency_bonus) * season_data_dict[row['season']]['p_win_percents_mean'] + season_data_dict[row['season']]['p_win_percents_stdev']
                        p_values.append(modified)
                    if compile_raw:
                        raw_seasons.append(row['season']); raw_managers.append(manager)
                        raw_metrics.append('playoff_win_percentage'); raw_values.append(row['playoff_win_percent'])
            playoff_wins_dict[manager] = sum(p_values) / len(p_values) if p_values else 0.0

        pwp_score_dict = create_metric_dict(metrics_dict, playoff_wins_dict.values(), 'playoff_win_percentage', False)
        final_scores_df['avg_p_win_percent']  = final_scores_df.index.map(playoff_wins_dict)
        final_scores_df['p_win_percent_score'] = final_scores_df.avg_p_win_percent.map(pwp_score_dict)

        # ---- PLAYOFF POINTS ------------------------------------------
        playoff_pts_dict: dict = {}
        for manager in season_managers:
            z_scores = []
            for _, row in master[master.manager == manager].iterrows():
                if not math.isnan(row['avg_playoff_points']):
                    z = (row['avg_playoff_points'] - season_data_dict[row['season']]['p_points_mean']) / season_data_dict[row['season']]['p_points_stdev']
                    z_scores.append(z if row['season'] < (latest_season - recency_window) else z * (1 + recency_bonus))
                    if compile_raw:
                        raw_seasons.append(row['season']); raw_managers.append(manager)
                        raw_metrics.append('playoff_points'); raw_values.append(z)
            playoff_pts_dict[manager] = sum(z_scores) / len(z_scores)

        pp_score_dict = create_metric_dict(metrics_dict, playoff_pts_dict.values(), 'playoff_points', False)
        final_scores_df['p_points_z_score'] = final_scores_df.index.map(playoff_pts_dict)
        final_scores_df['p_points_score']   = final_scores_df.p_points_z_score.map(pp_score_dict)

        # ---- PLAYOFF POINTS AGAINST ----------------------------------
        p_pta_z: dict = {}
        for manager in season_managers:
            z_scores = []
            for _, row in master[master.manager == manager].iterrows():
                if not math.isnan(row['avg_playoff_points']):
                    z = (row['avg_playoff_points_against'] - season_data_dict[row['season']]['p_points_against_mean']) / season_data_dict[row['season']]['p_points_against_stdev']
                    z_scores.append(z if row['season'] < (latest_season - recency_window) else z * (1 + recency_bonus))
                    if compile_raw:
                        raw_seasons.append(row['season']); raw_managers.append(manager)
                        raw_metrics.append('playoff_points_against'); raw_values.append(z)
            p_pta_z[manager] = sum(z_scores) / len(z_scores)

        ppa_score_dict = create_metric_dict(metrics_dict, p_pta_z.values(), 'playoff_points_against', True)
        final_scores_df['p_points_against_z_score'] = final_scores_df.index.map(p_pta_z)
        final_scores_df['p_points_against_score']   = final_scores_df.p_points_against_z_score.map(ppa_score_dict)

        # ---- WEIGHTED SEASON RANK ------------------------------------
        rank_weights_dict = RANK_WEIGHTS
        rank_stdevs = {k: stats.stdev(v.values()) for k, v in rank_weights_dict.items()}

        weighted_rank_dict: dict = {}
        for manager in season_managers:
            wr_values = []
            for _, row in master[master.manager == manager].iterrows():
                observed = master[master.season == row['season']].shape[0]
                num_mgrs = _get_league_size(int(row['season']), observed, overrides)
                raw_wr   = rank_weights_dict[num_mgrs][row['rank']]
                if row['season'] < (latest_season - recency_window):
                    wr_values.append(raw_wr)
                else:
                    avg_w = sum(rank_weights_dict[num_mgrs].values()) / num_mgrs
                    z     = (raw_wr - avg_w) / rank_stdevs[num_mgrs]
                    modified = (z + z * recency_bonus) * rank_stdevs[num_mgrs] + avg_w
                    wr_values.append(modified)
                if compile_raw:
                    raw_seasons.append(row['season']); raw_managers.append(manager)
                    raw_metrics.append('season_rank'); raw_values.append(raw_wr)
            weighted_rank_dict[manager] = sum(wr_values) / len(wr_values)

        wr_score_dict = create_metric_dict(metrics_dict, weighted_rank_dict.values(), 'season_rank', False)
        final_scores_df['weighted_rank']       = final_scores_df.index.map(weighted_rank_dict)
        final_scores_df['weighted_rank_score'] = final_scores_df.weighted_rank.map(wr_score_dict)

        # ---- DRAFT EFFICIENCY ----------------------------------------
        assessment_draft_df = full_seasons_draft_df[
            (full_seasons_draft_df.Year <= master.season.max()) &
            (full_seasons_draft_df.Year.isin(list(master.season)))
        ]

        draft_scores_dfs = []
        for season in assessment_draft_df.Year.unique():
            s_df         = assessment_draft_df[assessment_draft_df.Year == season]
            roster_spots = s_df.Owner.value_counts().max()
            owners, draft_scores = [], []
            for owner in s_df.Owner.unique():
                owner_df       = s_df[s_df.Owner == owner]
                penalty        = (roster_spots - owner_df.shape[0]) * 0.3
                draft_score    = owner_df.draft_score.sum() / owner_df.shape[0] - penalty
                owners.append(owner); draft_scores.append(draft_score)
            d_df            = pd.DataFrame({'Owner': owners, 'Year': season, 'draft_score': draft_scores})
            draft_scores_dfs.append(d_df)
        full_draft_scores_df = pd.concat(draft_scores_dfs)

        for season in full_draft_scores_df.Year.unique():
            s_df = full_draft_scores_df[full_draft_scores_df.Year == season]
            season_data_dict[season]['draft_score_mean']  = s_df.draft_score.mean()
            season_data_dict[season]['draft_score_stdev'] = stats.stdev(s_df.draft_score)

        draft_efficiency_dict: dict = {}
        for manager in season_managers:
            m_draft_df  = full_draft_scores_df[full_draft_scores_df.Owner == manager]
            z_scores    = []
            for season in m_draft_df.Year.unique():
                raw_eff = m_draft_df[m_draft_df.Year == season].draft_score.mean()
                z       = (raw_eff - season_data_dict[season]['draft_score_mean']) / season_data_dict[season]['draft_score_stdev']
                z_scores.append(z if season < (latest_season - recency_window) else z * (1 + recency_bonus))
                if compile_raw:
                    raw_seasons.append(season); raw_managers.append(manager)
                    raw_metrics.append('draft_efficiency'); raw_values.append(z)
            draft_efficiency_dict[manager] = sum(z_scores) / len(z_scores)

        de_score_dict = create_metric_dict(metrics_dict, draft_efficiency_dict.values(), 'draft_efficiency', False)
        final_scores_df['draft_efficiency']       = final_scores_df.index.map(draft_efficiency_dict)
        final_scores_df['draft_efficiency_score'] = final_scores_df.draft_efficiency.map(de_score_dict)

        # ---- UNDRAFTED SAVVY (in-season pickup) ----------------------
        non_drafted_avg_scores = []
        for season in master.season.unique():
            season_matchups = full_rs_matchups_df[full_rs_matchups_df.season == season]
            manager_avg_scores: dict = {}
            for manager in season_matchups.manager_name.unique():
                m_non_drafted = season_matchups[
                    (season_matchups.manager_name == manager) & (season_matchups.is_drafted == 0)
                ].copy()
                cleaned = [0 if s == '�' else s for s in m_non_drafted.score]
                m_non_drafted['score'] = pd.Series(pd.to_numeric(cleaned, errors='coerce')).fillna(0).values
                avg_score = m_non_drafted.score.sum() / m_non_drafted.shape[0]
                manager_avg_scores[manager] = avg_score
            nd_df = pd.DataFrame(index=manager_avg_scores.keys(), data=manager_avg_scores.values(), columns=['avg_non_draft_score'])
            nd_stdev = stats.stdev(nd_df.avg_non_draft_score)
            nd_mean  = nd_df.avg_non_draft_score.mean()
            nd_df['zscore_non_draft_scores'] = (nd_df.avg_non_draft_score - nd_mean) / nd_stdev
            nd_df['season'] = season
            non_drafted_avg_scores.append(nd_df)
        full_non_drafted = pd.concat(non_drafted_avg_scores)

        rs_non_drafted_dict: dict = {}
        for manager in season_managers:
            m_df     = full_non_drafted[full_non_drafted.index == manager]
            z_scores = []
            for _, row in m_df.iterrows():
                z = row['zscore_non_draft_scores']
                z_scores.append(z if row['season'] < (latest_season - recency_window) else z * (1 + recency_bonus))
                if compile_raw:
                    raw_seasons.append(row['season']); raw_managers.append(manager)
                    raw_metrics.append('undrafted_savvy'); raw_values.append(z)
            rs_non_drafted_dict[manager] = sum(z_scores) / len(z_scores)

        nd_score_dict = create_metric_dict(metrics_dict, rs_non_drafted_dict.values(), 'undrafted_savvy', False)
        final_scores_df['undrafted_avg_z_score']  = final_scores_df.index.map(rs_non_drafted_dict)
        final_scores_df['undrafted_savvy_score']  = final_scores_df.undrafted_avg_z_score.map(nd_score_dict)

        # ---- FAAB EFFICIENCY -----------------------------------------
        # Clean failed_bids column
        new_bids = []
        for failed_bids in full_faab.failed_bids:
            if isinstance(failed_bids, float):
                new_bids.append('')
            else:
                clean1    = failed_bids.replace('[', '').replace(']]', '').replace(', ', ',').split(']')
                new_items = []
                for item in clean1:
                    sub = [p[1:-1] for p in item.split(',') if p]
                    new_items.append(sub)
                new_bids.append(new_items)
        full_faab = full_faab.copy()
        full_faab['failed_bids_clean'] = new_bids

        top_losing_bids = []
        for f in full_faab.failed_bids_clean:
            if not f or f == '':
                top_losing_bids.append(0)
            else:
                try:
                    top_bid = int(f[0][2].split()[0].replace('$', ''))
                except (IndexError, ValueError):
                    top_bid = 0
                top_losing_bids.append(top_bid)
        full_faab['top_losing_bid']   = top_losing_bids
        full_faab['bid_differential'] = full_faab.faab_dollars - full_faab.top_losing_bid

        manager_ids = [int(url.split('/')[-1]) for url in full_faab.awardee_url]
        full_faab['manager_id'] = manager_ids

        season_dfs_faab = []
        for season in full_faab.season.unique():
            s_faab_df  = full_faab[full_faab.season == season].copy()
            mgr_lkup   = {}
            for _, row in Master[Master.season == season].iterrows():
                mid = int(row['team_key'].split('.')[-1])
                if mid not in mgr_lkup:
                    mgr_lkup[mid] = row['manager']
            s_faab_df['manager_name'] = s_faab_df.manager_id.map(mgr_lkup)
            season_dfs_faab.append(s_faab_df)
        full_faab_m = pd.concat(season_dfs_faab)

        season_faab_score_dfs = []
        for season in master.season.unique():
            if season in list(full_faab_m.season):
                s_df = full_faab_m[full_faab_m.season == season]
                mgr_faab: dict = {}
                for manager in s_df.manager_name.dropna().unique():
                    m_df       = s_df[s_df.manager_name == manager]
                    avg_diff   = m_df.bid_differential.sum() / m_df.shape[0]
                    unused     = 100 - m_df.faab_dollars.sum()
                    efficiency = avg_diff + (unused * 0.1) + (m_df.shape[0] * 0.2)
                    mgr_faab[manager] = efficiency
                mf_df         = pd.DataFrame(index=mgr_faab.keys())
                mf_df['faab_efficiency'] = mgr_faab.values()
                f_stdev       = stats.stdev(mf_df.faab_efficiency)
                f_mean        = mf_df.faab_efficiency.mean()
                mf_df['faab_efficiency_zscore'] = (mf_df.faab_efficiency - f_mean) / f_stdev
                mf_df['season'] = season
                season_data_dict[season]['faab_efficiency_stdev'] = f_stdev
                season_data_dict[season]['faab_efficiency_mean']  = f_mean
                season_faab_score_dfs.append(mf_df)
            else:
                mf_df = pd.DataFrame(index=season_managers)
                mf_df['faab_efficiency_zscore'] = 0
                mf_df['season'] = season
                season_faab_score_dfs.append(mf_df)
        full_season_faab_dfs = pd.concat(season_faab_score_dfs)

        faab_efficiency_dict: dict = {}
        for manager in season_managers:
            m_df     = full_season_faab_dfs[full_season_faab_dfs.index == manager]
            z_scores = []
            for _, row in m_df.iterrows():
                z = row['faab_efficiency_zscore']
                if row['season'] < (latest_season - recency_window):
                    z_scores.append(z)
                else:
                    f_stdev  = season_data_dict.get(row['season'], {}).get('faab_efficiency_stdev', 1)
                    f_mean   = season_data_dict.get(row['season'], {}).get('faab_efficiency_mean',  0)
                    modified = (z + z * recency_bonus) * f_stdev + f_mean
                    z_scores.append(modified)
                if compile_raw and z != 0:
                    raw_seasons.append(row['season']); raw_managers.append(manager)
                    raw_metrics.append('faab_efficiency'); raw_values.append(z)
            faab_efficiency_dict[manager] = sum(z_scores) / len(z_scores)

        fe_score_dict = create_metric_dict(metrics_dict, faab_efficiency_dict.values(), 'faab_efficiency', True)
        final_scores_df['avg_faab_efficiency'] = final_scores_df.index.map(faab_efficiency_dict)
        final_scores_df['faab_efficiency_score'] = final_scores_df.avg_faab_efficiency.map(fe_score_dict)

        # ---- TOTAL SCORE ---------------------------------------------
        score_cols = [
            'draft_efficiency_score', 'rs_win_percent_score', 'rs_points_score',
            'rs_points_against_score', 'p_win_percent_score', 'p_points_score',
            'p_points_against_score', 'weighted_rank_score', 'undrafted_savvy_score',
            'faab_efficiency_score',
        ]
        final_scores_df['total_score'] = final_scores_df[score_cols].sum(axis=1)
        final_scores_df.sort_values('total_score', ascending=False, inplace=True)
        final_scores_df['thru'] = current_max
        final_score_dfs.append(final_scores_df)

    # ------------------------------------------------------------------
    # Assemble and clean up outputs
    # ------------------------------------------------------------------
    compiled_final_scores_df = pd.concat(final_score_dfs)

    corrected_names = [MANAGER_DISPLAY_NAMES.get(m, m) for m in compiled_final_scores_df.index]
    compiled_final_scores_df['manager'] = corrected_names
    compiled_final_scores_df.set_index('manager', inplace=True)

    raw_scores_df = pd.DataFrame({
        'season':  raw_seasons,
        'manager': raw_managers,
        'metric':  raw_metrics,
        'score':   raw_values,
    }).drop_duplicates()
    raw_scores_df['manager'] = [MANAGER_DISPLAY_NAMES.get(m, m) for m in raw_scores_df.manager]

    # Normalize raw scores for display
    inv_rank_weights = {k: {v: ki for ki, v in d.items()} for k, d in RANK_WEIGHTS.items()}
    normalized_scores = []
    for _, row in raw_scores_df.iterrows():
        season  = row['season']
        metric  = row['metric']
        score   = row['score']
        if metric == 'avg_rs_win_percent':
            norm = (score - season_data_dict[season]['win_percent_mean']) / season_data_dict[season]['win_percent_stdev']
        elif metric == 'playoff_win_percentage':
            norm = (score - season_data_dict[season]['p_win_percents_mean']) / season_data_dict[season]['p_win_percents_stdev']
        elif metric == 'season_rank':
            num_mgrs = raw_scores_df[raw_scores_df.season == season].drop_duplicates('manager').shape[0]
            num_mgrs = _get_league_size(season, num_mgrs, overrides)
            actual_rank = inv_rank_weights[num_mgrs][score]
            norm        = actual_rank / num_mgrs
        else:
            norm = score
        normalized_scores.append(norm)
    raw_scores_df['normalized_score'] = normalized_scores

    return compiled_final_scores_df, raw_scores_df
