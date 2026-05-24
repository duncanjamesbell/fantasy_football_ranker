"""
Yahoo Fantasy Selenium scrapers.

Selector constants are grouped at the top of the file so that when Yahoo
updates their HTML, there is one place to fix — not three notebooks.

All functions accept a live Selenium WebDriver and return a DataFrame.
Explicit WebDriverWait calls replace bare time.sleep() wherever possible.
"""

import os
import time
import pandas as pd
from dotenv import load_dotenv
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select, WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

load_dotenv()

YAHOO_USERNAME = os.getenv("YAHOO_USERNAME", "")
YAHOO_PASSWORD = os.getenv("YAHOO_PASSWORD", "")
YAHOO_PROFILE_ID = os.getenv("YAHOO_PROFILE_ID", "")

# ---------------------------------------------------------------------------
# Selector constants — update here when Yahoo changes their markup
# ---------------------------------------------------------------------------

# Login page
SEL_LOGIN_LABEL = (By.XPATH, "//label[@for='login-username']")
SEL_USERNAME_INPUT = (By.XPATH, "//input[@id='login-username']")
SEL_NEXT_BUTTON = (By.XPATH, "//input[@value='Next']")

# Schedule navigation
SEL_SCHEDULE_TAB = (By.XPATH, "//a[@data-target='#lhstschedtab']")
SEL_SCHEDULE_NAV = (By.XPATH, "//ul[@id='schedsubnav']")
SEL_SCHEDULE_TABLE = (By.XPATH, "//table[@class='Table Table-interactive']")

# Matchup page
SEL_MANAGER_LINKS = (By.XPATH, '//a[@class="F-link"]')
SEL_MATCHUP_TABLE = (By.XPATH, "//table[@id='statTable1']")
SEL_PLAYER_DIV_CLASS = "ysf-player-name Nowrap Relative Lh-xs"
SEL_LEFT_SCORE_CLASS = "Pend-lg Ta-end Fw-b Nowrap Va-top"
SEL_RIGHT_SCORE_CLASS = "Ta-end Fw-b Nowrap Va-top"

# Player / position page
SEL_STATUS_SELECT = (By.XPATH, "//select[@id='statusselect']")
SEL_STAT_SELECT = (By.XPATH, "//*[@id='statselect']")
SEL_SEASON_TOTAL_OPTION = (
    By.XPATH,
    "/html/body/div[1]/div[2]/div[2]/div[2]/div/div/div[2]/div[2]/section"
    "/div/div/div[3]/section[1]/div[2]/div/form/fieldset/div[2]/div[4]/select"
    "/optgroup[3]/option[1]",
)
SEL_PLAYERS_TABLE = (By.XPATH, '//*[@id="players-table"]')
SEL_PLAYER_LINK = (By.CSS_SELECTOR, "a.name.F-link")
SEL_RANK_SPANS = (By.CSS_SELECTOR, "span[class='Fw-b'")
SEL_PAGINATION = (By.XPATH, "//div[@class='pagingnav navlist']")

# FAAB / transactions page
SEL_FAAB_ROW_CELL = (By.CSS_SELECTOR, "td[class='No-pstart']")
SEL_FAAB_FAILED_BIDS = (By.CSS_SELECTOR, "div[class='Mtop-med Fz-xxs']")
SEL_FAAB_AWARDEE_CELL = (By.CSS_SELECTOR, "td[class='Ta-end']")
SEL_ADD_ROW_CELL = (By.CSS_SELECTOR, "td[class='Fill-x No-pstart']")

# Playoff bracket
SEL_BRACKET_PANES_3 = (By.XPATH, "//div[@class='Grid-u-1-3 Ta-c']")
SEL_BRACKET_PANES_2 = (By.XPATH, "//div[@class='Grid-u-1-2 Ta-c']")

WAIT_TIMEOUT = 10  # seconds for explicit waits


def _wait(driver: webdriver.Chrome, timeout: int = WAIT_TIMEOUT) -> WebDriverWait:
    return WebDriverWait(driver, timeout)


def _next_page_url(driver: webdriver.Chrome) -> str | None:
    """Return the 'Next 25' href if it exists, else None."""
    try:
        nav = driver.find_element(*SEL_PAGINATION)
        last_link = nav.find_elements(By.TAG_NAME, "a")[-1]
        if last_link.text == "Next 25":
            return last_link.get_attribute("href")
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# Authentication
# ---------------------------------------------------------------------------

def check_and_handle_login(driver: webdriver.Chrome) -> None:
    """If Yahoo presents a login form, fill it in using env credentials.

    The persistent Chrome profile usually keeps the session alive, so this
    is a safety net rather than the normal code path.
    """
    try:
        _wait(driver, 3).until(EC.presence_of_element_located(SEL_LOGIN_LABEL))
    except Exception:
        return  # not on login page

    print("Login required — submitting username (you may need to approve 2FA).")
    username_input = driver.find_element(*SEL_USERNAME_INPUT)
    username_input.send_keys(YAHOO_USERNAME)
    driver.find_element(*SEL_NEXT_BUTTON).click()


# ---------------------------------------------------------------------------
# Regular-season matchups
# ---------------------------------------------------------------------------

def _parse_matchup_page(driver: webdriver.Chrome, matchup_url: str) -> pd.DataFrame:
    left_matchup_id = matchup_url.split("mid1=")[1].split("&")[0]
    right_matchup_id = matchup_url.split("mid2=")[1]

    driver.get(matchup_url)
    _wait(driver).until(EC.presence_of_element_located(SEL_MATCHUP_TABLE))

    manager_links = driver.find_elements(*SEL_MANAGER_LINKS)
    left_manager_url_id = manager_links[0].get_attribute("href").split("/")[-1]
    right_manager_url_id = manager_links[1].get_attribute("href").split("/")[-1]

    if left_matchup_id == left_manager_url_id:
        manager_match = "left"
        opponent_id = right_manager_url_id
    else:
        manager_match = "right"
        opponent_id = left_manager_url_id

    soup = BeautifulSoup(
        driver.find_element(*SEL_MATCHUP_TABLE).get_attribute("innerHTML"),
        "html.parser",
    )

    left_players, right_players = [], []
    for i, p in enumerate(soup.find_all("div", {"class": SEL_PLAYER_DIV_CLASS})):
        try:
            name = p.find("a").text
            url = p.find("a").get("href")
            pos = p.find("span", {"class": "D-b"}).text.split(" - ")[1]
        except Exception:
            name, url, pos = "", "", ""
        (left_players if i % 2 == 0 else right_players).append((name, url, pos))

    left_scores = [s.text for s in soup.find_all("td", {"class": SEL_LEFT_SCORE_CLASS})][:-1]
    right_scores = [s.text for s in soup.find_all("td", {"class": SEL_RIGHT_SCORE_CLASS})][:-1]

    players = left_players if manager_match == "left" else right_players
    scores = left_scores if manager_match == "left" else right_scores

    df = pd.DataFrame(players, columns=["player", "player_url", "position"])
    df["score"] = scores
    df["manager_id"] = left_matchup_id
    df["opponent_id"] = opponent_id
    df["matchup_url"] = matchup_url
    return df


def scrape_regular_season_matchups(
    driver: webdriver.Chrome, league_url: str
) -> pd.DataFrame:
    """Scrape every regular-season matchup for one league season."""
    driver.get(league_url)
    check_and_handle_login(driver)

    schedule_url = driver.find_element(*SEL_SCHEDULE_TAB).get_attribute("href")
    driver.get(schedule_url)

    nav_html = driver.find_element(*SEL_SCHEDULE_NAV).get_attribute("innerHTML")
    nav_soup = BeautifulSoup(nav_html, "html.parser")
    manager_schedule_urls = [
        (li.text.strip(), "https://football.fantasysports.yahoo.com/" + li.find("a")["href"])
        for li in nav_soup.find_all("li")
    ]

    manager_matchup_urls = []
    for manager, sched_url in manager_schedule_urls:
        print(f"  Collecting matchup URLs for {manager}")
        driver.get(sched_url)
        table_html = driver.find_element(*SEL_SCHEDULE_TABLE).get_attribute("innerHTML")
        table_soup = BeautifulSoup(table_html, "html.parser")
        urls = []
        for tr in table_soup.find_all("tr"):
            for a in tr.find_all("a"):
                try:
                    href = a.get("href")
                    if "matchup" in href:
                        urls.append("https://football.fantasysports.yahoo.com/" + href)
                        break
                except Exception:
                    pass
        manager_matchup_urls.append((manager, urls))

    all_dfs = []
    for manager, urls in manager_matchup_urls:
        print(f"  Scraping matchups for {manager}")
        week_dfs = [_parse_matchup_page(driver, url) for url in urls]
        df = pd.concat(week_dfs, ignore_index=True)
        df["manager"] = manager
        all_dfs.append(df)

    result = pd.concat(all_dfs, ignore_index=True)
    result["league_url"] = league_url
    return result


# ---------------------------------------------------------------------------
# Playoff matchups
# ---------------------------------------------------------------------------

def _get_bracket_panes(driver: webdriver.Chrome) -> tuple[list, int]:
    """Return (panes, grid_index_modifier) — handles 6- and 10-team formats."""
    panes = driver.find_elements(*SEL_BRACKET_PANES_3)
    if panes:
        return panes, 0
    return driver.find_elements(*SEL_BRACKET_PANES_2), 1


def _bracket_urls(pane, css_class: str) -> list[str]:
    base = "https://football.fantasysports.yahoo.com"
    elems = pane.find_elements(By.XPATH, f"div[@class='{css_class}']")
    return [base + e.get_attribute("data-target") for e in elems]


def _parse_playoff_matchup(driver: webdriver.Chrome, matchup_url: str) -> pd.DataFrame:
    driver.get(matchup_url)
    _wait(driver).until(EC.presence_of_element_located(SEL_MATCHUP_TABLE))

    links = driver.find_elements(*SEL_MANAGER_LINKS)
    left_id = links[0].get_attribute("href").split("/")[-1]
    right_id = links[1].get_attribute("href").split("/")[-1]

    soup = BeautifulSoup(
        driver.find_element(*SEL_MATCHUP_TABLE).get_attribute("innerHTML"),
        "html.parser",
    )

    left_players, right_players = [], []
    for i, p in enumerate(soup.find_all("div", {"class": SEL_PLAYER_DIV_CLASS})):
        try:
            name = p.find("a").text
            url = p.find("a").get("href")
            pos = p.find("span", {"class": "D-b"}).text.split(" - ")[1]
        except Exception:
            name, url, pos = "", "", ""
        (left_players if i % 2 == 0 else right_players).append((name, url, pos))

    left_scores = [s.text for s in soup.find_all("td", {"class": SEL_LEFT_SCORE_CLASS})][:-1]
    right_scores = [s.text for s in soup.find_all("td", {"class": SEL_RIGHT_SCORE_CLASS})][:-1]

    def _build_df(players, scores, manager_id, opponent_id):
        df = pd.DataFrame(players, columns=["player", "player_url", "position"])
        df["score"] = scores
        df["manager_id"] = manager_id
        df["opponent_id"] = opponent_id
        df["matchup_url"] = matchup_url
        return df

    return pd.concat(
        [_build_df(left_players, left_scores, left_id, right_id),
         _build_df(right_players, right_scores, right_id, left_id)],
        ignore_index=True,
    )


def scrape_playoff_matchups(
    driver: webdriver.Chrome, league_url: str
) -> pd.DataFrame:
    """Scrape all playoff and consolation matchups for one league season."""
    driver.get(league_url)
    check_and_handle_login(driver)
    driver.execute_script("window.scrollTo(0, 700)")

    panes, mod = _get_bracket_panes(driver)

    bracket_classes = [
        ("quarterfinal", 0),
        ("semifinal", 1 - mod),
        ("place_5", 1 - mod),
        ("final", 2 - mod),
        ("place_3", 2 - mod),
    ]
    if mod == 1:
        bracket_classes = [(c, i) for c, i in bracket_classes if c != "quarterfinal"]

    playoff_urls = []
    for css_class, pane_idx in bracket_classes:
        full_class = (
            f"Linkable Bdr Bdr-radius Bg-shade Ta-start yfa-matchup bracket {css_class}"
        )
        playoff_urls.extend(_bracket_urls(panes[pane_idx], full_class))

    # Consolation bracket
    consolation_elem = driver.find_element(By.CSS_SELECTOR, "span[id='selectlist_nav']")
    consolation_elem.click()
    time.sleep(1)
    action = webdriver.ActionChains(driver)
    action.move_to_element(consolation_elem).move_by_offset(0, 75).click().perform()
    time.sleep(1)

    panes, mod = _get_bracket_panes(driver)
    consolation_urls = []
    for css_class in ["semifinal", "place_7", "place_9"]:
        full_class = (
            f"Linkable Bdr Bdr-radius Bg-shade Ta-start yfa-matchup bracket {css_class}"
        )
        pane_idx = 1 - mod if css_class == "semifinal" else 2 - mod
        panes_fresh, mod = _get_bracket_panes(driver)
        consolation_urls.extend(_bracket_urls(panes_fresh[pane_idx], full_class))

    all_dfs = []
    for url in playoff_urls + consolation_urls:
        print(f"  Scraping playoff matchup: {url}")
        all_dfs.append(_parse_playoff_matchup(driver, url))

    result = pd.concat(all_dfs, ignore_index=True)
    result["league_url"] = league_url
    return result


# ---------------------------------------------------------------------------
# Position scores
# ---------------------------------------------------------------------------

def scrape_position_scores(
    driver: webdriver.Chrome,
    league_url: str,
    positions: list[str] | None = None,
) -> pd.DataFrame:
    """Scrape season-total position scores for all players in one league season."""
    if positions is None:
        positions = ["QB", "WR", "RB", "TE", "K", "DEF"]

    player_url = league_url + "/players"
    driver.get(player_url)
    check_and_handle_login(driver)

    status_select = Select(driver.find_element(*SEL_STATUS_SELECT))
    status_select.select_by_visible_text("All Players")
    time.sleep(1)
    driver.find_element(*SEL_SEASON_TOTAL_OPTION).click()

    all_dfs = []
    for position in positions:
        print(f"  Collecting {position} players...")
        pos_label = driver.find_element(By.XPATH, f"//label[text()='{position}']")
        pos_label.click()
        time.sleep(1)

        position_pages = []
        while True:
            table = driver.find_element(*SEL_PLAYERS_TABLE)
            rows = table.find_element(By.TAG_NAME, "tbody").find_elements(By.TAG_NAME, "tr")

            names, urls, ranks = [], [], []
            for row in rows:
                try:
                    link = row.find_element(*SEL_PLAYER_LINK)
                    names.append(link.text)
                    urls.append(link.get_attribute("href"))
                except Exception:
                    names.append(row.text)
                    urls.append("URL")

            for span in driver.find_elements(*SEL_RANK_SPANS):
                try:
                    ranks.append(float(span.text))
                except Exception:
                    pass

            # Pad ranks if fewer than players (unranked players at end)
            while len(ranks) < len(names):
                ranks.append(99900 + len(ranks))

            page_df = pd.DataFrame({
                "player_name": names,
                "position": position,
                "player_url": urls,
                "score": ranks,
            })
            position_pages.append(page_df)

            next_url = _next_page_url(driver)
            if next_url:
                driver.get(next_url)
                time.sleep(1)
            else:
                break

        all_dfs.append(pd.concat(position_pages, ignore_index=True))

    return pd.concat(all_dfs, ignore_index=True)


# ---------------------------------------------------------------------------
# FAAB transactions
# ---------------------------------------------------------------------------

def _scrape_faab_bid_page(driver: webdriver.Chrome) -> pd.DataFrame:
    """Scrape one page of competitive FAAB bids (transactionsfilter=faab)."""
    rows = driver.find_elements(By.TAG_NAME, "tr")
    records = []
    for row in rows:
        try:
            player_cell = row.find_element(*SEL_FAAB_ROW_CELL)
            player_name = player_cell.find_element(By.TAG_NAME, "a").text
            player_url = player_cell.find_element(By.TAG_NAME, "a").get_attribute("href")
            position = player_cell.find_element(
                By.CSS_SELECTOR, "span[class='F-position Fz-xxs']"
            ).text.split(" - ")[1]
            faab_spend = player_cell.find_element(By.TAG_NAME, "h6").text

            failed = []
            for p in row.find_element(*SEL_FAAB_FAILED_BIDS).find_elements(By.TAG_NAME, "p"):
                mgr_link = p.find_element(By.TAG_NAME, "a")
                offer_text = p.text.split(mgr_link.text)[1].strip()
                failed.append([mgr_link.text, mgr_link.get_attribute("href"), offer_text])

            awardee_cell = row.find_element(*SEL_FAAB_AWARDEE_CELL)
            awardee_span = awardee_cell.find_element(By.CSS_SELECTOR, "span[class='Grid-u']")
            awardee = awardee_span.find_element(By.TAG_NAME, "a").text
            awardee_url = awardee_span.find_element(By.TAG_NAME, "a").get_attribute("href")
            timestamp = awardee_span.find_element(By.TAG_NAME, "span").text.replace(",", ", ")

            records.append({
                "player_name": player_name,
                "player_url": player_url,
                "position": position,
                "faab_spend": faab_spend,
                "failed_bids": failed,
                "awardee": awardee,
                "awardee_url": awardee_url,
                "award_timestamp": timestamp,
            })
        except Exception:
            continue
    return pd.DataFrame(records)


def _scrape_add_page(driver: webdriver.Chrome) -> pd.DataFrame:
    """Scrape one page of free-agent adds (transactionsfilter=add)."""
    rows = driver.find_elements(By.TAG_NAME, "tr")
    records = []
    for row in rows:
        try:
            player_cell = row.find_element(*SEL_ADD_ROW_CELL)
            player_url = player_cell.find_element(By.TAG_NAME, "a").get_attribute("href")
            player_name = player_cell.find_element(By.TAG_NAME, "a").text
            pos_text = player_cell.find_element(
                By.CSS_SELECTOR, "span[class='F-position Fz-xxs']"
            ).text
            position = pos_text.split(" - ")[1]
            waiver_details = player_cell.find_element(
                By.CSS_SELECTOR, "h6[class='F-shade Fz-xxs']"
            ).text

            mgr_link = row.find_element(
                By.CSS_SELECTOR, "span[class='Grid-u']"
            ).find_element(By.TAG_NAME, "a")
            manager_team = mgr_link.text
            manager_url = mgr_link.get_attribute("href")
            timestamp = row.find_element(
                By.CSS_SELECTOR, "span[class='Block F-timestamp Fz-xxs Nowrap']"
            ).text

            records.append({
                "player_name": player_name,
                "player_url": player_url,
                "position": position,
                "faab_spend": waiver_details,
                "failed_bids": "",
                "awardee": manager_team,
                "awardee_url": manager_url,
                "award_timestamp": timestamp,
            })
        except Exception:
            continue
    return pd.DataFrame(records)


def _paginate_scrape(driver: webdriver.Chrome, scrape_fn) -> pd.DataFrame:
    pages = []
    while True:
        time.sleep(3)
        pages.append(scrape_fn(driver))
        next_url = _next_page_url(driver)
        if next_url:
            driver.get(next_url)
        else:
            break
    return pd.concat(pages, ignore_index=True) if pages else pd.DataFrame()


def scrape_faab(driver: webdriver.Chrome, league_url: str) -> pd.DataFrame:
    """Scrape all FAAB transactions (contested bids + uncontested adds) for one season."""
    faab_url = league_url + "/transactions?transactionsfilter=faab"
    driver.get(faab_url)
    check_and_handle_login(driver)
    faab_df = _paginate_scrape(driver, _scrape_faab_bid_page)

    add_url = league_url + "/transactions?transactionsfilter=add"
    driver.get(add_url)
    adds_raw = _paginate_scrape(driver, _scrape_add_page)
    faab_adds = adds_raw[adds_raw.faab_spend.str.startswith("$")].copy()

    combined = pd.concat([faab_df, faab_adds], ignore_index=True)

    combined["faab_dollars"] = (
        combined.faab_spend.str.split().str[0].str.replace("$", "", regex=False)
    )
    combined["has_failed_bidders"] = combined.failed_bids.apply(
        lambda x: "0" if x == "" else "1"
    )
    combined["sort"] = (
        combined.player_name + combined.awardee + combined.award_timestamp + combined.faab_dollars
    )
    combined.drop_duplicates(subset=["sort"], inplace=True)
    return combined
