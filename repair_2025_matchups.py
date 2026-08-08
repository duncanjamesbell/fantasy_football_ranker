"""
Re-scrape the 2025 RS matchup checkpoint with the fixed position selector.

Safe to re-run: already-collected URLs are skipped. Prints COMPLETE when
all 140 are done, INCOMPLETE with a re-run instruction if any failed.

Run with: py repair_2025_matchups.py
"""
import os
import pandas as pd
from config import LEAGUE_URLS
from scrapers.driver import get_driver, quit_driver
from scrapers.yahoo_selenium import _parse_matchup_page, check_and_handle_login

CHECKPOINT = "data/raw/2025_pre_matchups.csv"
URL_LIST   = "data/raw/2025_matchup_url_list.csv"   # persists across re-runs
YEAR = 2025

# ---------------------------------------------------------------------------
# Step 1 — Build or load the target URL list
# ---------------------------------------------------------------------------
if not os.path.exists(URL_LIST):
    old = pd.read_csv(CHECKPOINT)
    meta = (
        old[["matchup_url", "manager", "league_url"]]
        .drop_duplicates("matchup_url")
        .reset_index(drop=True)
    )
    meta.to_csv(URL_LIST, index=False)
    print(f"Saved {len(meta)} target URLs → {URL_LIST}")
    # Remove the old (bad) checkpoint so we start fresh.
    os.remove(CHECKPOINT)
    print(f"Cleared old checkpoint — starting fresh.")
else:
    meta = pd.read_csv(URL_LIST)
    print(f"Loaded {len(meta)} target URLs from {URL_LIST}")

total = len(meta)

# ---------------------------------------------------------------------------
# Step 2 — Find URLs already successfully collected
# ---------------------------------------------------------------------------
done_urls: set[str] = set()
if os.path.exists(CHECKPOINT):
    ck = pd.read_csv(CHECKPOINT)
    for url, grp in ck.groupby("matchup_url"):
        # A URL is "done" when it has full roster data (>= 5 rows with positions)
        if len(grp) >= 5 and grp["position"].notna().sum() >= 5:
            done_urls.add(url)

pending = meta[~meta["matchup_url"].isin(done_urls)].reset_index(drop=True)
n_already = len(done_urls)
print(f"Already collected: {n_already}/{total}  |  Pending: {len(pending)}")

if pending.empty:
    print(f"\nCOMPLETE: all {total} matchup URLs collected.")
    print("Run next: py pipeline.py --year 2025 --steps scrape")
    raise SystemExit(0)

# ---------------------------------------------------------------------------
# Step 3 — Scrape pending URLs, appending to checkpoint as we go
# ---------------------------------------------------------------------------
driver = get_driver()
n_ok = n_already
n_failed = 0
try:
    driver.get(LEAGUE_URLS[YEAR])
    check_and_handle_login(driver)

    for i, row in pending.iterrows():
        url = row["matchup_url"]
        try:
            df = _parse_matchup_page(driver, url)
            df["manager"]    = row["manager"]
            df["league_url"] = row["league_url"]
            write_header = not os.path.exists(CHECKPOINT)
            df.to_csv(CHECKPOINT, mode="a", header=write_header, index=False)
            n_ok += 1
            print(f"  [{n_ok}/{total}] OK   {url.split('?')[1]}")
        except Exception as exc:
            n_failed += 1
            print(f"  [FAIL]  {url.split('?')[1]}: {exc!s:.100}")
finally:
    quit_driver(driver)

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
print(f"\n── Repair summary ───────────────────────────────────────")
if n_failed == 0:
    print(f"COMPLETE: {n_ok}/{total} URLs collected — no failures.")
    print("Run next: py pipeline.py --year 2025 --steps scrape")
else:
    print(f"INCOMPLETE: {n_ok}/{total} collected, {n_failed} failed (rate limit).")
    print("Re-run this script to fill in the gaps:")
    print("  py repair_2025_matchups.py")
print(f"────────────────────────────────────────────────────────")
