"""
Static methodology text for the Methodology tab. Merges:
- Metric-by-metric prose from before_claude/PRE_Fantasy_Football_Composite_Ranks_googlecolab.ipynb
- Scoring-math sections from docs/composite_ranking.md
- The cascade-vs-capped_linear contrast from metrics/composite.py's own docstrings
No dynamic content -- this is presentation copy, not computation.
"""

OVERVIEW = """
## PRE Composite Fantasy Football Ranks

This app calculates overall composite ranks for our fantasy football group across 10 metrics
covering regular season performance, playoff performance, and player management. Adjust the
controls in the sidebar to explore how different weightings and scoring methods change the picture.
"""

METRICS = """
### Metrics

**Regular season performance**

- **`rs_win_percentage`** -- percent of wins out of total regular season matchups.
- **`rs_points`** -- our most important metric: how many points you scored during the regular
  season. Normalized with a z-score to control for scoring-scheme variance between seasons.
- **`rs_points_against`** -- how many points were scored *against* you. This is a deliberate
  luck adjustment, not a defense-quality metric: a **higher**-than-average points against is
  rewarded (evidence of a tougher draw despite a good record), a **lower**-than-average points
  against is penalized (evidence of an easy draw/good luck inflating the record).

**Playoff performance**

- **`playoff_win_percentage`** -- like its regular season sibling, a simple win percentage out
  of overall playoff matches.
- **`playoff_points`** -- average points scored during playoffs, regardless of bracket. An
  average is used because of the uneven number of playoff matches between managers (bye weeks).
- **`playoff_points_against`** -- the playoff counterpart to `rs_points_against`, same
  luck-adjustment logic.

**Player management**

- **`draft_efficiency`** -- how efficient you are with draft dollars, based on the disparity
  between draft price and the drafted player's ultimate season rank at their position.
- **`faab_efficiency`** -- how efficient you are with FAAB dollars. Unlike draft efficiency,
  this doesn't look at player performance at all -- only the disparity between what you paid and
  the next-highest bid. Credits accurate assessment of player value and reading the league.
- **`undrafted_savvy`** -- how skilled you are at in-season pickups. The sibling of draft
  efficiency, crediting only undrafted (and started) player performance -- rewards managers who
  find value on waivers, free agency, and trades.

**Overall performance**

- **`season_rank`** -- a weighted average of all season finishes, weighted so higher ranks count
  more heavily (e.g. a 1st place finish in a 10-team league is worth 20; a 6th place finish is
  worth 6).
"""

SCORING_METHODS = """
### Scoring methods

Two different ways to convert a manager's underlying performance on a metric into points toward
`total_score`. Both use the same underlying z-scores and weights -- they differ only in how a
z-score gets converted into a score.

**Cascade (the original method)** -- bounded `[0, weight]`, asymmetric. Managers are sorted by
metric value; the top performer claims the *full* weight regardless of margin, and each
subsequent manager's score is the previous manager's score reduced by a percentage (the size of
the gap to them, as a share of the total spread across the whole population):

```
Sort all managers by metric value (best first).
score[0] = full weight
score[i] = score[i-1] * (1 - gap_i / total_gaps)   for i > 0
```

The practical effect: good performance is rewarded on a steep curve concentrated at the top, and
even the worst performer in the league keeps a substantial floor -- nobody can score below zero
on a single metric, and being merely average nets a nontrivial chunk of the weight.

**Capped linear (symmetric alternative)** -- bounded `[-weight, weight]`, symmetric around the
population mean:

```
z = (value - population_mean) / population_stdev
z_capped = clip(z, -cap, cap)
score = (z_capped / cap) * weight
```

An average performer scores 0. Above-average performance is rewarded and below-average
performance is *penalized* -- genuinely subtracting from `total_score`, not just failing to add
to it. The cap (adjustable in the sidebar, default 2.0 standard deviations) prevents any single
outlier season from claiming more than a metric's full weight, and controls how much separation
there is between managers: a lower cap saturates faster (moderate over/under-performance already
reaches close to the full weight), a higher cap requires more extreme performance to reach the
edges and compresses everyone closer to the middle.

Because capped-linear scores can go negative, a `score_offset` (default +50) is added to
`total_score` only -- individual metric scores are left alone -- purely so totals stay positive
and readable. A perfectly average manager lands at exactly the offset value on a familiar
"score out of 100"-style scale.
"""

WEIGHTS = """
### Metric weights

How the metrics are *weighted* relative to each other is arguably more important than how each
one is calculated individually. The default weights (used in "Manual per-metric weights" mode)
reflect one person's judgment call, not an objective truth -- that's exactly why the sidebar lets
you change them and see how the rankings shift.

"Model-derived buckets" mode takes a different approach: past performance was used as training
data for a regression model predicting `season_rank`, and the resulting feature weights were
averaged to get a data-driven starting point. A few caveats worth knowing:

1. `season_rank` was the model's *target*, so it isn't included in the model's own feature
   weights -- it still has to be set manually (the "Season rank weight" slider).
2. Metrics are split into three buckets -- **manager-controlled** (`rs_points`,
   `draft_efficiency`, `undrafted_savvy`, `playoff_points`, `faab_efficiency`), **win
   percentages** (`rs_win_percentage`, `playoff_win_percentage`), and **points against**
   (`rs_points_against`, `playoff_points_against`) -- because an unconstrained model
   over-emphasized win percentages and playoff performance relative to what feels right for
   regular-season performance. You control each bucket's overall share with the three bucket
   sliders.
3. Using a model to set the weights is philosophically a little off to begin with: composite
   ranks are meant to answer "who was the best," not "whose final rank is most predictable" --
   though the two questions are closely related.

The model weights are still a useful, non-arbitrary reference point even with these caveats --
they just aren't gospel.
"""

DATA_NOTES = """
### Data notes

- Season z-scores are computed from the set of managers active that season, *after* the
  corrections in `overrides.yaml` are applied (co-manager account mix-ups, invalid rows, known
  scraping errors) -- see `docs/composite_ranking.md` for the full correction pipeline.
- Seasons within the trailing "Recency window" (Advanced settings) get a bonus applied to their
  z-score before being folded into a manager's career average, so recent play counts for more
  than a decade-old season.
- Managers who only have a single season of data (currently Mark+David and Waidmann, both 2025
  only) show up as a single dot rather than a line on the Trends tab -- there's no second point
  to draw a line to.
"""


def full_methodology_markdown() -> str:
    return "\n---\n".join([OVERVIEW, METRICS, SCORING_METHODS, WEIGHTS, DATA_NOTES])
