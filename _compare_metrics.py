"""
Metric-by-metric comparison: original Colab logic vs. refactored pipeline.
Run with: py -3 _compare_metrics.py
"""

import math, statistics as stats
import numpy as np
import pandas as pd

pd.options.mode.chained_assignment = None

# -- PARAMETERS (identical for both runs) --------------------------------------
PRE_MANAGERS = [
    'Benjamin','Bryan','David Casstevens','Duncan','Kevin',
    'Krista','Luke','Mark','Patrick','Scott Gunter',
]
METRICS_DICT = {
    'draft_efficiency': 6, 'faab_efficiency': 3, 'undrafted_savvy': 6,
    'rs_win_percentage': 5, 'rs_points': 38, 'rs_points_against': 8,
    'playoff_win_percentage': 6, 'playoff_points': 8,
    'playoff_points_against': 5, 'season_rank': 15,
}
RECENCY_BONUS  = 0.25
RECENCY_WINDOW = 4
START_YEAR     = 2015
THRU_YEAR      = 2024

MANAGER_NAME_DICT = {
    'Kevin': 'KJ', 'David Casstevens': 'David',
    'Scott Gunter': 'Scott', 'Benjamin': 'Ben', 'Patrick': 'Pat',
}

# -- DATA LOADING --------------------------------------------------------------
# Original uses the GitHub revised master; we use the local copy.
Master_orig = pd.read_csv('consolidated_master_revised_2024_20250809.csv')

# Shared supporting files (same for both)
full_rs_matchups_df   = pd.read_csv('data/processed/all_regular_season_thru_2024.csv')
full_seasons_draft_df = pd.read_csv('data/processed/full_seasons_draft_df.csv')
full_faab_raw         = pd.read_csv('data/processed/faab_thru_2024.csv')
full_playoffs         = pd.read_csv('data/processed/all_playoffs_thru_2024.csv')

# Refactored uses local master + overrides
from metrics.composite import calculate_composite_ranks, load_overrides
from config import CONSOLIDATED_MASTER_PATH, OVERRIDES_PATH

Master_refac = pd.read_csv(CONSOLIDATED_MASTER_PATH)
overrides    = load_overrides(OVERRIDES_PATH)


# ══════════════════════════════════════════════════════════════════════════════
# ORIGINAL COLAB FUNCTION  (copied exactly; only data-loading refs swapped)
# ══════════════════════════════════════════════════════════════════════════════

def create_metric_dict_orig(metrics_dict, values, metric, ascending):
    metric_dict = {}
    df = pd.DataFrame(values, columns=['value'])\
           .sort_values(by=['value'], ascending=ascending)\
           .drop_duplicates().reset_index(drop=True)
    if metric not in ['rs_points_against', 'playoff_points_against']:
        variances = []
        for index, row in df.iterrows():
            if index == 0:
                variances.append(0)
            else:
                variances.append(abs(df.iloc[index-1]['value'] - row['value']))
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


def intersection(lst1, lst2):
    return [v for v in lst1 if v in lst2]


def run_original(Master, full_rs_matchups_df, full_seasons_draft_df,
                 full_faab, full_playoffs,
                 start_year, pre_managers, recency_bonus, recency_window,
                 Metrics_dict):

    metrics_dict = Metrics_dict
    latest_season = Master.season.max()

    Master['rs_win_percentage'] = Master.wins / (Master.losses + Master.wins)

    # Playoff match counts
    playoff_match_counts = []
    for index, row in Master.iterrows():
        number_managers = Master[Master.season == row['season']].shape[0]
        if math.isnan(row['playoff_seed']):
            playoff_match_counts.append(np.nan)
        else:
            if number_managers == 6:
                matches = 2 if row['playoff_seed'] <= 4 else 1
            elif number_managers == 8:
                if row['playoff_seed'] <= 2:
                    matches = 2
                elif row['playoff_seed'] <= 6:
                    matches = 2 if row['rank'] in [5, 6] else 3
                else:
                    matches = 1
            elif number_managers == 10:
                if row['playoff_seed'] <= 2:
                    matches = 2
                elif row['playoff_seed'] <= 6:
                    matches = 2 if row['rank'] in [5, 6] else 3
                else:
                    matches = 2
            else:
                matches = np.nan
            playoff_match_counts.append(matches)
    Master['playoff_matches']     = playoff_match_counts
    Master['avg_playoff_points']  = Master['revised_p_score'] / Master['playoff_matches']
    Master['playoff_win_percent'] = Master['playoff_wins'] / Master['playoff_matches']

    # Playoff points against
    sum_p_points_against = []
    for index, row in Master.iterrows():
        manager_id = int(row['team_key'].split('.')[-1])
        season = row['season']
        playoff_df = full_playoffs[full_playoffs.season == season]
        playoff_df = playoff_df[playoff_df.score != '–']
        playoff_df['score'] = playoff_df['score'].astype(float)
        opponent_scores = playoff_df[playoff_df.opponent_id == manager_id].score
        sum_p_points_against.append(sum(opponent_scores))
    Master['p_points_against']          = sum_p_points_against
    Master['avg_playoff_points_against'] = Master['p_points_against'] / Master['playoff_matches']

    # Per-season stats
    season_data_dict = {}
    for season in Master.season.drop_duplicates():
        s_df   = Master[Master.season == season]
        s_dict = {}
        wp = s_df.rs_win_percentage
        s_dict['win_percent_mean']  = sum(wp) / len(wp)
        s_dict['win_percent_stdev'] = stats.stdev(wp)
        sp = s_df.points_for
        s_dict['rs_points_mean']  = sum(sp) / len(sp)
        s_dict['rs_points_stdev'] = stats.stdev(sp)
        spa = s_df.points_against
        s_dict['rs_points_against_mean']  = sum(spa) / len(spa)
        s_dict['rs_points_against_stdev'] = stats.stdev(spa)
        pwp = s_df[s_df.playoff_win_percent.notnull()].playoff_win_percent
        s_dict['p_win_percents_mean']  = sum(pwp) / len(pwp)
        s_dict['p_win_percents_stdev'] = stats.stdev(pwp)
        app = s_df[s_df.avg_playoff_points.notnull()].avg_playoff_points
        s_dict['p_points_mean']  = sum(app) / len(app)
        s_dict['p_points_stdev'] = stats.stdev(app)
        appa = s_df[s_df.avg_playoff_points_against > 0].avg_playoff_points_against
        s_dict['p_points_against_mean']  = sum(appa) / len(appa)
        s_dict['p_points_against_stdev'] = stats.stdev(appa)
        season_data_dict[season] = s_dict

    rank_weights_dict = {
        6:  {1:15,2:10,3:7, 4:4, 5:1, 6:0},
        8:  {1:18,2:13,3:10,4:7, 5:5, 6:4, 7:1, 8:0},
        10: {1:20,2:15,3:12,4:9, 5:7, 6:6, 7:3, 8:2, 9:1,10:0},
    }
    weighted_rank_stdevs_dict = {k: stats.stdev(v.values()) for k, v in rank_weights_dict.items()}

    final_score_dfs = []

    for it in range(latest_season - start_year + 1):
        cur = start_year + it
        master = Master[Master.season <= cur]
        season_managers = intersection(list(master.manager), pre_managers)

        # RS WIN PERCENTAGE
        win_percent_dict = {}
        for manager in season_managers:
            vals = []
            for _, row in master[master.manager == manager].iterrows():
                if row['season'] < (latest_season - recency_window):
                    vals.append(row['rs_win_percentage'])
                else:
                    z = (row['rs_win_percentage'] - season_data_dict[row['season']]['win_percent_mean']) / season_data_dict[row['season']]['win_percent_stdev']
                    modified = (z + z * recency_bonus) * season_data_dict[row['season']]['win_percent_stdev'] + season_data_dict[row['season']]['win_percent_mean']
                    vals.append(modified)
            win_percent_dict[manager] = sum(vals) / len(vals)
        wp_score = create_metric_dict_orig(metrics_dict, win_percent_dict.values(), 'rs_win_percentage', False)
        fdf = pd.DataFrame(index=win_percent_dict.keys(), data=win_percent_dict.values(), columns=['avg_rs_win_percent'])
        fdf['rs_win_percent_score'] = fdf.avg_rs_win_percent.map(wp_score)

        # RS POINTS
        rs_pts_z = {}
        for manager in season_managers:
            zs = []
            for _, row in master[master.manager == manager].iterrows():
                z = (row['points_for'] - season_data_dict[row['season']]['rs_points_mean']) / season_data_dict[row['season']]['rs_points_stdev']
                zs.append(z if row['season'] < (latest_season - recency_window) else z * (1 + recency_bonus))
            rs_pts_z[manager] = sum(zs) / len(zs)
        pts_score = create_metric_dict_orig(metrics_dict, rs_pts_z.values(), 'rs_points', False)
        fdf['rs_points_z_score'] = fdf.index.map(rs_pts_z)
        fdf['rs_points_score']   = fdf.rs_points_z_score.map(pts_score)

        # RS POINTS AGAINST
        rs_pta_z = {}
        for manager in season_managers:
            zs = []
            for _, row in master[master.manager == manager].iterrows():
                z = (row['points_against'] - season_data_dict[row['season']]['rs_points_against_mean']) / season_data_dict[row['season']]['rs_points_against_stdev']
                zs.append(z if row['season'] < (latest_season - recency_window) else z * (1 + recency_bonus))
            rs_pta_z[manager] = sum(zs) / len(zs)
        pta_score = create_metric_dict_orig(metrics_dict, rs_pta_z.values(), 'rs_points_against', True)
        fdf['rs_points_against_z_score'] = fdf.index.map(rs_pta_z)
        fdf['rs_points_against_score']   = fdf.rs_points_against_z_score.map(pta_score)

        # PLAYOFF WIN PERCENTAGE  (original has mean/stdev swapped — preserved exactly)
        playoff_wins_dict = {}
        for manager in season_managers:
            pvals = []
            for _, row in master[master.manager == manager].iterrows():
                if not math.isnan(row['playoff_win_percent']):
                    if row['season'] < (latest_season - recency_window):
                        pvals.append(row['playoff_win_percent'])
                    else:
                        z = (row['playoff_win_percent'] - season_data_dict[row['season']]['p_win_percents_mean']) / season_data_dict[row['season']]['p_win_percents_stdev']
                        # BUG in original: mean and stdev are swapped
                        modified = (z + z * recency_bonus) * season_data_dict[row['season']]['p_win_percents_mean'] + season_data_dict[row['season']]['p_win_percents_stdev']
                        pvals.append(modified)
            playoff_wins_dict[manager] = sum(pvals) / len(pvals)
        pwp_score = create_metric_dict_orig(metrics_dict, playoff_wins_dict.values(), 'playoff_win_percentage', False)
        fdf['avg_p_win_percent']   = fdf.index.map(playoff_wins_dict)
        fdf['p_win_percent_score'] = fdf.avg_p_win_percent.map(pwp_score)

        # PLAYOFF POINTS
        playoff_pts_dict = {}
        for manager in season_managers:
            zs = []
            for _, row in master[master.manager == manager].iterrows():
                if not math.isnan(row['avg_playoff_points']):
                    z = (row['avg_playoff_points'] - season_data_dict[row['season']]['p_points_mean']) / season_data_dict[row['season']]['p_points_stdev']
                    zs.append(z if row['season'] < (latest_season - recency_window) else z * (1 + recency_bonus))
            playoff_pts_dict[manager] = sum(zs) / len(zs) if zs else 0.0
        pp_score = create_metric_dict_orig(metrics_dict, playoff_pts_dict.values(), 'playoff_points', False)
        fdf['p_points_z_score'] = fdf.index.map(playoff_pts_dict)
        fdf['p_points_score']   = fdf.p_points_z_score.map(pp_score)

        # PLAYOFF POINTS AGAINST
        p_pta_z = {}
        for manager in season_managers:
            zs = []
            for _, row in master[master.manager == manager].iterrows():
                if not math.isnan(row['avg_playoff_points']):
                    z = (row['avg_playoff_points_against'] - season_data_dict[row['season']]['p_points_against_mean']) / season_data_dict[row['season']]['p_points_against_stdev']
                    zs.append(z if row['season'] < (latest_season - recency_window) else z * (1 + recency_bonus))
            p_pta_z[manager] = sum(zs) / len(zs) if zs else 0.0
        ppa_score = create_metric_dict_orig(metrics_dict, p_pta_z.values(), 'playoff_points_against', True)
        fdf['p_points_against_z_score'] = fdf.index.map(p_pta_z)
        fdf['p_points_against_score']   = fdf.p_points_against_z_score.map(ppa_score)

        # WEIGHTED SEASON RANK
        weighted_rank_dict = {}
        for manager in season_managers:
            wr_vals = []
            for _, row in master[master.manager == manager].iterrows():
                num_mgrs  = master[master.season == row['season']].shape[0]
                raw_wr    = rank_weights_dict[num_mgrs][row['rank']]
                if row['season'] < (latest_season - recency_window):
                    wr_vals.append(raw_wr)
                else:
                    avg_w    = sum(rank_weights_dict[num_mgrs].values()) / num_mgrs
                    z        = (raw_wr - avg_w) / weighted_rank_stdevs_dict[num_mgrs]
                    modified = (z + z * recency_bonus) * weighted_rank_stdevs_dict[num_mgrs] + avg_w
                    wr_vals.append(modified)
            weighted_rank_dict[manager] = sum(wr_vals) / len(wr_vals)
        wr_score = create_metric_dict_orig(metrics_dict, weighted_rank_dict.values(), 'season_rank', False)
        fdf['weighted_rank']       = fdf.index.map(weighted_rank_dict)
        fdf['weighted_rank_score'] = fdf.weighted_rank.map(wr_score)

        # DRAFT EFFICIENCY
        addf = full_seasons_draft_df[
            (full_seasons_draft_df.Year <= master.season.max()) &
            (full_seasons_draft_df.Year.isin(list(master.season)))
        ]
        draft_scores_dfs = []
        for season in addf.Year.drop_duplicates():
            sdf        = addf[addf.Year == season]
            roster_spots = max(sdf.Owner.value_counts())
            owners, dscores = [], []
            for owner in sdf.Owner.drop_duplicates():
                odf    = sdf[sdf.Owner == owner]
                pen    = (roster_spots - odf.shape[0]) * 0.3
                ds     = sum(odf.draft_score) / odf.shape[0] - pen
                owners.append(owner); dscores.append(ds)
            tmp = pd.DataFrame({'Owner': owners, 'Year': season, 'draft_score': dscores})
            draft_scores_dfs.append(tmp)
        full_draft_scores_df = pd.concat(draft_scores_dfs)
        for season in full_draft_scores_df.Year.drop_duplicates():
            sdf = full_draft_scores_df[full_draft_scores_df.Year == season]
            season_data_dict[season]['draft_score_mean']  = sum(sdf.draft_score) / len(sdf)
            season_data_dict[season]['draft_score_stdev'] = stats.stdev(sdf.draft_score)
        draft_eff_dict = {}
        for manager in season_managers:
            mdf = full_draft_scores_df[full_draft_scores_df.Owner == manager]
            zs  = []
            for season in mdf.Year.drop_duplicates():
                raw = sum(mdf[mdf.Year == season].draft_score) / mdf[mdf.Year == season].shape[0]
                z   = (raw - season_data_dict[season]['draft_score_mean']) / season_data_dict[season]['draft_score_stdev']
                zs.append(z if season < (latest_season - recency_window) else z * (1 + recency_bonus))
            draft_eff_dict[manager] = sum(zs) / len(zs) if zs else 0.0
        de_score = create_metric_dict_orig(metrics_dict, draft_eff_dict.values(), 'draft_efficiency', False)
        fdf['draft_efficiency']       = fdf.index.map(draft_eff_dict)
        fdf['draft_efficiency_score'] = fdf.draft_efficiency.map(de_score)

        # UNDRAFTED SAVVY
        nd_frames = []
        for season in master.season.drop_duplicates():
            sm = full_rs_matchups_df[full_rs_matchups_df.season == season]
            mgr_avgs = {}
            for mgr in sm.manager_name.drop_duplicates():
                nd = sm[(sm.manager_name == mgr) & (sm.is_drafted == 0)].copy()
                cleaned = [0 if str(s) in ('–','–','�') else s for s in nd.score]
                nd['score'] = pd.array(pd.to_numeric(cleaned, errors='coerce')).fillna(0)
                mgr_avgs[mgr] = nd.score.sum() / nd.shape[0]
            ndf = pd.DataFrame(index=mgr_avgs.keys(), data=mgr_avgs.values(), columns=['avg_non_draft_score'])
            m   = ndf.avg_non_draft_score.sum() / ndf.shape[0]
            sd  = stats.stdev(ndf.avg_non_draft_score)
            ndf['zscore_non_draft_scores'] = (ndf.avg_non_draft_score - m) / sd
            ndf['season'] = season
            nd_frames.append(ndf)
        full_nd = pd.concat(nd_frames)
        nd_dict = {}
        for manager in season_managers:
            mdf = full_nd[full_nd.index == manager]
            zs  = []
            for _, row in mdf.iterrows():
                z = row['zscore_non_draft_scores']
                zs.append(z if row['season'] < (latest_season - recency_window) else z * (1 + recency_bonus))
            nd_dict[manager] = sum(zs) / len(zs)
        nd_score = create_metric_dict_orig(metrics_dict, nd_dict.values(), 'undrafted_savvy', False)
        fdf['undrafted_avg_z_score']  = fdf.index.map(nd_dict)
        fdf['undrafted_savvy_score']  = fdf.undrafted_avg_z_score.map(nd_score)

        # FAAB EFFICIENCY
        new_bids = []
        for fb in full_faab.failed_bids:
            if isinstance(fb, float):
                new_bids.append('')
            else:
                c1 = fb.replace('[','').replace(']]','').replace(', ',',').split(']')
                items = []
                for seg in c1:
                    sub = [p[1:-1] for p in seg.split(',') if p]
                    items.append(sub)
                new_bids.append(items)
        full_faab = full_faab.copy()
        full_faab['failed_bids_clean'] = new_bids
        tlb = []
        for f in full_faab.failed_bids_clean:
            if not f or f == '':
                tlb.append(0)
            else:
                try:
                    tlb.append(int(f[0][2].split()[0].replace('$','')))
                except (IndexError, ValueError):
                    tlb.append(0)
        full_faab['top_losing_bid']   = tlb
        full_faab['bid_differential'] = full_faab.faab_dollars - full_faab.top_losing_bid
        full_faab['manager_id']       = [int(u.split('/')[-1]) for u in full_faab.awardee_url]

        # Map manager IDs → names using Master (original uses revised master)
        sdfs_faab = []
        for season in full_faab.season.drop_duplicates():
            sfd = full_faab[full_faab.season == season].copy()
            lkup = {}
            for _, row in Master[Master.season == season].iterrows():
                mid = int(row['team_key'].split('.')[-1])
                if mid not in lkup:
                    lkup[mid] = row['manager']
            sfd['manager_name'] = sfd.manager_id.map(lkup)
            sdfs_faab.append(sfd)
        full_faab_m = pd.concat(sdfs_faab)

        season_faab_dfs = []
        for season in master.season.drop_duplicates():  # <-- loop variable 'season'
            if season in list(full_faab_m.season):
                sdf = full_faab_m[full_faab_m.season == season]
                mfd = {}
                for mgr in sdf.manager_name.dropna().drop_duplicates():
                    mdf       = sdf[sdf.manager_name == mgr]
                    avg_diff  = mdf.bid_differential.sum() / mdf.shape[0]
                    unused    = 100 - mdf.faab_dollars.sum()
                    eff       = avg_diff + (unused * 0.1) + (mdf.shape[0] * 0.2)
                    mfd[mgr]  = eff
                mfdf = pd.DataFrame(index=mfd.keys())
                mfdf['faab_efficiency'] = mfd.values()
                f_stdev = stats.stdev(mfdf.faab_efficiency)
                f_mean  = mfdf.faab_efficiency.sum() / mfdf.shape[0]
                mfdf['faab_efficiency_zscore'] = (mfdf.faab_efficiency - f_mean) / f_stdev
                mfdf['season'] = season
                season_data_dict[season]['faab_efficiency_stdev'] = f_stdev
                season_data_dict[season]['faab_efficiency_mean']  = f_mean
                season_faab_dfs.append(mfdf)
            else:
                mfdf = pd.DataFrame(index=season_managers)
                mfdf['faab_efficiency_zscore'] = 0
                mfdf['season'] = season
                season_faab_dfs.append(mfdf)
        full_season_faab = pd.concat(season_faab_dfs)
        # NOTE: after the loop above, 'season' retains its LAST value (the bug)

        faab_eff_dict = {}
        for manager in season_managers:
            mdf = full_season_faab[full_season_faab.index == manager]
            zs  = []
            for _, row in mdf.iterrows():
                if row['season'] < (latest_season - recency_window):
                    zs.append(row['faab_efficiency_zscore'])
                else:
                    z  = row['faab_efficiency_zscore']
                    sm = z * recency_bonus
                    # BUG: uses last 'season' from loop, not row['season']
                    modified = (z + sm) * season_data_dict[season]['faab_efficiency_stdev'] \
                             + season_data_dict[season]['faab_efficiency_mean']
                    zs.append(modified)
            faab_eff_dict[manager] = sum(zs) / len(zs)
        fe_score = create_metric_dict_orig(metrics_dict, faab_eff_dict.values(), 'faab_efficiency', True)
        fdf['avg_faab_efficiency']   = fdf.index.map(faab_eff_dict)
        fdf['faab_efficiency_score'] = fdf.avg_faab_efficiency.map(fe_score)

        score_cols = ['draft_efficiency_score','rs_win_percent_score','rs_points_score',
                      'rs_points_against_score','p_win_percent_score','p_points_score',
                      'p_points_against_score','weighted_rank_score',
                      'undrafted_savvy_score','faab_efficiency_score']
        fdf['total_score'] = fdf[score_cols].sum(axis=1)
        fdf.sort_values('total_score', ascending=False, inplace=True)
        fdf['thru'] = cur
        final_score_dfs.append(fdf)

    compiled = pd.concat(final_score_dfs)
    corrected = [MANAGER_NAME_DICT.get(m, m) for m in compiled.index]
    compiled['manager'] = corrected
    compiled.set_index('manager', inplace=True)
    return compiled


# -- RUN BOTH ------------------------------------------------------------------
print("Running original Colab logic...")
orig_compiled = run_original(
    Master_orig.copy(), full_rs_matchups_df, full_seasons_draft_df,
    full_faab_raw.copy(), full_playoffs,
    START_YEAR, PRE_MANAGERS, RECENCY_BONUS, RECENCY_WINDOW, METRICS_DICT,
)

print("Running refactored logic...")
refac_compiled, _ = calculate_composite_ranks(
    master_df=Master_refac,
    rs_df=full_rs_matchups_df,
    draft_df=full_seasons_draft_df,
    faab_df=full_faab_raw,
    playoffs_df=full_playoffs,
    thru_year=THRU_YEAR,
    overrides=overrides,
    start_year=START_YEAR,
    pre_managers=PRE_MANAGERS,
    recency_bonus=RECENCY_BONUS,
    recency_window=RECENCY_WINDOW,
    use_model_weights=False,
    Metrics_dict=METRICS_DICT,
    season_rank_weight=15,
)

# -- COMPARE THRU 2024 ---------------------------------------------------------
SCORE_COLS = [
    'rs_win_percent_score','rs_points_score','rs_points_against_score',
    'p_win_percent_score','p_points_score','p_points_against_score',
    'weighted_rank_score','draft_efficiency_score',
    'undrafted_savvy_score','faab_efficiency_score','total_score',
]

orig_2024  = orig_compiled[orig_compiled.thru  == THRU_YEAR][SCORE_COLS].sort_index()
refac_2024 = refac_compiled[refac_compiled.thru == THRU_YEAR][SCORE_COLS].sort_index()

THRESHOLD = 0.001  # differences smaller than this are treated as identical

print(f"\n{'='*80}")
print(f"METRIC-BY-METRIC COMPARISON  (thru {THRU_YEAR})")
print(f"{'='*80}\n")

for col in SCORE_COLS:
    o = orig_2024[col].round(6)
    r = refac_2024[col].round(6)
    diff = (o - r).abs()
    max_diff = diff.max()
    is_identical = max_diff < THRESHOLD
    status = "IDENTICAL" if is_identical else f"DIFFERS  (max |delta| = {max_diff:.4f})"
    print(f"{'-'*60}")
    print(f"{col:35s}  [{status}]")
    if not is_identical:
        cmp = pd.DataFrame({'original': o, 'refactored': r, 'delta': (r - o).round(6)})
        cmp = cmp.sort_values('delta', key=abs, ascending=False)
        print(cmp.to_string())
    print()

print(f"{'-'*60}")
print(f"\nSUMMARY: identical metrics = "
      + str(sum(1 for col in SCORE_COLS if (orig_2024[col] - refac_2024[col]).abs().max() < THRESHOLD))
      + f" / {len(SCORE_COLS)}")
