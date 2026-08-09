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
from selenium.common.exceptions import TimeoutException

load_dotenv()

_YAHOO_BASE = "https://football.fantasysports.yahoo.com"

def _abs_url(href: str) -> str:
    """Convert a Yahoo relative href to an absolute URL without double-slashes."""
    return _YAHOO_BASE + "/" + href.lstrip("/")


def _norm_url(url: str) -> str:
    """Normalise a matchup URL so single- and double-slash variants match."""
    return url.replace(_YAHOO_BASE + "//", _YAHOO_BASE + "/")


def _atomic_to_csv(df: pd.DataFrame, path: str) -> None:
    """Write df to path via a temp file + os.replace, so a killed/crashed
    process leaves the previous checkpoint intact instead of a zero-filled file."""
    tmp_path = f"{path}.tmp"
    df.to_csv(tmp_path, index=False)
    os.replace(tmp_path, path)


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
# Center roster-slot column (new in ~2025; was inside span.D-b in earlier seasons)
SEL_POS_TD_CLASS = "Va-top Bg-shade F-shade Bdrstart Bdrend Ta-c"

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

# Standings page — no fixed selectors needed; scrape_standings() uses
# BeautifulSoup to locate the W/L table dynamically.

WAIT_TIMEOUT = 20  # seconds for explicit waits


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

    # Positions: new (2025+) format stores them in a center <td>; older seasons
    # kept them inside span.D-b inside the player div.  Build a list of positions
    # indexed by row so both formats work.
    pos_tds = [
        td.get_text(strip=True)
        for td in soup.find_all("td", {"class": SEL_POS_TD_CLASS})
        if td.get_text(strip=True) not in ("TOTAL", "")
    ]

    left_players, right_players = [], []
    for i, p in enumerate(soup.find_all("div", {"class": SEL_PLAYER_DIV_CLASS})):
        try:
            name = p.find("a").text
            url = p.find("a").get("href")
        except Exception:
            name, url = "", ""

        # Row index: two player divs per row (left at even i, right at odd i).
        row_idx = i // 2
        if pos_tds and row_idx < len(pos_tds):
            pos = pos_tds[row_idx]
        else:
            try:
                pos = p.find("span", {"class": "D-b"}).text.split(" - ")[1]
            except Exception:
                pos = ""

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
    driver: webdriver.Chrome,
    league_url: str,
    checkpoint_path: str | None = None,
) -> pd.DataFrame:
    """Scrape every regular-season matchup for one league season.

    If checkpoint_path is given, already-scraped matchup URLs are loaded from
    that file and skipped.  Each newly-scraped matchup is appended to the file
    immediately so progress survives a mid-run rate-limit or crash.
    """
    done_urls: set[str] = set()
    if checkpoint_path and os.path.exists(checkpoint_path):
        existing = pd.read_csv(checkpoint_path)
        # Normalise stored URLs so old double-slash entries match current single-slash ones.
        existing["matchup_url"] = existing["matchup_url"].apply(
            lambda u: _norm_url(u) if isinstance(u, str) else u
        )
        existing.drop_duplicates(subset=["matchup_url", "manager_id", "player", "position"], inplace=True)
        _atomic_to_csv(existing, checkpoint_path)
        done_urls = set(existing["matchup_url"].dropna())
        print(f"  Resuming: {len(done_urls)} matchup URLs already in checkpoint.")

    driver.get(league_url)
    check_and_handle_login(driver)
    try:
        tab = _wait(driver).until(EC.presence_of_element_located(SEL_SCHEDULE_TAB))
        tab.click()
        _wait(driver).until(EC.presence_of_element_located(SEL_SCHEDULE_NAV))
    except TimeoutException:
        if done_urls:
            print(
                "  WARNING: Schedule nav not found (completed season layout?). "
                f"Returning {len(done_urls)} URLs already in checkpoint."
            )
            if checkpoint_path and os.path.exists(checkpoint_path):
                return pd.read_csv(checkpoint_path), 0
            raise RuntimeError("checkpoint_path required — pass rs_out.")
        raise

    nav_html = driver.find_element(*SEL_SCHEDULE_NAV).get_attribute("innerHTML")
    nav_soup = BeautifulSoup(nav_html, "html.parser")
    manager_schedule_urls = [
        (li.text.strip(), _abs_url(li.find("a")["href"]))
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
                        urls.append(_abs_url(href))
                        break
                except Exception:
                    pass
        manager_matchup_urls.append((manager, urls))

    all_urls = [(m, u) for m, urls in manager_matchup_urls for u in urls]
    all_url_set = {u for _, u in all_urls}
    total = len(all_url_set)

    n_failed = 0
    any_new = False
    for manager, urls in manager_matchup_urls:
        pending = [u for u in urls if u not in done_urls]
        if not pending:
            print(f"  {manager}: all matchups already collected — skipping.")
            continue
        print(f"  Scraping matchups for {manager} ({len(pending)} of {len(urls)} remaining)")
        for url in pending:
            try:
                df = _parse_matchup_page(driver, url)
                df["manager"] = manager
                df["league_url"] = league_url
                if checkpoint_path:
                    write_header = not os.path.exists(checkpoint_path)
                    df.to_csv(checkpoint_path, mode="a", header=write_header, index=False)
                done_urls.add(url)
                any_new = True
            except Exception as exc:
                print(f"  WARNING: failed to parse {url} ({exc!s:.120}) — skipping week.")
                n_failed += 1

    collected = len(all_url_set & done_urls)
    missing = total - collected
    if missing == 0:
        print(f"  RS matchups COMPLETE: {collected}/{total} URLs collected.")
    else:
        print(f"  RS matchups INCOMPLETE: {collected}/{total} collected, {missing} still missing — re-run to resume.")

    if checkpoint_path and os.path.exists(checkpoint_path):
        return pd.read_csv(checkpoint_path), n_failed

    if not any_new:
        raise ValueError("No regular-season matchup data was collected. Check authentication and page selectors.")
    raise RuntimeError("checkpoint_path required when not all data fits in memory — pass rs_out.")


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
    elems = pane.find_elements(By.XPATH, f".//div[@class='{css_class}']")
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

    pos_tds = [
        td.get_text(strip=True)
        for td in soup.find_all("td", {"class": SEL_POS_TD_CLASS})
        if td.get_text(strip=True) not in ("TOTAL", "")
    ]

    left_players, right_players = [], []
    for i, p in enumerate(soup.find_all("div", {"class": SEL_PLAYER_DIV_CLASS})):
        try:
            name = p.find("a").text
            url = p.find("a").get("href")
        except Exception:
            name, url = "", ""

        row_idx = i // 2
        if pos_tds and row_idx < len(pos_tds):
            pos = pos_tds[row_idx]
        else:
            try:
                pos = p.find("span", {"class": "D-b"}).text.split(" - ")[1]
            except Exception:
                pos = ""

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
    driver: webdriver.Chrome,
    league_url: str,
    checkpoint_path: str | None = None,
) -> pd.DataFrame:
    """Scrape all playoff and consolation matchups for one league season.

    If checkpoint_path is given, already-scraped matchup URLs are skipped and
    each new matchup is appended to the file immediately.
    """
    done_urls: set[str] = set()
    if checkpoint_path and os.path.exists(checkpoint_path):
        existing = pd.read_csv(checkpoint_path)
        existing["matchup_url"] = existing["matchup_url"].apply(
            lambda u: _norm_url(u) if isinstance(u, str) else u
        )
        existing.drop_duplicates(subset=["matchup_url", "manager_id", "player", "position"], inplace=True)
        _atomic_to_csv(existing, checkpoint_path)
        done_urls = set(existing["matchup_url"].dropna())
        print(f"  Resuming: {len(done_urls)} playoff matchup URLs already in checkpoint.")

    driver.get(league_url)
    check_and_handle_login(driver)
    driver.execute_script("window.scrollTo(0, 700)")
    time.sleep(2)

    panes, mod = _get_bracket_panes(driver)
    if not panes:
        raise ValueError(
            "No playoff bracket panes found on the league home page. "
            "The bracket section may not have rendered — check that the season "
            "is complete and that the page loaded correctly."
        )

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

    # Consolation bracket — may not exist if season is still in progress
    consolation_urls = []
    try:
        consolation_elem = driver.find_element(By.CSS_SELECTOR, "span[id='selectlist_nav']")
        consolation_elem.click()
        time.sleep(1)
        action = webdriver.ActionChains(driver)
        action.move_to_element(consolation_elem).move_by_offset(0, 75).click().perform()
        time.sleep(1)

        panes_fresh, mod = _get_bracket_panes(driver)
        for css_class in ["semifinal", "place_7", "place_9"]:
            full_class = (
                f"Linkable Bdr Bdr-radius Bg-shade Ta-start yfa-matchup bracket {css_class}"
            )
            pane_idx = 1 - mod if css_class == "semifinal" else 2 - mod
            consolation_urls.extend(_bracket_urls(panes_fresh[pane_idx], full_class))
    except Exception as exc:
        print(f"  WARNING: consolation bracket navigation failed ({exc!s:.120}) — skipping.")

    all_urls = playoff_urls + consolation_urls
    total = len(all_urls)
    pending = [u for u in all_urls if u not in done_urls]
    if done_urls:
        print(f"  {len(all_urls) - len(pending)} playoff URLs already collected, {len(pending)} remaining.")

    n_failed = 0
    any_new = False
    for url in pending:
        print(f"  Scraping playoff matchup: {url}")
        try:
            df = _parse_playoff_matchup(driver, url)
            df["league_url"] = league_url
            if checkpoint_path:
                write_header = not os.path.exists(checkpoint_path)
                df.to_csv(checkpoint_path, mode="a", header=write_header, index=False)
            done_urls.add(url)
            any_new = True
        except Exception as exc:
            print(f"  WARNING: failed to parse {url} ({exc!s:.120}) — skipping.")
            n_failed += 1

    collected = len(done_urls)
    missing = total - collected
    if total == 0:
        print("  WARNING: no playoff URLs were discovered — bracket may not have loaded.")
    elif missing == 0:
        print(f"  Playoff matchups COMPLETE: {collected}/{total} URLs collected.")
    else:
        print(f"  Playoff matchups INCOMPLETE: {collected}/{total} collected, {missing} still missing — re-run to resume.")

    if checkpoint_path and os.path.exists(checkpoint_path):
        return pd.read_csv(checkpoint_path), n_failed

    if not any_new and not done_urls:
        raise ValueError(
            "No playoff matchup data was collected. "
            "Check that the bracket page loaded correctly and that "
            "_bracket_urls() is finding matchup elements."
        )
    raise RuntimeError("checkpoint_path required — pass po_out.")


# ---------------------------------------------------------------------------
# Schedule results (W/L + weekly scores)
# ---------------------------------------------------------------------------

def scrape_schedule_results(
    driver: webdriver.Chrome,
    league_url: str,
    manager_ids: list[str] | None = None,
) -> pd.DataFrame:
    """Scrape weekly W/L results and scores from each team's schedule page.

    Navigates to the Schedule tab and visits every manager's schedule page.
    Each completed week's row yields: manager, manager_id, week, score (team),
    opponent_id, opponent_score, result (W/L/T).

    If the schedule subnav is unavailable (completed-season layout), pass
    manager_ids as a fallback; schedule URLs are constructed directly.

    Returns a DataFrame with one row per (manager, week).
    """
    driver.get(league_url)
    check_and_handle_login(driver)
    manager_schedule_urls = None
    try:
        tab = _wait(driver).until(EC.presence_of_element_located(SEL_SCHEDULE_TAB))
        tab.click()
        _wait(driver).until(EC.presence_of_element_located(SEL_SCHEDULE_NAV))
        nav_html = driver.find_element(*SEL_SCHEDULE_NAV).get_attribute("innerHTML")
        nav_soup = BeautifulSoup(nav_html, "html.parser")
        manager_schedule_urls = [
            (li.text.strip(), _abs_url(li.find("a")["href"]))
            for li in nav_soup.find_all("li")
        ]
    except TimeoutException:
        if manager_ids:
            print(
                "  WARNING: Schedule subnav not found; using provided manager_ids "
                "to construct schedule URLs directly."
            )
            base = league_url.rstrip("/")
            manager_schedule_urls = [(mid, f"{base}/{mid}") for mid in manager_ids]
        else:
            raise

    if not manager_schedule_urls:
        raise ValueError("No manager schedule URLs could be determined.")

    rows = []
    for manager, sched_url in manager_schedule_urls:
        # Extract the numeric team ID.
        # Nav URLs use ?scmid=N; fallback URLs use path segment /{N}.
        if "scmid=" in sched_url:
            manager_id = sched_url.split("scmid=")[1].split("&")[0]
        else:
            manager_id = sched_url.rstrip("/").split("/")[-1]

        print(f"  Schedule: {manager} (id={manager_id})")
        driver.get(sched_url)
        try:
            _wait(driver).until(EC.presence_of_element_located(SEL_SCHEDULE_TABLE))
        except Exception:
            print(f"  WARNING: schedule table not found for {manager} — skipping.")
            continue

        table_html = driver.find_element(*SEL_SCHEDULE_TABLE).get_attribute("innerHTML")
        table_soup = BeautifulSoup(table_html, "html.parser")

        for tr in table_soup.find_all("tr"):
            # Find the matchup link in this row
            matchup_href = None
            for a in tr.find_all("a"):
                href = a.get("href", "")
                if "matchup" in href and "week=" in href:
                    matchup_href = _abs_url(href)
                    break
            if not matchup_href:
                continue

            # Derive week and opponent from URL params
            try:
                week = int(matchup_href.split("week=")[1].split("&")[0])
                mid1 = matchup_href.split("mid1=")[1].split("&")[0]
                mid2_raw = matchup_href.split("mid2=")[1]
                mid2 = mid2_raw.split("&")[0] if "&" in mid2_raw else mid2_raw
                opponent_id = mid2 if mid1 == manager_id else mid1
            except Exception:
                continue  # skip rows where we can't parse the URL

            # Parse result and scores from table cells.
            # Score cell shows "129.72 - 149.14" as combined link text; split on " - ".
            result = None
            team_score = None
            opp_score = None
            for cell in tr.find_all("td"):
                text = cell.get_text(strip=True)
                if text in ("W", "L", "T"):
                    result = text
                elif text.lower() in ("win", "loss", "tie"):
                    result = text[0].upper()
                elif " - " in text:
                    parts = text.split(" - ", 1)
                    try:
                        v1 = float(parts[0].replace(",", ""))
                        v2 = float(parts[1].replace(",", ""))
                        if 0 < v1 < 1000 and 0 < v2 < 1000:
                            team_score = v1
                            opp_score = v2
                    except ValueError:
                        pass

            rows.append({
                "manager": manager,
                "manager_id": manager_id,
                "week": week,
                "score": team_score,
                "opponent_id": opponent_id,
                "opponent_score": opp_score,
                "result": result,
                "matchup_url": matchup_href,
            })

    df = pd.DataFrame(rows)
    print(f"  Schedule results collected: {len(df)} rows across {len(manager_schedule_urls)} managers")
    return df


# ---------------------------------------------------------------------------
# Playoff seeds
# ---------------------------------------------------------------------------

def _mid_from_url(url: str) -> tuple[str, str]:
    """Extract (mid1, mid2) from a playoff/matchup URL."""
    try:
        mid1 = url.split("mid1=")[1].split("&")[0]
        mid2_raw = url.split("mid2=")[1]
        mid2 = mid2_raw.split("&")[0] if "&" in mid2_raw else mid2_raw
        return mid1, mid2
    except Exception:
        return "", ""


def scrape_playoff_seeds(
    driver: webdriver.Chrome,
    league_url: str,
) -> dict[str, int]:
    """Return {manager_id (str): playoff_seed (int)} for all teams.

    Reads the playoff bracket page (championship + consolation).  Seeds are
    assigned positionally from the first-round bracket elements:

    Championship bracket (mod==0, has quarterfinals):
      QF element 0: mid1 → seed 3, mid2 → seed 6
      QF element 1: mid1 → seed 4, mid2 → seed 5
      Teams in SF/Final but NOT in QF → seeds 1 & 2 (bye teams)

    Championship bracket (mod==1, no quarterfinals, 4-team):
      SF element 0: mid1 → seed 1, mid2 → seed 4
      SF element 1: mid1 → seed 2, mid2 → seed 3

    Consolation bracket:
      SF element 0: mid1 → seed 1, mid2 → seed 4  (within consolation)
      SF element 1: mid1 → seed 2, mid2 → seed 3
      Consolation seeds are offset by number of championship teams.

    These seeding conventions assume Yahoo's standard bracket ordering
    (higher seed = mid1).  Verify the output against the actual bracket.
    """
    driver.get(league_url)
    check_and_handle_login(driver)
    driver.execute_script("window.scrollTo(0, 700)")
    time.sleep(2)

    panes, mod = _get_bracket_panes(driver)
    if not panes:
        print("  WARNING: playoff bracket panes not found — cannot extract seeds.")
        return {}

    seed_map: dict[str, int] = {}

    def _elems(pane, round_name: str):
        full = f"Linkable Bdr Bdr-radius Bg-shade Ta-start yfa-matchup bracket {round_name}"
        return pane.find_elements(By.XPATH, f".//div[@class='{full}']")

    def _urls_from_pane(pane, round_name: str) -> list[str]:
        return [
            _YAHOO_BASE + e.get_attribute("data-target")
            for e in _elems(pane, round_name)
        ]

    if mod == 0:
        # 6-team championship: pane 0 = quarterfinals, pane 1 = semis, pane 2 = final
        qf_urls = _urls_from_pane(panes[0], "quarterfinal")
        # QF pair 0: seeds 3 vs 5  |  QF pair 1: seeds 4 vs 6
        qf_seeds = [(3, 5), (4, 6)]
        for i, (hi, lo) in enumerate(qf_seeds):
            if i < len(qf_urls):
                mid1, mid2 = _mid_from_url(qf_urls[i])
                if mid1:
                    seed_map[mid1] = hi
                if mid2:
                    seed_map[mid2] = lo

        # Bye teams (seeds 1 & 2): appear in SF but not in QF.
        # Check both mid1 and mid2 per SF URL; take the first non-QF team per match.
        sf_urls = _urls_from_pane(panes[1], "semifinal")
        qf_teams = set(seed_map.keys())
        seen_bye: set[str] = set()
        bye_teams: list[str] = []
        for url in sf_urls:
            for mid in _mid_from_url(url):
                if mid and mid not in qf_teams and mid not in seen_bye:
                    bye_teams.append(mid)
                    seen_bye.add(mid)
                    break  # at most one bye team per SF matchup
        for i, mid in enumerate(bye_teams):
            seed_map[mid] = i + 1  # seeds 1, 2

    else:
        # 4-team championship: pane 0 = semis, pane 1 = final
        sf_urls = _urls_from_pane(panes[0], "semifinal")
        sf_seeds = [(1, 4), (2, 3)]
        for i, (hi, lo) in enumerate(sf_seeds):
            if i < len(sf_urls):
                mid1, mid2 = _mid_from_url(sf_urls[i])
                if mid1:
                    seed_map[mid1] = hi
                if mid2:
                    seed_map[mid2] = lo

    champ_count = len(seed_map)

    # Consolation bracket
    try:
        consolation_elem = driver.find_element(By.CSS_SELECTOR, "span[id='selectlist_nav']")
        consolation_elem.click()
        time.sleep(1)
        action = webdriver.ActionChains(driver)
        action.move_to_element(consolation_elem).move_by_offset(0, 75).click().perform()
        time.sleep(1)

        con_panes, con_mod = _get_bracket_panes(driver)
        con_sf_urls = _urls_from_pane(con_panes[1 - con_mod], "semifinal")
        # Within consolation: SF pair 0 = seeds 1 vs 4, pair 1 = seeds 2 vs 3
        con_seeds = [(1, 4), (2, 3)]
        for i, (hi, lo) in enumerate(con_seeds):
            if i < len(con_sf_urls):
                mid1, mid2 = _mid_from_url(con_sf_urls[i])
                if mid1 and mid1 not in seed_map:
                    seed_map[mid1] = champ_count + hi
                if mid2 and mid2 not in seed_map:
                    seed_map[mid2] = champ_count + lo

    except Exception as exc:
        print(f"  WARNING: consolation bracket seed extraction failed ({exc!s:.120})")

    print(f"  Playoff seeds: {seed_map}")
    return seed_map


# ---------------------------------------------------------------------------
# Position scores
# ---------------------------------------------------------------------------

_ALL_POSITIONS = ["QB", "WR", "RB", "TE", "K", "DEF"]


def scrape_position_scores(
    driver: webdriver.Chrome,
    league_url: str,
    positions: list[str] | None = None,
) -> tuple[pd.DataFrame, list[str]]:
    """Scrape season-total position scores for all players in one league season.

    If positions is None (the default), the set of positions is discovered
    automatically from the player filter labels on the Yahoo page — so positions
    not used in that season's league (e.g. K in 2025) are silently skipped.

    Returns (df, failed_positions) where failed_positions is a list of position
    labels that were present on the page but could not be scraped.
    """
    player_url = league_url + "/players"
    driver.get(player_url)
    check_and_handle_login(driver)

    status_select = Select(driver.find_element(*SEL_STATUS_SELECT))
    status_select.select_by_visible_text("All Players")
    time.sleep(1)
    driver.find_element(*SEL_SEASON_TOTAL_OPTION).click()

    if positions is None:
        # Probe each known position: find_elements returns [] if the label is absent.
        positions = [
            p for p in _ALL_POSITIONS
            if driver.find_elements(By.XPATH, f"//label[text()='{p}']")
        ]
        print(f"  Detected positions on page: {positions}")

    all_dfs = []
    failed_positions: list[str] = []

    for position in positions:
        print(f"  Collecting {position} players...")
        try:
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

            pos_df = pd.concat(position_pages, ignore_index=True)
            print(f"  {position}: {len(pos_df)} players scraped.")
            all_dfs.append(pos_df)

        except Exception as exc:
            print(f"  WARNING: failed to scrape {position} ({exc!s:.120}) — skipping.")
            failed_positions.append(position)

    if not all_dfs:
        raise ValueError("No position data collected for any position. Check authentication and selectors.")

    if failed_positions:
        print(f"  Positions INCOMPLETE: {len(failed_positions)} failed {failed_positions} — re-run to retry.")
    else:
        print(f"  Positions COMPLETE: all {len(positions)} positions scraped.")

    return pd.concat(all_dfs, ignore_index=True), failed_positions


# ---------------------------------------------------------------------------
# Standings
# ---------------------------------------------------------------------------

def scrape_standings(driver: webdriver.Chrome, league_url: str) -> pd.DataFrame:
    """
    Scrape season standings from Yahoo Fantasy /standings page.

    Yahoo's /standings URL renders a scoring-totals table (not a W-L table).
    The section with id="standings-table" contains one row per team with:
      cell[0]  rank label ("1.", "2.", ...)
      cell[1]  team name + link (href ends with manager_id integer)
      cell[-1] season total points

    Wins and losses are not available on this page and are left as 0.
    They can be derived from the RS matchup data in the pipeline if needed.

    If the structure changes, re-run the scrape step and inspect standings_debug.html.
    """
    driver.get(league_url.rstrip("/") + "/standings")
    check_and_handle_login(driver)

    # Wait for the standings section to render.
    try:
        _wait(driver).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "section#standings-table"))
        )
    except Exception:
        pass
    time.sleep(2)

    soup = BeautifulSoup(driver.page_source, "html.parser")
    section = soup.find("section", {"id": "standings-table"})

    if section is None:
        debug_path = "standings_debug.html"
        with open(debug_path, "w", encoding="utf-8") as _f:
            _f.write(driver.page_source)
        raise ValueError(
            "Cannot find section#standings-table on /standings page. "
            f"Page source saved to {debug_path} for inspection."
        )

    target_table = section.find("table")
    if target_table is None:
        raise ValueError("section#standings-table found but contains no <table>.")

    # Build the league path fragment to match team hrefs ("/2025/f1/532435").
    league_path_frag = "/" + "/".join(league_url.rstrip("/").split("/")[-3:])

    records = []
    for row in target_table.select("tbody tr"):
        cells = row.find_all("td")
        if len(cells) < 2:
            continue

        team_link = row.find("a", href=lambda h: h and league_path_frag in h)
        if not team_link:
            continue

        href_parts = team_link["href"].rstrip("/").split("/")
        manager_id = href_parts[-1] if href_parts and href_parts[-1].isdigit() else ""
        team_name  = team_link.get_text(strip=True)

        # Rank from first cell ("1.", "2.", ...).
        rank_text = cells[0].get_text(strip=True).rstrip(".")
        try:
            rank = int(rank_text)
        except ValueError:
            continue

        # Total season points in last cell.
        try:
            points_for = float(cells[-1].get_text(strip=True).replace(",", ""))
        except (ValueError, TypeError):
            points_for = 0.0

        records.append({
            "rank":           rank,
            "name":           team_name,
            "manager":        team_name,   # display name not separately available
            "manager_id":     manager_id,
            "wins":           0,           # not on this page; derive from matchup data
            "losses":         0,
            "points_for":     points_for,
            "points_against": 0.0,
        })

    if not records:
        debug_path = "standings_debug.html"
        with open(debug_path, "w", encoding="utf-8") as _f:
            _f.write(driver.page_source)
        raise ValueError(
            "section#standings-table found but no rows parsed. "
            f"Page source saved to {debug_path} for inspection."
        )

    print(f"  Scraped {len(records)} standings rows.")
    df = pd.DataFrame(records)

    # Enrich with FAAB balance and moves from the main league standings tab.
    stand_extras = _scrape_stand_tab_extras(driver, league_url)
    if stand_extras:
        df["faab_balance"] = df["manager_id"].map(
            {k: v.get("faab_balance", "") for k, v in stand_extras.items()}
        )
        df["moves"] = df["manager_id"].map(
            {k: v.get("moves", "") for k, v in stand_extras.items()}
        )
        print(f"  Standings tab extras: {stand_extras}")
    else:
        df["faab_balance"] = ""
        df["moves"] = ""

    return df


def _scrape_stand_tab_extras(
    driver: webdriver.Chrome,
    league_url: str,
) -> dict[str, dict]:
    """
    Scrape 'Waiver Bdgt' (FAAB) and 'Moves' from the main league ?lhst=stand page.

    Navigates to the old-style league home (Standings tab), waits for any table
    containing 'Waiver'/'Bdgt'/'Moves' headers, and reads FAAB + moves by column
    index. Falls back to a page-wide table scan if #leaguehomestandings is absent.

    Returns {manager_id: {"faab_balance": "...", "moves": "..."}} or {} on failure.
    """
    stand_url = league_url.rstrip("/") + "?lhst=stand"
    driver.get(stand_url)
    print(f"  [faab-scrape] navigated to: {driver.current_url}")

    # Give JS time to render dynamic content.  Try the specific section first,
    # then fall back to a page-wide scan.
    section_elem = None
    try:
        _wait(driver, timeout=30).until(
            EC.presence_of_element_located(
                (By.CSS_SELECTOR, "#leaguehomestandings table")
            )
        )
        section_elem = driver.find_element(By.ID, "leaguehomestandings")
        print("  [faab-scrape] found #leaguehomestandings table")
    except TimeoutException:
        print("  [faab-scrape] #leaguehomestandings table not found — will scan all tables")

    if section_elem is not None:
        html = section_elem.get_attribute("innerHTML")
    else:
        html = driver.page_source

    soup = BeautifulSoup(html, "html.parser")

    # Locate a table whose <thead> contains "Waiver"/"Bdgt" or "Moves".
    target_table = waiver_idx = moves_idx = None
    for tbl in soup.find_all("table"):
        thead = tbl.find("thead")
        if not thead:
            continue
        hdrs = [th.get_text(strip=True) for th in thead.find_all("th")]
        w = next((i for i, h in enumerate(hdrs) if "waiver" in h.lower() or "bdgt" in h.lower()), None)
        m = next((i for i, h in enumerate(hdrs) if "move" in h.lower()), None)
        if w is not None or m is not None:
            target_table, waiver_idx, moves_idx = tbl, w, m
            print(f"  [faab-scrape] found FAAB table with headers: {hdrs}")
            break

    if target_table is None:
        # Summarise all table headers to help debug future changes.
        all_hdrs = []
        for i, tbl in enumerate(soup.find_all("table")):
            th = tbl.find("thead")
            if th:
                all_hdrs.append(f"table[{i}]: {[x.get_text(strip=True) for x in th.find_all('th')]}")
        print(f"  [faab-scrape] no FAAB table found. Tables on page: {all_hdrs}")
        debug_path = "faab_debug.html"
        with open(debug_path, "w", encoding="utf-8") as _f:
            _f.write(html)
        print(f"  [faab-scrape] HTML saved to {debug_path}")
        return {}

    # Match team rows using the last two URL path segments ("/f1/532435") so the
    # year prefix is irrelevant (handles both /f1/532435/N and /2025/f1/532435/N).
    url_parts = league_url.rstrip("/").split("/")
    league_path_frag = "/" + "/".join(url_parts[-2:])   # "/f1/532435"

    result: dict[str, dict] = {}
    for row in target_table.select("tbody tr"):
        cells = row.find_all("td")
        team_link = row.find("a", href=lambda h: h and league_path_frag in h)
        if not team_link:
            continue
        href_parts = team_link["href"].rstrip("/").split("/")
        manager_id = href_parts[-1] if href_parts and href_parts[-1].isdigit() else ""
        if not manager_id:
            continue

        row_data: dict = {}
        if waiver_idx is not None and len(cells) > waiver_idx:
            row_data["faab_balance"] = cells[waiver_idx].get_text(strip=True).replace("$", "").strip()
        if moves_idx is not None and len(cells) > moves_idx:
            row_data["moves"] = cells[moves_idx].get_text(strip=True)
        result[manager_id] = row_data

    if not result:
        print(f"  [faab-scrape] table found but no rows matched league_path_frag={league_path_frag!r}")

    return result


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


def scrape_faab(driver: webdriver.Chrome, league_url: str) -> tuple[pd.DataFrame, list[str]]:
    """Scrape all FAAB transactions (contested bids + uncontested adds) for one season.

    Returns (df, warnings) where warnings is a list of any anomalies detected
    (e.g. a phase that returned 0 records, suggesting a selector or auth issue).
    """
    warnings: list[str] = []

    faab_url = league_url + "/transactions?transactionsfilter=faab"
    driver.get(faab_url)
    check_and_handle_login(driver)
    faab_df = _paginate_scrape(driver, _scrape_faab_bid_page)
    print(f"  FAAB contested bids: {len(faab_df)} records.")
    if faab_df.empty:
        warnings.append("0 contested FAAB bid records — page may be empty or selector changed")

    add_url = league_url + "/transactions?transactionsfilter=add"
    driver.get(add_url)
    adds_raw = _paginate_scrape(driver, _scrape_add_page)
    faab_adds = adds_raw[adds_raw.faab_spend.str.startswith("$")].copy()
    print(f"  Uncontested FAAB adds: {len(faab_adds)} records (from {len(adds_raw)} total adds).")
    if adds_raw.empty:
        warnings.append("0 free-agent add records — page may be empty or selector changed")

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
    print(f"  Total FAAB records after dedup: {len(combined)}.")
    return combined, warnings
