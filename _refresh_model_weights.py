"""
_refresh_model_weights.py

Reproduces the original model-derived weight methodology (see
pre_fantasy_pycaret.ipynb, root) on the refreshed dataset
(before_claude/transformed_pre_fantasy_data_refreshed.csv), which covers
2007-2025 using the current, corrected data pipeline instead of the stale
2007-2022 file.

Methodology (unchanged from the original notebook):
  - Split the 9 predictor metrics into 3 buckets: manager-controlled,
    win-percentages, points-against.
  - For each bucket, fit two regression models (Linear Regression and
    Bayesian Ridge, both tuned via pycaret's tune_model) predicting
    season_rank (fraction: rank / league_size, lower = better).
  - Average the absolute value of each feature's coefficient across the
    two models -> that bucket's raw "model weight" dict.
  - faab_efficiency is negated (faab_efficiency_inv) before fitting so its
    coefficient sign matches the other "higher raw metric = better" features.

Run: py _refresh_model_weights.py
"""
import warnings
warnings.filterwarnings('ignore')

import pandas as pd
from pycaret.regression import setup, create_model, tune_model, pull

data = pd.read_csv('before_claude/transformed_pre_fantasy_data_refreshed.csv')
data.set_index(['manager', 'season'], inplace=True)
data['faab_efficiency_inv'] = data['faab_efficiency'] * -1

BUCKETS = {
    'manager_controlled': ['rs_points', 'playoff_points', 'draft_efficiency',
                            'undrafted_savvy', 'faab_efficiency_inv'],
    'win_percentages':    ['avg_rs_win_percent', 'playoff_win_percentage'],
    'points_against':     ['rs_points_against', 'playoff_points_against'],
}

results = {}
for bucket_name, features in BUCKETS.items():
    print(f'\n{"="*70}\nBUCKET: {bucket_name}  features={features}\n{"="*70}')
    cols = features + ['season_rank']
    bucket_data = data[cols]

    setup(bucket_data, target='season_rank', session_id=42, verbose=False)

    lr = create_model('lr', verbose=False)
    tuned_lr = tune_model(lr, n_iter=100, early_stopping=True, verbose=False)
    lr_metrics = pull()

    br = create_model('br', verbose=False)
    tuned_br = tune_model(br, n_iter=100, early_stopping=True, verbose=False)
    br_metrics = pull()

    lr_coefs = dict(zip(features, tuned_lr.coef_))
    br_coefs = dict(zip(features, tuned_br.coef_))

    print(f'  lr  coefs: { {k: round(v,4) for k,v in lr_coefs.items()} }')
    print(f'  br  coefs: { {k: round(v,4) for k,v in br_coefs.items()} }')
    print(f'  lr  CV R2 (mean row of fold results): see lr_metrics tail')
    print(lr_metrics.tail(3)[['R2']] if 'R2' in lr_metrics.columns else lr_metrics.tail(3))
    print(br_metrics.tail(3)[['R2']] if 'R2' in br_metrics.columns else br_metrics.tail(3))

    avg_abs = {}
    for f in features:
        # rename faab_efficiency_inv back to faab_efficiency for weight reporting
        key = 'faab_efficiency' if f == 'faab_efficiency_inv' else f
        avg_abs[key] = (abs(lr_coefs[f]) + abs(br_coefs[f])) / 2

    results[bucket_name] = avg_abs
    print(f'  --> averaged |coef| weights: { {k: round(v,4) for k,v in avg_abs.items()} }')

print(f'\n{"="*70}\nFINAL RAW MODEL WEIGHTS (avg |coef| across lr + tuned br)\n{"="*70}')
for bucket, weights in results.items():
    print(f'{bucket}:')
    for k, v in weights.items():
        print(f'    {k!r}: {round(v, 3)},')

import json
with open('_refreshed_model_weights.json', 'w') as f:
    json.dump(results, f, indent=2)
print('\nSaved to _refreshed_model_weights.json')
