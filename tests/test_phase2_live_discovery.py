import sys
from pathlib import Path
import json

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.config import load_profile
from src.job_filter import fetch_easy_apply_jobs

def run_live_discovery_test():
    print("=" * 70)
    print("PHASE 2 LIVE DISCOVERY: FETCHING LIVE EASY-APPLY JOBS")
    print("=" * 70)

    # 1. Load target preferences from profile
    profile = load_profile()
    target_search = profile.get("target_search", {})
    job_titles = target_search.get("job_titles", ["Software Developer"])
    locations = target_search.get("locations", ["India"])
    max_yoe = target_search.get("max_years_experience", 3)

    # Pick top 2 titles for a quick, focused test
    sample_titles = job_titles[:2]
    sample_locations = locations[:1]

    print(f"Target Titles:     {sample_titles}")
    print(f"Target Locations:  {sample_locations}")
    print(f"Max YOE allowed:   <= {max_yoe} years")
    print(f"Filter Mode:       Strictly Easy Apply / Direct Apply Only")
    print("-" * 70)

    # 2. Fetch jobs
    discovered_jobs = fetch_easy_apply_jobs(
        search_terms=sample_titles,
        locations=sample_locations,
        results_per_query=8,
        hours_old=72,
        max_yoe=max_yoe
    )

    print(f"\nSuccessfully discovered and filtered {len(discovered_jobs)} eligible jobs:\n")

    for i, job in enumerate(discovered_jobs[:6], 1):
        site = job.get("site", "N/A")
        title = job.get("title", "N/A")
        company = job.get("company", "N/A")
        location = job.get("location", "N/A")
        job_url = job.get("job_url", "N/A")
        reason = job.get("eligibility_reason", "N/A")

        print(f"[{i}] {title} @ {company}")
        print(f"    Platform:    {site}")
        print(f"    Location:    {location}")
        print(f"    Eligibility: {reason}")
        print(f"    URL:         {job_url}")
        print("-" * 70)

    return discovered_jobs

if __name__ == "__main__":
    run_live_discovery_test()

