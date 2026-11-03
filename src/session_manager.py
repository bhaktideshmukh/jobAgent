import os
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.config import BROWSER_USER_DATA_DIR

def open_interactive_login_session():
    """
    Opens a visible browser with a persistent user profile.
    Allows the user to log into LinkedIn and Indeed once.
    Cookies and login sessions are saved permanently in browser_profile/
    """
    BROWSER_USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
    print("=" * 70)
    print("PLAYWRIGHT PERSISTENT SESSION SETUP")
    print(f"Profile directory: {BROWSER_USER_DATA_DIR}")
    print("=" * 70)
    print("1. A browser window will open.")
    print("2. Log in to your LinkedIn and/or Indeed accounts.")
    print("3. Check 'Remember me' and complete any 2FA/SMS verification.")
    print("4. Once logged in, close the browser window or press Enter here.")
    print("=" * 70)

    with sync_playwright() as p:
        browser_context = p.chromium.launch_persistent_context(
            user_data_dir=str(BROWSER_USER_DATA_DIR),
            headless=False,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--start-maximized"
            ],
            viewport=None
        )
        # Tab 1: LinkedIn Login
        page_linkedin = browser_context.new_page()
        page_linkedin.goto("https://www.linkedin.com/login")

        # Tab 2: Indeed Login
        page_indeed = browser_context.new_page()
        page_indeed.goto("https://secure.indeed.com/account/login")

        print("Both LinkedIn and Indeed login tabs are now open.")
        print("Please log in to both accounts in the opened browser window.")
        try:
            input("Press Enter after logging in to BOTH accounts to save session and close: ")
        except EOFError:
            pass
        browser_context.close()
        print("Session saved successfully!")

if __name__ == "__main__":
    open_interactive_login_session()

