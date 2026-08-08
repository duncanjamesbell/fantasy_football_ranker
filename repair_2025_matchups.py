"""
Re-scrape the 2025 RS matchup checkpoint with the fixed position selector.

The original checkpoint only captured DEF + team-total rows because span.D-b
was empty in the 2025 Yahoo UI. The fixed _parse_matchup_page now reads
positions from the center roster-slot <td> instead.

Run with: py repair_2025_matchups.py
"""
import pandas as pd
from config import LEAGUE_URLS
from scrapers.driver import get_driver, quit_driver
from scrapers.yahoo_selenium import _parse_matchup_page, check_and_handle_login

CHECKPOINT = "data/raw/2025_pre_matchups.csv"
YEAR = 2025

old = pd.read_csv(CHECKPOINT)
# One row per unique URL — preserves manager name and league_url metadata.
meta = (
    old[["matchup_url", "manager", "league_url"]]
    .drop_duplicates(subset=["matchup_url"])
    .reset_index(drop=True)
)
print(f"Re-scraping {len(meta)} matchup URLs...")

driver = get_driver()
try:
    driver.get(LEAGUE_URLS[YEAR])
    check_and_handle_login(driver)

    new_rows = []
    for i, row in meta.iterrows():
        url = row["matchup_url"]
        try:
            df = _parse_matchup_page(driver, url)
            df["manager"] = row["manager"]
            df["league_url"] = row["league_url"]
            new_rows.append(df)
            print(f"  [{i+1}/{len(meta)}] OK  {url.split('?')[1]}")
        except Exception as exc:
            print(f"  [{i+1}/{len(meta)}] FAIL {url.split('?')[1]}: {exc!s:.100}")
finally:
    quit_driver(driver)

if new_rows:
    combined = pd.concat(new_rows, ignore_index=True)
    combined.to_csv(CHECKPOINT, index=False)
    print(f"\nSaved {len(combined)} rows → {CHECKPOINT}")
    print("Position counts:")
    print(combined["position"].value_counts(dropna=False))
else:
    print("No rows scraped — checkpoint unchanged.")
