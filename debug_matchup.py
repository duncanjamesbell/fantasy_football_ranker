"""
Diagnostic script: load one 2025 matchup page and save its HTML for selector inspection.
Run with: py debug_matchup.py
"""
import time
from bs4 import BeautifulSoup
from scrapers.driver import get_driver, quit_driver
from scrapers.yahoo_selenium import check_and_handle_login, _wait, SEL_MATCHUP_TABLE
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC

MATCHUP_URL = "https://football.fantasysports.yahoo.com/2025/f1/532435/matchup?week=1&mid1=1&mid2=7"
OLD_PLAYER_CLASS = "ysf-player-name Nowrap Relative Lh-xs"

driver = get_driver()
try:
    driver.get(MATCHUP_URL)
    check_and_handle_login(driver)

    # Wait for the matchup table
    try:
        _wait(driver, timeout=20).until(EC.presence_of_element_located(SEL_MATCHUP_TABLE))
        print("statTable1 found!")
        table_elem = driver.find_element(*SEL_MATCHUP_TABLE)
        table_html = table_elem.get_attribute("innerHTML")
    except Exception as e:
        print(f"statTable1 NOT found: {e}")
        print("Saving full page source instead...")
        table_html = driver.page_source

    # Save raw HTML for inspection
    with open("matchup_debug_table.html", "w", encoding="utf-8") as f:
        f.write(table_html)
    print("Saved matchup_debug_table.html")

    # Report all div classes found in the table
    soup = BeautifulSoup(table_html, "html.parser")

    print(f"\nDivs with OLD class '{OLD_PLAYER_CLASS}':")
    old_divs = soup.find_all("div", {"class": OLD_PLAYER_CLASS})
    print(f"  Count: {len(old_divs)}")
    for d in old_divs[:3]:
        print(f"  {d!s:.200}")

    print("\nAll unique div class strings found in table:")
    seen = set()
    for d in soup.find_all("div"):
        cls = d.get("class")
        if cls:
            key = " ".join(cls)
            if key not in seen and ("player" in key.lower() or "ysf" in key.lower() or "name" in key.lower()):
                seen.add(key)
                print(f"  {key!r}")

    print("\nAll <tr> rows in table (first 5 with player-like content):")
    count = 0
    for tr in soup.find_all("tr"):
        text = tr.get_text(separator="|", strip=True)
        if text and len(text) > 10:
            print(f"  {text[:200]}")
            count += 1
            if count >= 5:
                break

finally:
    quit_driver(driver)
