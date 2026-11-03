import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.browser_automation import JobApplicationBrowser

def run_phase3_test():
    print("=" * 70)
    print("PHASE 3 VERIFICATION: PLAYWRIGHT EASY APPLY AUTOMATION")
    print("=" * 70)

    # Default unapplied job from Phase 2: .Net Developer @ UST
    default_url = "https://www.linkedin.com/jobs/view/4486024681"
    test_job_url = sys.argv[1] if len(sys.argv) > 1 else default_url

    print(f"Target Job URL: {test_job_url}")
    print("Launching browser with your saved LinkedIn session...")
    print("The agent will:")
    print("  1. Open the job listing")
    print("  2. Click 'Easy Apply'")
    print("  3. Autofill inputs using your profile & resume")
    print("  4. Stop at the Review step and take a screenshot")
    print("-" * 70)

    browser = JobApplicationBrowser(headless=False)
    result = browser.process_application(test_job_url)
    browser.close()

    print("\n" + "=" * 70)
    print("PHASE 3 TEST RESULT:")
    print(f"Status:            {result.get('status')}")
    print(f"Easy Apply Found:  {result.get('easy_apply_found')}")
    print(f"Review Screenshot: {result.get('screenshot_path')}")
    if result.get("error"):
        print(f"Note / Error:      {result.get('error')}")
    print("=" * 70)

if __name__ == "__main__":
    run_phase3_test()

