import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.job_filter import fetch_easy_apply_jobs

def test_segregation():
    print("=" * 65)
    print("TESTING PLATFORM SEGREGATION")
    print("=" * 65)

    # 1. Indeed Only
    print("\n--- Testing Indeed Only ---")
    indeed_jobs = fetch_easy_apply_jobs(
        search_terms=["Software Developer"],
        locations=["India"],
        platforms=["indeed"],
        results_per_query=5
    )
    print(f"Indeed returned {len(indeed_jobs)} jobs:")
    for j in indeed_jobs:
        url = j.get("job_url", "")
        print(f"  • {j.get('title')} @ {j.get('company')} -> {url}")
        assert "indeed.com" in url.lower(), f"Non-Indeed URL found in indeed-only run: {url}"
    print("  [PASS] 100% of jobs returned are from Indeed!")

    # 2. LinkedIn Only
    print("\n--- Testing LinkedIn Only ---")
    linkedin_jobs = fetch_easy_apply_jobs(
        search_terms=["Software Developer"],
        locations=["India"],
        platforms=["linkedin"],
        results_per_query=5
    )
    print(f"LinkedIn returned {len(linkedin_jobs)} jobs:")
    for j in linkedin_jobs:
        url = j.get("job_url", "")
        print(f"  • {j.get('title')} @ {j.get('company')} -> {url}")
        assert "linkedin.com" in url.lower(), f"Non-LinkedIn URL found in linkedin-only run: {url}"
    print("  [PASS] 100% of jobs returned are from LinkedIn!")

    print("\n" + "=" * 65)
    print("PLATFORM SEGREGATION TESTS PASSED!")
    print("=" * 65)

if __name__ == "__main__":
    test_segregation()

