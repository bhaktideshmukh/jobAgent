import re
from typing import Dict, Any, List, Tuple
from jobspy import scrape_jobs

UNIT = r'(?:years?|yrs?|yoe)'

# 1. Range pattern: e.g. 0-2 yrs, 0 - 1 yr, 1 to 3 years, 2 - 4 YOE, 1-2 yrs
RANGE_PATTERN = rf'(\d+)\s*(?:\+|plus)?\s*(?:to|[-–—])\s*(\d+)\s*(?:\+|plus)?\s*{UNIT}'

# 2. Single value pattern: e.g. 1+ years, 2+ yrs, 3+ YOE, minimum 4 years, 3 years
SINGLE_PATTERN = rf'(?:minimum|min|at least)?\s*(\d+)\s*(?:\+|plus)?\s*{UNIT}'

ENTRY_LEVEL_KEYWORDS = [
    "fresher", "freshers", "entry level", "entry-level", 
    "junior", "jr.", "jr ", "intern", "internship", "trainee", "graduate"
]

SENIOR_KEYWORDS = [
    "senior", "sr.", "sr ", "lead", "principal", "staff", 
    "architect", "director", "vp", "head of", "manager", "team lead"
]

def is_experience_eligible(job: Dict[str, Any], max_yoe_allowed: int = 3) -> Tuple[bool, str]:
    """
    Evaluates whether a job posting requires <= max_yoe_allowed (default 3 years).
    
    Handles:
      - Ranges: 0-1, 0-2, 0-3, 1-2, 1-3, 2-3, 2-4 yrs
      - Singles with plus: 1+, 2+, 3+, 4+ yrs/years/YOE
      - Entry-level / Fresher keywords: automatically eligible
      - Senior / Lead / Staff titles: automatically rejected
    """
    title = str(job.get("title", "")).lower()
    description = str(job.get("description", "")).lower()
    full_text = f"{title} {description}"

    # 1. Immediate reject for senior/management titles
    for kw in SENIOR_KEYWORDS:
        pattern = r"\b" + re.escape(kw) + r"\b"
        if re.search(pattern, title):
            return False, f"Rejected: Title contains '{kw}'"

    # 2. Immediate accept for explicit fresher / entry-level keywords
    for kw in ENTRY_LEVEL_KEYWORDS:
        if kw in full_text:
            return True, f"Accepted: Explicit entry-level/fresher keyword ('{kw}')"

    # 3. Check for experience ranges (e.g. 0-2, 1-3, 2-4, 3-5, 5-7)
    ranges = re.findall(RANGE_PATTERN, full_text)
    if ranges:
        for low_str, high_str in ranges:
            low = int(low_str)
            high = int(high_str)
            # If the minimum requirement itself is greater than allowed (e.g. 4-6, 5-7), reject
            if low > max_yoe_allowed:
                return False, f"Rejected: Required range {low}-{high} YOE exceeds max {max_yoe_allowed}"
            else:
                return True, f"Accepted: Experience range {low}-{high} YOE is within target"

    # 4. Check for single mentions (e.g. 1+, 2+, 3+, 4+, 5+ years/yrs/YOE)
    singles = re.findall(SINGLE_PATTERN, full_text)
    if singles:
        # Extract all detected numbers tied to experience units
        detected_yoes = [int(s) for s in singles if s.isdigit()]
        if detected_yoes:
            min_yoe = min(detected_yoes)
            # If the minimum experience mention is strictly greater than max allowed (e.g. 4+, 5+ yrs)
            if min_yoe > max_yoe_allowed:
                return False, f"Rejected: Requires minimum {min_yoe}+ YOE which exceeds max {max_yoe_allowed}"
            else:
                return True, f"Accepted: Experience mention ({min_yoe}+ YOE) is <= {max_yoe_allowed}"

    # Default: If no explicit experience barrier is found, keep it
    return True, "Accepted: <= 3 YOE or no explicit experience requirement found"

def fetch_easy_apply_jobs(
    search_terms: List[str],
    locations: List[str],
    results_per_query: int = 15,
    hours_old: int = 48,
    max_yoe: int = 3
) -> List[Dict[str, Any]]:
    """
    Queries LinkedIn and Indeed specifically for Easy Apply / Direct Apply jobs.
    Filters out any roles requiring more than max_yoe.
    """
    collected_jobs: List[Dict[str, Any]] = []

    for term in search_terms:
        for loc in locations:
            try:
                print(f"Fetching '{term}' jobs in '{loc}' (Easy Apply only)...")
                jobs_df = scrape_jobs(
                    site_name=["linkedin", "indeed"],
                    search_term=term,
                    location=loc,
                    results_wanted=results_per_query,
                    hours_old=hours_old,
                    easy_apply=True  # Strictly Easy Apply / Direct Apply
                )
                if not jobs_df.empty:
                    records = jobs_df.to_dict(orient="records")
                    for job in records:
                        eligible, reason = is_experience_eligible(job, max_yoe_allowed=max_yoe)
                        job["is_eligible"] = eligible
                        job["eligibility_reason"] = reason
                        if eligible:
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
