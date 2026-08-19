"""
_compare_scoring_methods.py

Compare the 'cascade' (original, production default) and 'capped_linear'
(symmetric, outlier-bounded) scoring methods in metrics/composite.py,
metric by metric and manager by manager.

Cascade: bounded [0, weight], asymmetric -- rank #1 always claims the full
metric weight regardless of margin, and even the worst performer keeps a
substantial floor well above zero.

Capped_linear: bounded [-weight, weight], symmetric around the population
mean -- an average performer scores 0, above/below average is rewarded/
penalized symmetrically, and a `capped_linear_cap`-SD cap keeps any single
outlier from running away with more than the metric's full weight.

Run with: py _compare_scoring_methods.py
Or to compare cascade vs. a specific cap: py _compare_scoring_methods.py --cap 2.5
Or to see how spread/floor/ceiling shift across caps: py _compare_scoring_methods.py --cap 1.5 2.0 2.5 3.0
"""

import argparse

import pandas as pd

from config import (
    CONSOLIDATED_MASTER_PATH, OVERRIDES_PATH, DRAFT_DF_PATH,
    rs_matchups_path, playoffs_path, faab_path, SEASONS,
)
from metrics.composite import calculate_composite_ranks, load_overrides

THRU_YEAR = 2025
LATEST_YEAR = max(SEASONS)
CAPPED_LINEAR_CAP = 2.0
SCORE_OFFSET = 50.0  # applied to capped_linear only, keeps totals positive

# Core league members -- excludes single-season, non-core participants
# (currently Ryan 2007, Stuart 2009) from the reported leaderboard. Their
# underlying stats still count toward the season means/stdevs for whichever
# years they played, so they still influence core members' z-scores those
# seasons -- they just never get their own career average computed or shown.
CORE_MEMBERS = [
    'Duncan', 'Patrick', 'Mark', 'Scott Gunter', 'Krista', 'Kevin', 'Luke',
    'Bryan', 'David Casstevens', 'Benjamin', 'Mark+David', 'Waidmann',
]

SCORE_COLS = [
    'rs_win_percent_score', 'rs_points_score', 'rs_points_against_score',
    'p_win_percent_score', 'p_points_score', 'p_points_against_score',
    'weighted_rank_score', 'draft_efficiency_score', 'undrafted_savvy_score',
    'faab_efficiency_score', 'total_score',
]


def load_data():
    master = pd.read_csv(CONSOLIDATED_MASTER_PATH)
    full_rs = pd.read_csv(rs_matchups_path(LATEST_YEAR))
    full_draft = pd.read_csv(DRAFT_DF_PATH)
    full_faab = pd.read_csv(faab_path(LATEST_YEAR))
    full_playoffs = pd.read_csv(playoffs_path(LATEST_YEAR))
    overrides = load_overrides(OVERRIDES_PATH)
    return master, full_rs, full_draft, full_faab, full_playoffs, overrides


def run(score_method: str, score_offset: float = 0.0, pre_managers=None, cap: float = CAPPED_LINEAR_CAP) -> pd.DataFrame:
    master, full_rs, full_draft, full_faab, full_playoffs, overrides = load_data()
    result, _ = calculate_composite_ranks(
        master, full_rs, full_draft, full_faab, full_playoffs, THRU_YEAR,
        overrides=overrides, pre_managers=pre_managers or CORE_MEMBERS,
        score_method=score_method, capped_linear_cap=cap,
        score_offset=score_offset,
    )
    return result[result['thru'] == THRU_YEAR]


def compare(pre_managers=None, cap: float = CAPPED_LINEAR_CAP):
    """Returns (per_metric_detail_df, leaderboard_df) for cascade vs. capped_linear at one cap value."""
    print("Running cascade (current production method)...")
    old = run('cascade', pre_managers=pre_managers)
    print(f"Running capped_linear (cap={cap})...")
    new = run('capped_linear', score_offset=SCORE_OFFSET, pre_managers=pre_managers, cap=cap)

    rows = []
    for manager in old.index:
        for col in SCORE_COLS:
            old_v = old.loc[manager, col]
            new_v = new.loc[manager, col]
            rows.append({
                'manager': manager, 'metric': col,
                'old_score': old_v, 'new_score': new_v, 'delta': new_v - old_v,
            })
    detail = pd.DataFrame(rows)

    old_rank = old['total_score'].rank(ascending=False).astype(int)
    new_rank = new['total_score'].rank(ascending=False).astype(int)
    leaderboard = pd.DataFrame({
        'old_rank': old_rank, 'old_total': old['total_score'],
        'new_rank': new_rank, 'new_total': new['total_score'],
    }).sort_values('old_rank')
    leaderboard['rank_change'] = leaderboard['old_rank'] - leaderboard['new_rank']

    return detail, leaderboard


def cap_sensitivity(caps: list[float], pre_managers=None) -> pd.DataFrame:
    """
    total_score (capped_linear, with SCORE_OFFSET applied) for each manager
    at each cap value in `caps`, one column per cap. A lower cap saturates
    faster (moderate over/under-performance already reaches close to a
    metric's full weight) and widens the spread; a higher cap requires more
    extreme z-scores to reach full weight, compressing everyone toward the
    middle. Rank order is typically stable across caps -- the cap changes
    magnitude of separation, not who beats whom.
    """
    totals = {}
    for cap in caps:
        result = run('capped_linear', score_offset=SCORE_OFFSET, pre_managers=pre_managers, cap=cap)
        totals[f'cap={cap}'] = result['total_score']
    return pd.DataFrame(totals)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        '--cap', type=float, nargs='+', default=[CAPPED_LINEAR_CAP],
        help=(
            f'capped_linear_cap value(s) in standard deviations (default: {CAPPED_LINEAR_CAP}). '
            'Pass one value to run the full cascade-vs-capped_linear comparison at that cap. '
            'Pass multiple values (e.g. --cap 1.5 2.0 2.5 3.0) to instead see how total_score, '
            'rank order, and spread shift across caps -- no cascade comparison in that mode.'
        ),
    )
    args = parser.parse_args()
    pd.set_option('display.width', 200)

    if len(args.cap) == 1:
        cap = args.cap[0]
        detail, leaderboard = compare(cap=cap)

        print(f"\n=== Leaderboard: cascade vs capped_linear (cap={cap}, offset=+{SCORE_OFFSET:.0f}) ===")
        print(leaderboard.to_string())

        print("\n=== Per-metric score delta (new - old), pivoted by manager ===")
        pivot = detail.pivot(index='manager', columns='metric', values='delta')
        pivot = pivot.reindex(index=leaderboard.index)  # keep old-rank order
        print(pivot.to_string())

        detail.to_csv('scoring_method_comparison.csv', index=False)
        print("\nFull per-metric detail saved to scoring_method_comparison.csv")
    else:
        totals_df = cap_sensitivity(args.cap)
        sort_col = f'cap={args.cap[0]}'
        totals_df = totals_df.sort_values(sort_col, ascending=False)

        print(f"\n=== total_score (capped_linear, offset=+{SCORE_OFFSET:.0f}) by cap ===")
        print(totals_df.to_string())

        print("\n=== Rank order by cap ===")
        print(totals_df.rank(ascending=False).astype(int).to_string())

        print("\n=== Spread across managers, by cap ===")
        for col in totals_df.columns:
            lo, hi = totals_df[col].min(), totals_df[col].max()
            print(f"  {col}: min={lo:.2f}  max={hi:.2f}  range={hi - lo:.2f}")

        totals_df.to_csv('cap_sensitivity_comparison.csv')
        print("\nFull detail saved to cap_sensitivity_comparison.csv")
