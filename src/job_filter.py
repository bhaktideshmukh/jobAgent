import re
from typing import Dict, Any, List, Optional
from jobspy import scrape_jobs
import pandas as pd

SENIOR_KEYWORDS = [
    "senior", "sr.", "sr ", "lead", "principal", "staff", "architect", 
    "director", "vp", "head of", "manager", "team lead"
]

def is_experience_eligible(job: Dict[str, Any], max_yoe_allowed: int = 3) -> bool:
    """
    Evaluates whether a job posting requires <= max_yoe_allowed (default 3 years).
    Returns True if:
      - Title does not contain senior keywords
      - Explicit years mentioned are <= max_yoe_allowed, or no explicit years required.
    """
    title = str(job.get("title", "")).lower()
    description = str(job.get("description", "")).lower()

    # 1. Reject if title has senior keywords
    for kw in SENIOR_KEYWORDS:
        # Match as whole word or prefix
        pattern = r"\b" + re.escape(kw) + r"\b"
        if re.search(pattern, title):
            return False

    # 2. Extract experience mentions from description
    # Matches patterns like:
    # "3+ years", "2-4 years", "minimum 5 years", "3 to 5 years of experience"
    exp_patterns = [
        r'(\d+)\+?\s*(?:to|-)\s*(\d+)\+?\s*years?',
        r'(?:minimum|at least)\s*(\d+)\+?\s*years?',
        r'(\d+)\+?\s*years?(?:\s+of)?\s+experience'
    ]

    detected_years = []

    for pat in exp_patterns:
        matches = re.findall(pat, description)
        for m in matches:
            if isinstance(m, tuple):
                for val in m:
                    if val and val.isdigit():
                        detected_years.append(int(val))
            elif isinstance(m, str) and m.isdigit():
                detected_years.append(int(m))

    # If explicit experience requirements are mentioned
    if detected_years:
        min_required = min(detected_years)
        # If the minimum requirement is strictly greater than max allowed (e.g., 4, 5+ yrs), reject
        if min_required > max_yoe_allowed:
            return False

    return True

def fetch_easy_apply_jobs(
    search_terms: List[str],
    locations: List[str],
    results_per_query: int = 15,
    hours_old: int = 48
) -> List[Dict[str, Any]]:
    """
    Queries LinkedIn and Indeed specifically for Easy Apply / Direct Apply jobs.
    """
    collected_jobs: List[Dict[str, Any]] = []

    for term in search_terms:
        for loc in locations:
            try:
                jobs_df = scrape_jobs(
                    site_name=["linkedin", "indeed"],
                    search_term=term,
                    location=loc,
                    results_wanted=results_per_query,
                    hours_old=hours_old,
                    easy_apply=True  # Strictly Easy Apply / Direct Apply
                )
                if not jobs_df.empty:
                    # Filter for <= 3 years of experience
                    records = jobs_df.to_dict(orient="records")
                    for job in records:
                        if is_experience_eligible(job, max_yoe_allowed=3):
                            collected_jobs.append(job)
            except Exception as e:
                print(f"Error fetching jobs for {term} in {loc}: {e}")

    # Deduplicate by job URL or title+company
    unique_jobs = {}
    for job in collected_jobs:
        key = job.get("job_url") or f"{job.get('title')}-{job.get('company')}"
        if key not in unique_jobs:
            unique_jobs[key] = job

    return list(unique_jobs.values())

