import sys
from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from jobspy import scrape_jobs
from src.job_filter import is_experience_eligible

def find_indeed_jobs():
    print("Searching for live Indeed Easy Apply jobs in India with country_indeed='india'...")
    df = scrape_jobs(
        site_name=["indeed"],
        search_term="Software Developer",
        location="India",
        country_indeed="india",
        easy_apply=True,
        results_wanted=15
    )
    print(f"Total jobs returned from Indeed: {len(df)}")
    if not df.empty:
        for idx, row in df.iterrows():
            job_dict = row.to_dict()
            is_direct = job_dict.get("is_direct_apply", False)
            title = job_dict.get("title")
            company = job_dict.get("company")
            url = job_dict.get("job_url")
            eligible, reason = is_experience_eligible(job_dict, max_yoe_allowed=3)
            print(f"[{idx+1}] {title} @ {company} | DirectApply: {is_direct} | Eligible: {eligible}")
            if is_direct and eligible:
                print(f"    Selected URL: {url}")
                return url
    return None

if __name__ == "__main__":
    find_indeed_jobs()
