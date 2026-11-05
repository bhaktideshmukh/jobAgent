import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.job_filter import fetch_easy_apply_jobs

jobs = fetch_easy_apply_jobs(
    search_terms=['Software Engineer'],
    locations=['India'],
    results_per_query=4,
    hours_old=72,
    max_yoe=3
)
print(f"\nTotal Jobs Returned: {len(jobs)}")
platforms = {}
for j in jobs:
    p = 'Indeed' if 'indeed.com' in j.get('job_url', '') else 'LinkedIn'
    platforms[p] = platforms.get(p, 0) + 1
    print(f"  [{p:8}] {j.get('title')} @ {j.get('company')} -> {j.get('job_url')}")
print(f"\nPlatform Breakdown: {platforms}")
assert 'Indeed' in platforms and platforms['Indeed'] > 0, "No Indeed jobs found!"
assert 'LinkedIn' in platforms and platforms['LinkedIn'] > 0, "No LinkedIn jobs found!"
print("SUCCESS: Both LinkedIn and Indeed jobs are present in the queue!")
