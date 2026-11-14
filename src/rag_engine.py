import os
import re
import yaml
from pathlib import Path
from typing import Dict, Any, List, Optional
import pypdf  # type: ignore

try:
    from src.config import (
        DATA_DIR, 
        RESUME_PATH, 
        COVER_LETTER_PATH, 
        PROFILE_PATH, 
        load_profile,
        get_resume_path,
        get_cover_letter_path
    )
except (ImportError, ModuleNotFoundError):
    from .config import (
        DATA_DIR, 
        RESUME_PATH, 
        COVER_LETTER_PATH, 
        PROFILE_PATH, 
        load_profile,
        get_resume_path,
        get_cover_letter_path
    )

class ProfileRAG:
    """
    RAG & Knowledge Base engine for candidate profile, resume, and cover letter.
    Answers screening questions and extracts required application details.
    """

    def __init__(self):
        self.profile_data: Dict[str, Any] = {}
        self.resume_text: str = ""
        self.cover_letter_text: str = ""
        self.reload_documents()

    def _extract_pdf_text(self, pdf_path: Path) -> str:
        """Extracts text from a given PDF file."""
        if not pdf_path.exists():
            return ""
        try:
            reader = pypdf.PdfReader(str(pdf_path))
            text = "\n".join([page.extract_text() or "" for page in reader.pages])
            return text.strip()
        except Exception as e:
            print(f"Error reading {pdf_path}: {e}")
            return ""

    def reload_documents(self):
        """Loads or reloads profile.yaml, resume, and cover letter."""
        if PROFILE_PATH.exists():
            self.profile_data = load_profile()
        
        # Load Resume
        resume_file = get_resume_path()
        if resume_file.exists():
            if resume_file.suffix.lower() == ".pdf":
                self.resume_text = self._extract_pdf_text(resume_file)
            elif resume_file.suffix.lower() in [".txt", ".md"]:
                self.resume_text = resume_file.read_text(encoding="utf-8")

        # Load Cover Letter
        cover_file = get_cover_letter_path()
        if cover_file.exists():
            if cover_file.suffix.lower() == ".pdf":
                self.cover_letter_text = self._extract_pdf_text(cover_file)
            elif cover_file.suffix.lower() in [".txt", ".md"]:
                self.cover_letter_text = cover_file.read_text(encoding="utf-8")

    def get_candidate_summary(self) -> str:
        """Returns consolidated candidate context for the LLM."""
        return f"""
--- CANDIDATE STRUCTURED PROFILE ---
{yaml.dump(self.profile_data, default_flow_style=False)}

--- RESUME TEXT ---
{self.resume_text if self.resume_text else "[Resume not attached yet]"}

--- COVER LETTER TEXT ---
{self.cover_letter_text if self.cover_letter_text else "[Cover letter not attached yet]"}
"""

    def answer_screening_question(self, question: str, input_type: str = "text") -> str:
        """
        Answers a specific application form question using structured profile + resume context.
        """
        q_lower = question.lower().strip()

        personal = self.profile_data.get("personal_info", {})
        legal = self.profile_data.get("legal_and_compliance", {})
        prefs = self.profile_data.get("work_preferences", {})

        # Name checks
        if "middle name" in q_lower or "middle initial" in q_lower:
            return ""
        if "first name" in q_lower:
            return personal.get("full_name", "").split()[0]
        if "last name" in q_lower:
            parts = personal.get("full_name", "").split()
            return parts[-1] if len(parts) > 1 else ""
        if "full name" in q_lower or q_lower == "name" or "your name" in q_lower:
            return str(personal.get("full_name", ""))

        # Contact info & Country Code
        if any(w in q_lower for w in ["country code", "calling code", "dial code", "country calling code"]):
            return personal.get("country_code", "+91")
        if "email" in q_lower:
            return str(personal.get("email", ""))
        if "phone" in q_lower or "mobile" in q_lower or "contact number" in q_lower:
            # On LinkedIn, phone input expects only the clean numeric digits without country code
            num = str(personal.get("phone", "7974065469")).replace(" ", "").replace("-", "")
            if num.startswith("+91"):
                num = num[3:]
            return num
        if "linkedin" in q_lower:
            return str(personal.get("linkedin_url", ""))
        if "github" in q_lower:
            return str(personal.get("github_url", ""))
        if "portfolio" in q_lower or "website" in q_lower:
            return str(personal.get("portfolio_url", "N/A"))

        # Date of Birth (DOB) -> 04/10/2000 in DD/MM/YYYY format
        if any(term in q_lower for term in ["date of birth", "dob", "birth date", "birthdate", "born"]):
            if "day" in q_lower:
                return "04"
            if "month" in q_lower:
                return "10"
            if "year" in q_lower:
                return "2000"
            if input_type == "date":
                return "2000-10-04"
            return str(personal.get("date_of_birth", "04/10/2000"))

        if "birth" in q_lower:
            if "day" in q_lower:
                return "04"
            if "month" in q_lower:
                return "10"
            if "year" in q_lower:
                return "2000"

        # -------------------------------------------------------------
        # TOP-PRIORITY SCREENING RULES (COMMUTE, WORK MODE, ELIGIBILITY, SPONSORSHIP)
        # Evaluated BEFORE location checks so words like "location" do not trigger address returns.
        # -------------------------------------------------------------

        # 1. Visa Sponsorship (now or in future) -> ALWAYS "Yes" per user preference
        visa_sponsorship_indicators = [
            "do you now, or will you in the future, require sponsorship",
            "do you now or will you in the future require sponsorship",
            "now, or will you in the future, require sponsorship",
            "now or will you in the future require sponsorship",
            "require sponsorship", "require visa sponsorship", "sponsorship to work in the country",
            "require sponsorship to work", "will you now or in the future require sponsorship",
            "now or in the future require sponsorship", "future require sponsorship",
            "need sponsorship", "require visa", "need visa sponsorship", "visa sponsorship",
            "require immigration sponsorship", "sponsorship now or in the future", "sponsorship for a work visa",
            "require sponsorship for employment", "require sponsorship to work in the country where this role is based",
            "require sponsorship to work in the country", "require sponsorship to work in"
        ]
        if any(ind in q_lower for ind in visa_sponsorship_indicators) or (("sponsorship" in q_lower or "visa" in q_lower) and any(w in q_lower for w in ["require", "need", "future", "now"])):
            return "Yes"

        # 2. Legal Authorization to work in country / country of hire -> ALWAYS "Yes"
        legal_auth_indicators = [
            "authorized to work in the country of hire", "country of hire",
            "legally authorized to work in the country in which this role is located",
            "legally authorized to work in the country", "legally authorized to work",
            "authorized to work in the country", "authorized to work in which this role is located",
            "legally authorized", "authorized to work in this location", "authorized to work in",
            "work authorization", "eligible to work in the country", "legally eligible to work"
        ]
        if any(ind in q_lower for ind in legal_auth_indicators):
            return "Yes"

        # 3. Commute to job location -> ALWAYS "Yes"
        commute_indicators = [
            "comfortable commuting to this job location", "comfortable commuting to job location",
            "comfortable commuting to this location", "comfortable to commute",
            "comfortable commuting", "commuting", "commute to", "okay commuting", "willing to commute", "able to commute",
            "reliably commute", "comfortably commute", "travel to the job", "commute daily",
            "willing to travel", "commute to work", "okay to commute",
            "commute to this", "commute"
        ]
        if any(ind in q_lower for ind in commute_indicators):
            return "Yes"

        # 4. Work mode (Hybrid, WFO, Onsite, 4/5 days, Hybrid setting) -> ALWAYS "Yes"
        work_mode_indicators = [
            "comfortable working all 4/5 days", "working all 4/5 days", "all 4/5 days", "all 4-5 days",
            "all 4 or 5 days", "all 5 days", "4/5 days", "4-5 days", "4 or 5 days", "5 days a week",
            "4 days a week", "5 days in office", "5 days from office", "5 days working",
            "working 4/5 days", "working 5 days", "working 4-5 days", "working 4 days",
            "hybrid setting", "hybrid setup", "hybrid model", "hybrid", "wfo", "work from office",
            "onsite", "on-site", "in-office", "in office", "work from the office", "working from office",
            "office-based", "physical office", "work in office", "work in the office",
            "work setting", "office setting"
        ]
        if any(ind in q_lower for ind in work_mode_indicators):
            return "Yes"

        # 4b. Relocation preference -> ALWAYS "Yes" (and tick checkbox)
        relocation_indicators = [
            "are you willing to relocate", "willing to relocate", "willing to relocation",
            "open to relocate", "open to relocation", "ready to relocate", "able to relocate",
            "willingness to relocate", "comfortable relocating", "relocate for this role",
            "relocate for this position", "relocate for this job", "relocate to",
            "willing to move", "open to move", "relocate", "relocation"
        ]
        if any(ind in q_lower for ind in relocation_indicators):
            return "Yes"

        # 5. Location eligibility, authorization, and comfort -> ALWAYS "Yes"
        location_eligible_indicators = [
            "eligible to work in this location", "eligible to work in", "authorized to work in this location",
            "authorized to work in", "permitted to work in this location", "permitted to work in",
            "comfortable with the job location", "comfortable with this location", "comfortable with the location",
            "willing to work in", "open to working in", "okay working in", "okay to work in",
            "can you work in", "able to work in", "work in this location", "work at this location",
            "comfortable working in", "ready to work in"
        ]
        if any(ind in q_lower for ind in location_eligible_indicators):
            return "Yes"

        # 6. Job Requirements / Read JD / Role Eligibility -> ALWAYS "Yes"
        jd_eligible_indicators = [
            "meet job requirements", "meet the job requirements", "meet requirements",
            "meet all requirements", "meet the requirements", "read jd", "read the jd",
            "read job description", "read the job description", "have you read the jd",
            "did you read", "eligible for this role", "eligible for the role",
            "eligible for this position", "eligible for this job", "eligible to apply",
            "qualified for this role", "qualified for this position", "meet minimum qualifications",
            "meet basic qualifications", "reviewed the job description",
            "understand the job requirements", "possess the required skills",
            "fulfill the criteria", "meet the criteria", "confirm you meet",
            "fit for this role"
        ]
        if any(ind in q_lower for ind in jd_eligible_indicators):
            return "Yes"

        # 7. Criminal Record / Conviction Confirmation -> ALWAYS "Yes" for declaration / confirmation, "No" if asked if convicted
        criminal_declaration_indicators = [
            "not been convicted", "no criminal proceedings", "warrant or summons",
            "warrant for arrest", "convicted by a court in india", "criminal offense and/or sentenced",
            "no criminal", "never been convicted", "have not been convicted", "not convicted",
            "no criminal record", "free of criminal", "clean criminal"
        ]
        if any(term in q_lower for term in criminal_declaration_indicators) or (q_lower.startswith("i confirm") and any(w in q_lower for w in ["convicted", "criminal", "imprisonment", "court", "warrant", "summons"])):
            return "Yes"

        if any(term in q_lower for term in [
            "have you been convicted", "have you ever been convicted", "convicted of a crime",
            "convicted of any criminal", "any criminal convictions", "criminal record", "charged with a criminal"
        ]):
            return "No"

        # 8. Suspended / Terminated for Misconduct, Fraud, Abandonment -> ALWAYS "No"
        misconduct_indicators = [
            "suspended or terminated", "misconduct, fraud", "misconduct or fraud",
            "abandonment of services", "grounds of misconduct", "terminated on the grounds",
            "suspended on the grounds", "terminated for misconduct", "terminated for cause",
            "previous employment or services suspended", "services suspended", "grounds of misconduct, fraud",
            "misconduct", "abandonment", "terminated for fraud"
        ]
        if any(ind in q_lower for ind in misconduct_indicators):
            return "No"

        # 9. Bankruptcy, Financial Delinquency, Litigation -> ALWAYS "No"
        bankruptcy_litigation_indicators = [
            "bankruptcy", "financial delinquency", "any other litigation",
            "involved in bankruptcy", "involved in litigation", "bankruptcy, financial delinquency",
            "insolvency", "delinquency or any other litigation", "financial delinquency or any other litigation",
            "financial delinquency", "litigation"
        ]
        if any(ind in q_lower for ind in bankruptcy_litigation_indicators):
            return "No"

        # -------------------------------------------------------------
        # RESIDENCE & LOCATION (STREET, CITY, STATE, PINCODE)
        # Only returned for explicit residence/address fields, NOT Yes/No questions.
        # -------------------------------------------------------------
        is_yes_no_question = any(q_lower.startswith(w) for w in ["are you", "do you", "can you", "will you", "would you", "is it okay", "have you", "were you"])
        if not is_yes_no_question:
            has_state = bool(re.search(r'\bstate\b', q_lower))
            has_city = bool(re.search(r'\bcity\b', q_lower))
            has_location_kw = any(w in q_lower for w in ["current location", "your location", "present location", "home location", "address", "street", "postal", "pincode", "zip"]) or has_state or has_city
            if has_location_kw:
                city = personal.get("city", "Khargone")
                state = personal.get("state", "Madhya Pradesh")
                country = personal.get("country", "India")
                postal = personal.get("postal_code", "451001")
                if any(w in q_lower for w in ["pincode", "postal", "zip"]):
                    return str(postal)
                if has_state and not has_city:
                    return state
                if has_city and not has_state and "country" not in q_lower:
                    return city
                return f"{city}, {state}, {country}".strip(", ")

        # Work experience details (Company, Title)
        work_exp = self.profile_data.get("work_experience", {})
        current_comp = work_exp.get("current_company", "Avalara Technologies")
        current_role = work_exp.get("current_title", "Software Engineer")

        # Questions about current employment status (Yes/No)
        if any(w in q_lower for w in ["currently employed", "currently working", "are you employed"]):
            return "Yes"

        # Rule: Previously worked here / at this organization -> ALWAYS "No"
        prev_worked_indicators = [
            "worked here", "worked at this", "previously worked", "previously employed",
            "worked for this", "worked for us", "former employee", "past employee",
            "ever worked for", "worked with this organisation", "worked in this organisation",
            "worked with this organization", "worked in this organization",
            "worked with us previously", "prior employment with", "employed here previously",
            "employed with us", "worked for the company previously", "have you worked for",
            "employed by this", "employed by us"
        ]
        if any(ind in q_lower for ind in prev_worked_indicators):
            return "No"

        # Rule: Referred by company's employee -> ALWAYS "No"
        referral_indicators = [
            "referred by", "employee referral", "referred by an employee", "referred by a current employee",
            "referred by company", "referred by someone", "were you referred", "are you referred",
            "internal referral", "referral by employee", "referral by a company", "did an employee refer you",
            "referral name", "referral employee", "who referred you", "referral details"
        ]
        if any(ind in q_lower for ind in referral_indicators):
            return "No"

        # Questions asking for Company / Employer / Organization name
        company_indicators = [
            "current company", "current employer", "present company", "present employer",
            "name of current company", "name of company", "company name", "organization name",
            "current organization", "present organization", "current firm", "employer name",
            "previous company", "past employer", "most recent employer", "name of your employer"
        ]
        if any(ind in q_lower for ind in company_indicators) or q_lower in ["company", "employer", "organization", "current company:"]:
            return current_comp

        # Role / Title / Designation
        role_indicators = ["current role", "current designation", "current title", "job title", "designation", "present title"]
        if any(ind in q_lower for ind in role_indicators):
            return current_role

        # Legal & compliance checks
        if "authorized to work" in q_lower or "legally authorized" in q_lower:
            return "Yes" if legal.get("legally_authorized_to_work", True) else "No"
        if "sponsorship" in q_lower or "require visa" in q_lower:
            return "Yes" if legal.get("require_visa_sponsorship_now_or_future", True) else "No"
        if "gender" in q_lower:
            return str(legal.get("gender", "Decline to self-identify"))
        if "race" in q_lower or "ethnicity" in q_lower:
            return str(legal.get("race_ethnicity", "Decline to self-identify"))
        if "veteran" in q_lower:
            return str(legal.get("veteran_status", "I am not a protected veteran"))
        if "disability" in q_lower:
            return str(legal.get("disability_status", "I do not have a disability"))

        # Consent, agreements, acknowledgements, certifications -> ALWAYS "Yes"
        consent_indicators = [
            "consent", "do you agree", "terms and conditions", "privacy policy",
            "certify", "acknowledge", "declaration", "i agree", "confirm that the information",
            "background check consent", "data processing consent", "agree to the terms"
        ]
        if any(ind in q_lower for ind in consent_indicators):
            return "Yes"

        # Salary / CTC checks - STRICTLY NUMERIC ONLY (no currency text, e.g. '1800000' or '15')
        if any(w in q_lower for w in ["salary", "compensation", "ctc", "remuneration", "package"]):
            curr_sal = re.sub(r"[^\d]", "", str(prefs.get("current_salary", "1500000"))) or "1500000"
            exp_sal = re.sub(r"[^\d]", "", str(prefs.get("expected_salary", "1800000"))) or "1800000"
            is_lpa = any(u in q_lower for u in ["lpa", "lakh", "lakhs", "lac", "lacs"])
            
            if any(w in q_lower for w in ["current", "present", "fixed", "existing", "drawing"]):
                if is_lpa:
                    return str(round(int(curr_sal) / 100000)) if len(curr_sal) >= 6 else curr_sal
                return curr_sal
            else:
                # Expected or generic
                if is_lpa:
                    return str(round(int(exp_sal) / 100000)) if len(exp_sal) >= 6 else exp_sal
                return exp_sal

        # -------------------------------------------------------------
        # NOTICE PERIOD & JOINING DAYS RULES
        # -------------------------------------------------------------
        # 1. Serving notice period -> ALWAYS "No"
        serving_np_indicators = [
            "serving notice period", "serving a notice period", "serving your notice period",
            "currently serving notice", "currently serving your notice", "are you serving notice",
            "are you serving your np", "serving np", "serving your np", "on notice period",
            "currently on notice", "serving notice"
        ]
        if any(ind in q_lower for ind in serving_np_indicators):
            return "No"

        # 2. How soon can you join us / availability / earliest start date -> "Immediately" (or "0" if numeric days)
        how_soon_indicators = [
            "how soon can you join", "how soon could you join", "how soon can you start",
            "when can you join", "how soon can you join us", "earliest you can join",
            "earliest you can start", "how soon would you be able to join", "how soon are you available to join"
        ]
        if any(w in q_lower for w in how_soon_indicators):
            if input_type == "number" or any(w in q_lower for w in ["days", "number of", "integer", "in days", "(integer)"]):
                return "0"
            return "Immediately"

        # 3. Immediate joiner -> ALWAYS "Yes"
        if any(w in q_lower for w in ["immediate joiner", "can you join immediately", "available to join immediately", "join immediately"]):
            return "Yes"

        # 4. How many days can you join / notice period in days -> ALWAYS "0"
        joining_days_indicators = [
            "how many days can you join", "days can you join", "in how many days can you join",
            "days required to join", "how many days to join",
            "notice period in days", "notice period (in days)", "notice period days",
            "notice days", "period in days", "days notice", "how many days notice",
            "notice period", "days left"
        ]
        if any(w in q_lower for w in joining_days_indicators):
            return "0"

        if "start date" in q_lower or "earliest start" in q_lower:
            return str(prefs.get("earliest_start_date", "Immediately"))

        # "Rate yourself" / Proficiency rating -> ALWAYS return highest integer
        rating_indicators = [
            "rate yourself", "rate your", "how would you rate", "rating on a scale",
            "scale of 1", "scale 1-5", "scale 1-10", "on a scale of", "self-rating",
            "proficiency rating", "rate your proficiency"
        ]
        if any(ind in q_lower for ind in rating_indicators):
            if "10" in q_lower:
                return "10"
            if "5" in q_lower:
                return "5"
            if "4" in q_lower:
                return "4"
            if "3" in q_lower:
                return "3"
            return "5"

        # -------------------------------------------------------------
        # EXPERIENCE & TECHNOLOGY QUESTIONS
        # -------------------------------------------------------------
        # 1. Additional Months of Experience -> ALWAYS "6"
        months_indicators = [
            "additional months of experience", "additional months", "months of experience",
            "how many months of experience", "months experience", "number of months",
            "experience in months", "total months", "remaining months", "additional month"
        ]
        if any(ind in q_lower for ind in months_indicators) or (("month" in q_lower or "months" in q_lower) and "experience" in q_lower) or q_lower in ["months", "month", "months:", "month:", "additional months", "additional months:"]:
            return "6"

        # 2. Numeric Years of Experience -> ALWAYS "2"
        years_indicators = [
            "how many years", "years of experience", "total years", "years experience",
            "number of years", "total exp", "yoe", "years of hands-on", "years hands-on"
        ]
        if any(ind in q_lower for ind in years_indicators) or q_lower in ["years", "years:", "year", "year:"]:
            return "2"

        # 2. Specific technology experience / worked on technology -> ALWAYS "Yes"
        tech_work_indicators = [
            "have you worked", "have you used", "do you have experience", "experience in",
            "experience with", "hands-on experience", "hands on experience", "familiar with",
            "knowledge of", "worked with", "worked on", "proficient in", "proficiency in",
            "experience using", "prior experience with", "prior experience in"
        ]
        if any(ind in q_lower for ind in tech_work_indicators):
            if input_type in ["number", "numeric"]:
                return "2"
            return "Yes"

        # 3. Direct technology names in questions -> ALWAYS "Yes" (or "2" if numeric)
        tech_keywords = [
            "python", "aws", "docker", "kubernetes", "c#", ".net", "react", "sql", "git",
            "ci/cd", "devops", "java", "node", "javascript", "typescript", "golang", "linux",
            "rest api", "microservices", "cloud", "terraform", "jenkins", "nosql", "mongodb",
            "postgresql", "mysql", "redis", "kafka", "azure", "gcp"
        ]
        if any(t in q_lower for t in tech_keywords):
            if input_type in ["number", "numeric"]:
                return "2"
            return "Yes"

        # -------------------------------------------------------------
        # EDUCATION & DEGREE QUESTIONS -> ALWAYS "Bachelors" (or "Yes" for confirmation)
        # -------------------------------------------------------------
        education_indicators = [
            "highest education level", "highest level of education", "highest level of education completed",
            "highest education", "education level", "level of education", "highest qualification",
            "highest degree", "highest degree completed", "highest level of education attained",
            "highest completed education", "level of education completed", "what is your highest level of education",
            "what is your highest degree", "what is your highest qualification", "degree completed",
            "degree level", "educational qualification", "educational level", "education qualification",
            "degree", "highest degree attained", "minimum education", "education background", "education"
        ]
        if any(ind in q_lower for ind in education_indicators) or (("education" in q_lower or "degree" in q_lower or "qualification" in q_lower) and any(w in q_lower for w in ["highest", "level", "completed", "attained", "hold", "your"])) or q_lower.strip(" :") in ["degree", "education", "education level", "highest education", "highest qualification", "highest degree", "level of education"]:
            if is_yes_no_question or any(q_lower.startswith(w) for w in ["do you hold", "have you obtained", "did you graduate"]):
                return "Yes"
            return "Bachelors"


        # LLM fallback if API key is configured
        gemini_api_key = os.environ.get("GEMINI_API_KEY")
        if gemini_api_key:
            try:
                from google import genai  # type: ignore
                client = genai.Client(api_key=gemini_api_key)
                prompt = f"""
You are assisting a candidate with a job application form.
Answer the following question truthfully and concisely based ONLY on the candidate's profile, resume, and cover letter.
If the answer is a simple number or Yes/No, provide just that.

Candidate Context:
{self.get_candidate_summary()}

Question: {question}
Answer:"""
                response = client.models.generate_content(
                    model='gemini-2.5-flash',
                    contents=prompt
                )
                return response.text.strip()
            except Exception as e:
                print(f"LLM generation failed: {e}")

        return "Yes"

