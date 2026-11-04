import os
import sys
from pathlib import Path
from playwright.sync_api import sync_playwright

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.config import BROWSER_USER_DATA_DIR

def open_interactive_login_session(target: str = "both"):
    """
    Opens a visible Chrome window with the persistent user profile.
    Target options: 'both', 'linkedin', 'indeed'.
    """
    BROWSER_USER_DATA_DIR.mkdir(parents=True, exist_ok=True)
    print("=" * 70)
    print(f"PERSISTENT SESSION SETUP - TARGET: {target.upper()}")
    print(f"Profile directory: {BROWSER_USER_DATA_DIR}")
    print("=" * 70)

    with sync_playwright() as p:
        browser_context = p.chromium.launch_persistent_context(
            user_data_dir=str(BROWSER_USER_DATA_DIR),
            channel="chrome",  # Uses real installed Google Chrome to avoid Cloudflare flags
            headless=False,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--start-maximized",
                "--no-sandbox"
            ],
            viewport=None
        )

        # Remove navigator.webdriver detection
        browser_context.add_init_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")

        if target in ["both", "linkedin"]:
            page_linkedin = browser_context.new_page()
            page_linkedin.goto("https://www.linkedin.com/login", wait_until="domcontentloaded")
            print("Opened LinkedIn login tab.")

        if target in ["both", "indeed"]:
            page_indeed = browser_context.new_page()
            # Proper OAuth entry point with continue parameter
            indeed_url = "https://secure.indeed.com/auth?continue=https%3A%2F%2Fin.indeed.com%2F"
            page_indeed.goto(indeed_url, wait_until="domcontentloaded")
            print("Opened Indeed login tab.")

        print("\nPlease complete your login in the opened browser window.")
        try:
            input("Press [Enter] here once you are logged in to save session and close: ")
        except EOFError:
            pass

        browser_context.close()
        print("Session saved successfully!")

if __name__ == "__main__":
    mode = "both"
    if len(sys.argv) > 1:
        mode = sys.argv[1].lower()
    open_interactive_login_session(target=mode)
