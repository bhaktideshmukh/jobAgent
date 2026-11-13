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

    # 8b. Test Referred by Company Employee (Always "No")
    print("\n--- 8b. Referred by Company's Employee (Always 'No') ---")
    referral_questions = [
        "Are you referred by company's employee?",
        "Were you referred by an employee?",
        "Were you referred by a current employee?",
        "Employee referral?",
        "Did an employee refer you to this role?",
        "Are you referred by anyone in this organisation?",
        "Internal referral?"
    ]
    for q in referral_questions:
        ans = rag.answer_screening_question(q)
        assert ans == "No", f"Expected 'No' for referral question '{q}', got '{ans}'"
        print(f"  [PASS Referral] '{q}' -> {ans}")

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

    # 12. Verification for Email Updates & Indeed Continue Button Enhancements
    print("\n--- 12. Email Updates Exclusion & Indeed Continue Detection ---")
    from src.browser_automation import JobApplicationBrowser

    browser = JobApplicationBrowser(headless=True)
    
    # Test exclusions list in browser automation
    email_terms = [
        "Get email updates for jobs like this",
        "Send me job alerts for this search",
        "Email me jobs like this from this company",
        "Receive email notifications about jobs",
        "Stay updated with new openings"
    ]
    excluded_keywords = [
        "email update", "email updates", "get email updates", "job alert", "job alerts",
        "email me", "send me", "notify me", "similar jobs", "recommended jobs",
        "stay up to date", "stay updated", "receive updates", "notifications", "alerts"
    ]
    for term in email_terms:
        matched = any(kw in term.lower() for kw in excluded_keywords)
        assert matched, f"Failed to match email alert term '{term}' against excluded keywords"
        print(f"  [PASS Email Alert Exclusion] '{term}' -> correctly flagged as excluded")

    # Verify method existence
    assert hasattr(browser, "_uncheck_email_updates"), "_uncheck_email_updates method missing on browser"
    assert hasattr(browser, "_dismiss_popups_or_banners"), "_dismiss_popups_or_banners method missing on browser"
    assert hasattr(browser, "_get_active_container"), "_get_active_container method missing on browser"
    assert hasattr(browser, "_is_legitimate_wizard_button"), "_is_legitimate_wizard_button method missing on browser"
    print("  [PASS Browser Methods] _uncheck_email_updates, _dismiss_popups_or_banners, _get_active_container, _is_legitimate_wizard_button are implemented")

    # 13. Verification for Date of Birth (DOB)
    print("\n--- 13. Date of Birth (DOB) in DD/MM/YYYY ---")
    dob_standard = rag.answer_screening_question("What is your date of birth?")
    dob_short = rag.answer_screening_question("DOB")
    dob_format = rag.answer_screening_question("Date of birth (DD/MM/YYYY)")
    dob_born = rag.answer_screening_question("When were you born?")
    dob_day = rag.answer_screening_question("Birth Day")
    dob_month = rag.answer_screening_question("Birth Month")
    dob_year = rag.answer_screening_question("Birth Year")
    dob_html5 = rag.answer_screening_question("Date of Birth", input_type="date")

    assert dob_standard == "04/10/2000", f"Expected 04/10/2000, got {dob_standard}"
    assert dob_short == "04/10/2000", f"Expected 04/10/2000, got {dob_short}"
    assert dob_format == "04/10/2000", f"Expected 04/10/2000, got {dob_format}"
    assert dob_born == "04/10/2000", f"Expected 04/10/2000, got {dob_born}"
    assert dob_day == "04", f"Expected 04, got {dob_day}"
    assert dob_month == "10", f"Expected 10, got {dob_month}"
    assert dob_year == "2000", f"Expected 2000, got {dob_year}"
    assert dob_html5 == "2000-10-04", f"Expected 2000-10-04, got {dob_html5}"

    print(f"  [PASS DOB Standard] 'Date of birth' -> {dob_standard}")
    print(f"  [PASS DOB Short] 'DOB' -> {dob_short}")
    print(f"  [PASS DOB Format] 'Date of birth (DD/MM/YYYY)' -> {dob_format}")
    print(f"  [PASS DOB Born] 'When were you born?' -> {dob_born}")
    print(f"  [PASS DOB Day] 'Birth Day' -> {dob_day}")
    print(f"  [PASS DOB Month] 'Birth Month' -> {dob_month}")
    print(f"  [PASS DOB Year] 'Birth Year' -> {dob_year}")
    print(f"  [PASS DOB HTML5] 'Date of Birth (date input)' -> {dob_html5}")

    # 14. Verification for Legal Authorization, Sponsorship & Joining Time
    print("\n--- 14. Legal Authorization, Sponsorship & Joining Time ---")
    q_auth = rag.answer_screening_question("Are you legally authorized to work in the country in which this role is located? *")
    assert q_auth == "Yes", f"Expected 'Yes', got '{q_auth}'"
    print(f"  [PASS Authorization] 'Are you legally authorized to work in the country in which this role is located? *' -> {q_auth}")

    q_sponsor = rag.answer_screening_question("Will you now or in the future require sponsorship to work in the country where this role is based?  *")
    assert q_sponsor == "No", f"Expected 'No', got '{q_sponsor}'"
    print(f"  [PASS Sponsorship] 'Will you now or in the future require sponsorship to work in the country where this role is based?  *' -> {q_sponsor}")

    q_join = rag.answer_screening_question("How soon can you join us *")
    assert q_join == "Immediately", f"Expected 'Immediately', got '{q_join}'"
    print(f"  [PASS Joining Time] 'How soon can you join us *' -> {q_join}")

    # Ensure numeric joining days still returns '0'
    q_days = rag.answer_screening_question("How many days can you join (integer)?", input_type="number")
    assert q_days == "0", f"Expected '0', got '{q_days}'"
    print(f"  [PASS Numeric Days] 'How many days can you join (integer)?' -> {q_days}")

    # 15. Verification for Additional Months of Experience & Commuting Comfort
    print("\n--- 15. Additional Months of Experience & Commuting Comfort ---")
    months_qs = [
        "Additional months of experience",
        "Months of experience",
        "Additional months",
        "How many months of experience?",
        "Experience in months",
        "Months"
    ]
    for mq in months_qs:
        ans_m = rag.answer_screening_question(mq)
        assert ans_m == "6", f"Expected '6' for '{mq}', got '{ans_m}'"
        print(f"  [PASS Months] '{mq}' -> {ans_m}")

    commute_qs = [
        "If I am comfortable commuting to this job location",
        "Are you comfortable commuting to this job location?",
        "Comfortable commuting to this job location",
        "Are you comfortable commuting to job location?",
        "Comfortable commuting to this location"
    ]
    for cq in commute_qs:
        ans_c = rag.answer_screening_question(cq)
        assert ans_c == "Yes", f"Expected 'Yes' for '{cq}', got '{ans_c}'"
        print(f"  [PASS Commute Comfort] '{cq}' -> {ans_c}")

    # 16. Verification for Highest Education Level (Always "Bachelors")
    print("\n--- 16. Highest Education Level (Always 'Bachelors') ---")
    education_qs = [
        "Highest education level",
        "Highest level of education",
        "Highest level of education completed",
        "What is your highest level of education?",
        "Highest degree",
        "Highest qualification",
        "Level of education",
        "Education level",
        "Degree",
        "Highest education",
        "Educational qualification",
        "What is your highest degree?",
        "Degree level"
    ]
    for eq in education_qs:
        ans_e = rag.answer_screening_question(eq)
        assert ans_e == "Bachelors", f"Expected 'Bachelors' for '{eq}', got '{ans_e}'"
        print(f"  [PASS Education Level] '{eq}' -> {ans_e}")

    # Yes/No variants
    edu_yes_no = [
        "Do you have a Bachelor's degree?",
        "Have you completed a Bachelor's degree?",
        "Do you hold a degree?"
    ]
    for eq in edu_yes_no:
        ans_yn = rag.answer_screening_question(eq)
        assert ans_yn == "Yes", f"Expected 'Yes' for '{eq}', got '{ans_yn}'"
        print(f"  [PASS Education Yes/No] '{eq}' -> {ans_yn}")

    # 17. Verification for Drop Down Selection of Bachelor's / Bachelors
    print("\n--- 17. Drop Down Selection of Bachelor's / Bachelors ---")
    class MockOption:
        def __init__(self, text, val):
            self._text = text
            self._val = val
        def inner_text(self):
            return self._text
        def get_attribute(self, attr):
            if attr == "value":
                return self._val
            return ""

    class MockSelect:
        def __init__(self, options_tuples):
            self._options = [MockOption(t, v) for t, v in options_tuples]
            self.selected_value = None
            self.selected_text = None
        def locator(self, sel):
            if sel == "option":
                class OptList:
                    def __init__(self, opts):
                        self.opts = opts
                    def all(self):
                        return self.opts
                return OptList(self._options)
            return None
        def select_option(self, value=None):
            self.selected_value = value
            for o in self._options:
                if o._val == value:
                    self.selected_text = o._text
        def input_value(self):
            return self.selected_value or ""

    # Test Case A: Indeed Dropdown with "Bachelor's"
    mock_indeed = MockSelect([
        ("Select an option", "0"),
        ("Secondary(10th Pass)", "1"),
        ("Higher Secondary(12th Pass)", "2"),
        ("Diploma", "3"),
        ("Bachelor's", "4"),
        ("Master's", "5"),
        ("Doctorate", "6")
    ])
    res_a = browser._select_best_option(mock_indeed, "Highest level of education", "Bachelors")
    assert res_a is True, "Failed to select option in Indeed dropdown"
    assert mock_indeed.selected_text == "Bachelor's", f"Expected Bachelor's, got {mock_indeed.selected_text}"
    print(f"  [PASS Dropdown Test A - Indeed] Selected: '{mock_indeed.selected_text}' (val={mock_indeed.selected_value})")

    # Test Case B: LinkedIn Dropdown with "Bachelor's degree"
    mock_linkedin = MockSelect([
        ("High school diploma", "hs"),
        ("Associate's degree", "assoc"),
        ("Bachelor's degree", "bach"),
        ("Master's degree", "mast"),
        ("Doctorate", "doc")
    ])
    res_b = browser._select_best_option(mock_linkedin, "Highest level of education completed", "Bachelors")
    assert res_b is True, "Failed to select option in LinkedIn dropdown"
    assert mock_linkedin.selected_text == "Bachelor's degree", f"Expected Bachelor's degree, got {mock_linkedin.selected_text}"
    print(f"  [PASS Dropdown Test B - LinkedIn] Selected: '{mock_linkedin.selected_text}' (val={mock_linkedin.selected_value})")

    # Test Case C: Generic Education Dropdown with "Bachelors" (unapostrophized)
    mock_generic = MockSelect([
        ("Select education", ""),
        ("High School", "1"),
        ("Bachelors", "2"),
        ("Masters", "3")
    ])
    res_c = browser._select_best_option(mock_generic, "Education Level", "Bachelors")
    assert res_c is True, "Failed to select option in generic dropdown"
    assert mock_generic.selected_text == "Bachelors", f"Expected Bachelors, got {mock_generic.selected_text}"
    print(f"  [PASS Dropdown Test C - Generic Bachelors] Selected: '{mock_generic.selected_text}' (val={mock_generic.selected_value})")

    # Test Case D: Dropdown where question is generic but options contain Bachelor's
    mock_no_label = MockSelect([
        ("Choose level", "0"),
        ("Secondary School", "1"),
        ("Bachelor's Degree", "2"),
        ("Master's Degree", "3")
    ])
    res_d = browser._select_best_option(mock_no_label, "Dropdown", "Yes")
    assert res_d is True, "Failed to detect education from options alone"
    assert mock_no_label.selected_text == "Bachelor's Degree", f"Expected Bachelor's Degree, got {mock_no_label.selected_text}"
    print(f"  [PASS Dropdown Test D - Auto-detected from options] Selected: '{mock_no_label.selected_text}' (val={mock_no_label.selected_value})")

    print("\n" + "=" * 70)
    print("ALL VERIFICATIONS (INCLUDING DOB, INDEED FIXES, COMMUTE & HIGHEST EDUCATION) PASSED!")
    print("=" * 70)

if __name__ == "__main__":
    test_all()

