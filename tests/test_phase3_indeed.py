import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.browser_automation import JobApplicationBrowser

def run_indeed_test():
    print("=" * 70)
    print("PHASE 3 VERIFICATION: INDEED APPLY AUTOMATION")
    print("=" * 70)

    # Live Indeed India job URL
    test_job_url = "https://in.indeed.com/viewjob?jk=eb7c81fcf8303125"
    if len(sys.argv) > 1:
        test_job_url = sys.argv[1]

    print(f"Target Indeed Job URL: {test_job_url}")
    print("Launching visible Chrome with your saved Indeed profile...")
    print("Note: If a Cloudflare Security Check appears, complete the checkbox in the window.")
    print("-" * 70)

    browser = JobApplicationBrowser(headless=False)
    result = browser.process_application(test_job_url, auto_submit=True)
    browser.close()

    print("\n" + "=" * 70)
    print("INDEED TEST RESULT:")
    print(f"Status:            {result.get('status')}")
    print(f"Apply Found:       {result.get('easy_apply_found')}")
    print(f"Review Screenshot: {result.get('screenshot_path')}")
    if result.get("error"):
        print(f"Note / Error:      {result.get('error')}")
    print("=" * 70)

if __name__ == "__main__":
    run_indeed_test()

