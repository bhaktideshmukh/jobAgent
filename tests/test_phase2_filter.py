import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.job_filter import is_experience_eligible

def test_experience_patterns():
    print("=" * 70)
    print("PHASE 2 UNIT TEST: EXPERIENCE PATTERN VALIDATION")
    print("=" * 70)

    # All variations specifically requested by user:
    # 0 - 2, 0 - 1, 1+, 2+, 1 - 2, 0 - 3, 2 - 3, 3+, 2- 4, 1 - 3
    test_cases = [
        # (Title, Description snippet, Expected eligibility, Note)
        ("Software Developer", "Requires 0 - 2 years of experience", True, "0 - 2"),
        ("Python Engineer", "Needs 0 - 1 yrs experience", True, "0 - 1"),
        ("AI Engineer", "1+ years of industry experience", True, "1+"),
        ("SDE 1", "2+ yrs in backend development", True, "2+"),
        ("Associate Developer", "1 - 2 yrs of experience with databases", True, "1 - 2"),
        ("Junior Dev", "0 - 3 years experience required", True, "0 - 3"),
        ("Fullstack Dev", "2 - 3 YOE required", True, "2 - 3"),
        ("Backend Engineer", "3+ yrs in Python / Django", True, "3+"),
        ("Developer", "2- 4 years of software development", True, "2- 4"),
        ("DevOps Engineer", "1 - 3 yrs with Docker/Kubernetes", True, "1 - 3"),
        ("Entry Level Dev", "Freshers can apply", True, "Fresher keyword"),
        # Rejection cases (> 3 years or Senior titles)
        ("Backend Engineer", "Requires 4+ years of experience", False, "4+ (Exceeds 3)"),
        ("Lead Developer", "5 - 7 years of experience", False, "5 - 7 (Exceeds 3)"),
        ("Senior Python Engineer", "2 years of experience", False, "Senior in title"),
        ("Staff AI Architect", "1+ years experience", False, "Staff/Architect title"),
        ("Software Engineer", "Company in business for 20 years. Freshers welcome.", True, "Company age false-positive")
    ]

    all_passed = True
    for title, desc, expected, label in test_cases:
        job = {"title": title, "description": desc}
        eligible, reason = is_experience_eligible(job, max_yoe_allowed=3)
        status = "PASS" if eligible == expected else "FAIL"
        if status == "FAIL":
            all_passed = False
        print(f"[{status}] Case: {label:20} -> Eligible: {eligible!s:5} | Reason: {reason}")

    print("=" * 70)
    if all_passed:
        print("ALL EXPERIENCE PATTERNS VERIFIED & PASSED!")
    else:
        print("SOME PATTERNS FAILED!")
    print("=" * 70)

if __name__ == "__main__":
    test_experience_patterns()

