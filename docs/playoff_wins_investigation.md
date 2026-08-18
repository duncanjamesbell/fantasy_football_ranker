# Playoff Win Discrepancy Investigation — Working Notes

**Status as of 2026-08-17: 2020 AND 2022 both independently confirmed. A
separate rank-order bug found and fixed for 2022. Ready to commit.**

This file exists so either of us can pick this back up if a session gets lost.
It's a running log, not a finished doc — update it as the investigation continues.

## What this is about

A prior (lost) session started building logic to replace the playoff win/match
count heuristic with something derived from real scraped per-player scores.
That work was found sitting uncommitted in `metrics/composite.py` when this
session picked it up. This doc covers what was found, what was fixed, and how
the results were independently verified against Duncan's own season records.

## Background: what "playoff_wins" actually was

Important finding — **the old `playoff_wins` values were never scraped from
Yahoo's real game results.** They come from a static lookup table,
`_PLAYOFF_WINS` in `scrapers/yahoo_api.py` (~lines 20-40), keyed on
`(num_managers, final_rank, seed_bucket)`. E.g. in a 10-team league, rank 9
*always* gets credited 1 "playoff win" regardless of what actually happened.
It's a formula proxy, not ground truth.

The **only actual manual, human-verified corrections that existed before
this session** live in `data/reference/overrides.yaml` under
`playoff_wins_overrides` — 7 entries total (2009 Scott Gunter; 2020 Patrick,
Kevin, Benjamin, Scott Gunter, David Casstevens, Duncan). Both seasons are
tied to a documented co-manager account scrambling issue (see
`co_manager_dedup.row_reattributions` in the same file).

## The new logic (`_derive_real_playoff_results`, in `metrics/composite.py`)

Sums each team's per-player scraped scores per `(season, matchup_url,
manager_id)`, compares the two teams in a matchup, and counts real
wins/matches from who actually outscored whom. This replaces the rank/seed
heuristic wherever the real data looks trustworthy (see safeguard below).

**Motivating case:** 2023 champion Mark was under-credited by the old
heuristic — 2 wins vs. a real 3-0 perfect playoff run.

## Bug #1 found and fixed this session: 2020 override clobbering

The real-data derivation reads from `full_playoffs`, the *same raw scraped
source that's corrupted for 2020* (the co-manager mix-up). The original
safeguard (`real_matches >= heuristic_matches`) only protects against
undercounting from scraping gaps — it does nothing for misattributed rows.
Result: 4 of the 6 manually-verified 2020 overrides were being silently
overwritten (Benjamin 1->0, David Casstevens 2->1, Duncan 1->2, Scott Gunter
0->2). Kevin and Patrick escaped only by luck of the threshold check.

**Fix:** any `(season, manager)` with an explicit `playoff_wins_overrides`
entry is now never replaced by derived-real data, full stop.

## 2020 CONFIRMED - validated against a paper bracket (2026-08-17)

That season's playoffs were run off-site on a paper bracket. Duncan provided
the paper-bracket final standings and win counts from memory (initially
mislabeled as 2022, corrected to 2020 after the mismatch was flagged). All
10 managers matched our post-fix 2020 data exactly, both final-standing
order and win count — including the 4 non-overridden managers (Mark, Luke,
Bryan, Krista) that the fix derives independently with zero manual input.
**2020 is fully settled.**

## 2022 CONFIRMED - all 10 win counts validated by Duncan (2026-08-17)

Duncan supplied the authoritative 2022 win counts from memory (later
correcting one entry: Scott Gunter = 3 wins, not 2 — he won all three
rounds to take the championship). Final comparison, all matching exactly:

| Manager | Wins |
|---|---|
| Scott Gunter | 3 |
| Kevin | 2 |
| Patrick | 1 |
| Krista | 0 |
| David Casstevens | 1 |
| Duncan | 0 |
| Benjamin | 2 |
| Mark | 1 |
| Luke | 1 |
| Bryan | 0 |

Also checked: 2022 had a league-agreed manual points correction for a
cancelled week-17 game (projected points awarded since Yahoo didn't reflect
it) — see `p_score_overrides` entries for Scott Gunter, Patrick, Benjamin,
Luke in `overrides.yaml`. Verified the raw per-player scraped data already
contains these corrected values (summed per-game scores match each
manager's `corrected` revised_p_score exactly, not the stale `original`) —
so the win derivation was never working off outdated numbers here.

## Bug #2 found and fixed this session: 2022 rank field swapped for two pairs

While reconciling win counts, found the `rank` column in
`consolidated_master.csv` had two pairs inverted for 2022:
- Stored: Krista=3, Patrick=4. Actual: Patrick beat Krista 214.26-167.95 in
  their week-17 placement game — Patrick should be 3, Krista 4.
- Stored: Bryan=9, Luke=10. Actual: Luke beat Bryan 203.46-156.78 in their
  week-17 placement game — Luke should be 9, Bryan 10.

Total points back this up too (Patrick 407.73 >> Krista 312.13; Luke 302.66
> Bryan 282.29). Duncan independently confirmed noticing the same error.

**Fix:** added a `rank_corrections` block for 2022 in `overrides.yaml`
(same mechanism as the existing 2020 full-scramble entries, just 4 targeted
entries here instead of all 10):

```yaml
    - {season: 2022, manager: "Patrick", correct_rank: 3}
    - {season: 2022, manager: "Krista",  correct_rank: 4}
    - {season: 2022, manager: "Luke",    correct_rank: 9}
    - {season: 2022, manager: "Bryan",   correct_rank: 10}
```

Verified this doesn't perturb `heuristic_matches` for any manager that
season (checked seed-based branch conditions for all 10) and confirmed the
full pipeline (`calculate_composite_ranks`) still runs clean end-to-end with
both fixes applied together, and rank/wins for 2022 come out in the correct
order with the correct counts.

## Net result after both fixes (thru 2025 season)

5 manager-seasons changed vs. the old heuristic-lookup-table values, all
confirmed correct:

| Season | Manager | Old wins | New wins | Verified against |
|---|---|---|---|---|
| 2023 | Mark (champion) | 2 | 3 | internally consistent (no hard-copy check) |
| 2022 | Luke | 0 | 1 | Duncan's confirmed record |
| 2022 | Patrick | 0 | 1 | Duncan's confirmed record |
| 2022 | Bryan | 1 | 0 | Duncan's confirmed record |
| 2022 | Krista | 1 | 0 | Duncan's confirmed record |

Plus the 2022 rank swap fix (Patrick/Krista, Luke/Bryan) — not a
playoff_wins change, but a `rank` column correction found along the way.

2020 shows no net change from the existing manual overrides — now
independently confirmed correct by the paper bracket.

**2023 Mark is the one remaining item without independent verification** —
still just "internally consistent real-score derivation," same evidentiary
level 2022 was at before Duncan's confirmation. No action needed unless a
hard-copy record for 2023 turns up.

## Current repo state (uncommitted, ready to commit)

```
 M composite_ranks.ipynb        (unrelated: always load latest-year data
                                  files instead of year-specific thru_{year}
                                  snapshots, capped by THRU_YEAR)
 M metrics/composite.py         (real-playoff-derivation logic + the
                                  override-precedence fix for 2020)
 M data/reference/overrides.yaml (new 2022 rank_corrections entries)
?? docs/playoff_wins_investigation.md (this file)
```

Nothing has been committed yet.

## Next steps

1. Commit `metrics/composite.py`, `composite_ranks.ipynb`,
   `data/reference/overrides.yaml`, and this doc.
2. Add a CHANGELOG.md entry documenting both fixes — the 2020 and 2022
   confirmations are strong supporting evidence, worth including.
3. No outstanding open items for 2020 or 2022. 2023's champion fix (Mark)
   remains unverified against any external record but has no reason to be
   doubted absent new information.
