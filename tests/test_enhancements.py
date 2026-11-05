import sys
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.rag_engine import ProfileRAG
from src.tracker import extract_job_identifier, is_already_applied
from src.config import get_resume_path, get_cover_letter_path

def test_all():
    print("=" * 70)
    print("RUNNING VERIFICATION FOR 7 USER OBSERVATIONS")
    print("=" * 70)

    # 1. Test Queue Deduplication & Job ID Extraction
    print("\n--- 1. Deduplication & Job Identification ---")
    urls = [
        ("https://www.linkedin.com/jobs/view/4486825915", "linkedin_4486825915"),
        ("https://in.linkedin.com/jobs/view/4486825915?refId=abc", "linkedin_4486825915"),
        ("https://in.indeed.com/viewjob?jk=eb7c81fcf8303125&from=serp", "indeed_eb7c81fcf8303125"),
        ("https://www.indeed.com/viewjob?jk=eb7c81fcf8303125", "indeed_eb7c81fcf8303125"),
    ]
    for url, expected in urls:
        extracted = extract_job_identifier(url)
        assert extracted == expected, f"Expected {expected}, got {extracted}"
        print(f"  [PASS] {url} -> {extracted}")

    # Test is_already_applied by title + company
    assert is_already_applied({"title": "Back End Developer", "company": "Helpshift"}), "Failed title+company match"
    print("  [PASS] Successfully detected previously submitted job by title + company")

    # 2. Test CTC Clean Number Formatting (No Currency)
    print("\n--- 2. CTC Clean Number Formatting ---")
    rag = ProfileRAG()
    curr_ctc = rag.answer_screening_question("What is your current CTC?")
    exp_ctc = rag.answer_screening_question("What is your expected salary?")
    assert curr_ctc == "1500000", f"Expected 1500000, got {curr_ctc}"
    assert exp_ctc == "1800000", f"Expected 1800000, got {exp_ctc}"
    assert "inr" not in curr_ctc.lower() and "inr" not in exp_ctc.lower(), "Currency found in CTC!"
    print(f"  [PASS] Current CTC: '{curr_ctc}' (Digits only)")
    print(f"  [PASS] Expected CTC: '{exp_ctc}' (Digits only)")

    # 3. Test Cover Letter & Resume File Detection
    print("\n--- 3. File Paths for Resume & Cover Letter ---")
    resume = get_resume_path()
    cover = get_cover_letter_path()
    assert resume.exists(), f"Resume not found at {resume}"
    assert cover.exists(), f"Cover letter not found at {cover}"
    print(f"  [PASS] Resume file: {resume.name}")
    print(f"  [PASS] Cover letter file: {cover.name}")

    # 4. Test Current Company
    print("\n--- 4. Current Company Filling ---")
    company_answers = [
        rag.answer_screening_question("Current company name?"),
        rag.answer_screening_question("What is your current employer?"),
        rag.answer_screening_question("Current Organization:"),
    ]
    for ans in company_answers:
        assert ans == "Avalara Technologies", f"Expected Avalara Technologies, got {ans}"
    print(f"  [PASS] Current Company correctly answers: '{company_answers[0]}'")

    # 5 & 6. Test Rating Questions (Highest Integer)
    print("\n--- 5 & 6. Rating Questions (Highest Integer) ---")
    r5 = rag.answer_screening_question("Rate yourself in Python on a scale of 1 to 5")
    r10 = rag.answer_screening_question("Rate your communication skills on a scale of 1-10")
    r_gen = rag.answer_screening_question("How would you rate yourself in SQL?")
    assert r5 == "5", f"Expected 5, got {r5}"
    assert r10 == "10", f"Expected 10, got {r10}"
    assert r_gen == "5", f"Expected 5, got {r_gen}"
    print(f"  [PASS] 1-5 Scale: {r5}")
    print(f"  [PASS] 1-10 Scale: {r10}")
    print(f"  [PASS] Generic Rating: {r_gen}")

    # 7. Test Experience & Notice Period Rules
    print("\n--- 7. Standard Candidate Rules ---")
    exp_ans = rag.answer_screening_question("How many years of experience in .NET / C#?")
    np_ans = rag.answer_screening_question("What is your notice period?")
    assert exp_ans == "2", f"Expected 2, got {exp_ans}"
    assert np_ans == "0", f"Expected 0, got {np_ans}"
    print(f"  [PASS] Experience YOE: {exp_ans}")
    print(f"  [PASS] Notice Period Days: {np_ans}")

    # 8. Test Previous Organization Employment (Always "No")
    print("\n--- 8. Previous Organization Employment (Always 'No') ---")
    prev_org_questions = [
        "Have you worked here in this organisation previously?",
        "Have you previously worked at this company?",
        "Were you previously employed by us?",
        "Are you a former employee of this company?",
        "Prior employment with our organisation?",
        "Have you worked for this organization in the past?"
    ]
    for q in prev_org_questions:
        ans = rag.answer_screening_question(q)
        assert ans == "No", f"Expected 'No' for '{q}', got '{ans}'"
        print(f"  [PASS] '{q}' -> {ans}")

    # 9. Test Consent & Agreement Questions (Always "Yes")
    print("\n--- 9. Consent & Agreement Questions (Always 'Yes') ---")
    consent_questions = [
        "Do you consent to the processing of your data?",
        "Do you agree to the terms and conditions?",
        "I certify that all statements made are true and complete",
        "Do you acknowledge the privacy policy?",
        "Consent to background verification check?"
    ]
    for q in consent_questions:
        ans = rag.answer_screening_question(q)
        assert ans == "Yes", f"Expected 'Yes' for '{q}', got '{ans}'"
        print(f"  [PASS] '{q}' -> {ans}")

    # 10. Test Country Code and Middle Name
    print("\n--- 10. Country Code & Middle Name Rules ---")
    cc_ans = rag.answer_screening_question("Country Code")
    mid_ans = rag.answer_screening_question("Middle Name")
    assert cc_ans == "+91", f"Expected '+91', got '{cc_ans}'"
    assert mid_ans == "", f"Expected empty string for middle name, got '{mid_ans}'"
    print(f"  [PASS] 'Country Code' -> '{cc_ans}'")
    print(f"  [PASS] 'Middle Name' -> '{mid_ans}' (Kept empty)")

    # 11. Test 7 Specific User Failure Observations
    print("\n--- 11. Verification for 7 Newly Reported Observations ---")

    # Obs 1: Commuting to job location -> ALWAYS "Yes"
    commute_qs = [
        "Are you okay commuting to job location?",
        "Are you willing to commute to this location?",
        "Can you reliably commute to work daily?",
        "Comfortable commuting to office location?"
    ]
    for q in commute_qs:
        ans = rag.answer_screening_question(q)
        assert ans == "Yes", f"Obs 1 Failed: Expected 'Yes' for '{q}', got '{ans}'"
        print(f"  [PASS Obs 1 Commute] '{q}' -> {ans}")

    # Obs 2: Job requirements / Read JD / Role eligibility -> ALWAYS "Yes"
    jd_qs = [
        "Do you meet job requirements?",
        "Did you read JD?",
        "Have you read the job description?",
        "Are you eligible for this role?",
        "Do you meet the basic qualifications?"
    ]
    for q in jd_qs:
        ans = rag.answer_screening_question(q)
        assert ans == "Yes", f"Obs 2 Failed: Expected 'Yes' for '{q}', got '{ans}'"
        print(f"  [PASS Obs 2 JD/Eligibility] '{q}' -> {ans}")

    # Obs 3: Specific technology worked on -> ALWAYS "Yes" (or "2" if numeric years)
    tech_qs = [
        "Have you worked on Python?",
        "Do you have experience with AWS?",
        "Have you worked with Docker?",
        "Hands-on experience in SQL?",
        "Knowledge of Kubernetes?"
    ]
    for q in tech_qs:
        ans = rag.answer_screening_question(q)
        assert ans == "Yes", f"Obs 3 Failed: Expected 'Yes' for '{q}', got '{ans}'"
        print(f"  [PASS Obs 3 Tech Worked On] '{q}' -> {ans}")
    tech_numeric = rag.answer_screening_question("How many years of experience in Python?", input_type="number")
    assert tech_numeric == "2", f"Obs 3 Failed: Expected '2' for YOE, got '{tech_numeric}'"
    print(f"  [PASS Obs 3 Tech YOE] 'Years in Python' -> {tech_numeric}")

    # Obs 4: Hybrid, WFO, Onsite -> ALWAYS "Yes"
    work_mode_qs = [
        "This is a hybrid role, are you okay with that?",
        "Are you comfortable with work from office (WFO)?",
        "Can you work onsite at our Bangalore office?",
        "Comfortable with hybrid setup?"
    ]
    for q in work_mode_qs:
        ans = rag.answer_screening_question(q)
        assert ans == "Yes", f"Obs 4 Failed: Expected 'Yes' for '{q}', got '{ans}'"
        print(f"  [PASS Obs 4 Work Mode] '{q}' -> {ans}")

    # Obs 5: Are you serving notice period -> ALWAYS "No"
    serving_np_qs = [
        "Are you serving notice period?",
        "Are you currently serving your notice period?",
        "Serving notice period?",
        "Are you on notice period?"
    ]
    for q in serving_np_qs:
        ans = rag.answer_screening_question(q)
        assert ans == "No", f"Obs 5 Failed: Expected 'No' for '{q}', got '{ans}'"
        print(f"  [PASS Obs 5 Serving NP] '{q}' -> {ans}")

    # Obs 6: How many days can you join (integer) -> ALWAYS "0"
    joining_qs = [
        "How many days can you join?",
        "In how many days can you join?",
        "How many days can you join (integer)?",
        "Days required to join?"
    ]
    for q in joining_qs:
        ans = rag.answer_screening_question(q)
        assert ans == "0", f"Obs 6 Failed: Expected '0' for '{q}', got '{ans}'"
        print(f"  [PASS Obs 6 Joining Days] '{q}' -> {ans}")

    # Obs 7: Location eligibility -> ALWAYS "Yes"
    loc_eligible_qs = [
        "Are you eligible to work in this location?",
        "Eligible to work in India?",
        "Authorized to work in this location?",
        "Comfortable with the job location?"
    ]
    for q in loc_eligible_qs:
        ans = rag.answer_screening_question(q)
        assert ans == "Yes", f"Obs 7 Failed: Expected 'Yes' for '{q}', got '{ans}'"
        print(f"  [PASS Obs 7 Location Eligibility] '{q}' -> {ans}")

    # Address sanity check: Explicit residence questions still return address
    residence_q = rag.answer_screening_question("What is your current location?")
    assert "Khargone" in residence_q, f"Expected Khargone in current location, got '{residence_q}'"
    print(f"  [PASS Residence Check] 'Current location' -> {residence_q}")

    print("\n" + "=" * 70)
    print("ALL VERIFICATIONS (INCLUDING 7 NEW USER OBSERVATIONS) PASSED!")
    print("=" * 70)

if __name__ == "__main__":
    test_all()

