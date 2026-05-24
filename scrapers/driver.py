"""
Chrome WebDriver setup. All driver configuration lives here so Yahoo HTML
changes only require edits in one place.
"""

import os
from dotenv import load_dotenv
from selenium import webdriver
from selenium.webdriver.chrome.options import Options

load_dotenv()

CHROME_PROFILE_DIR = os.getenv("CHROME_PROFILE_DIR", "C:/chrome_profile")
DEBUGGING_PORT = 9222


def get_driver(headless: bool = False) -> webdriver.Chrome:
    options = Options()
    options.add_argument(f"--user-data-dir={CHROME_PROFILE_DIR}")
    options.add_argument(f"--remote-debugging-port={DEBUGGING_PORT}")
    if headless:
        options.add_argument("--headless=new")
    return webdriver.Chrome(options=options)


def quit_driver(driver: webdriver.Chrome) -> None:
    try:
        driver.quit()
    except Exception:
        pass
