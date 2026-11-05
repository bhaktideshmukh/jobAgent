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

    def answer_screening_question(self, question: str) -> str:
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

        # Location checks
        has_state = bool(re.search(r'\bstate\b', q_lower))
        has_city = bool(re.search(r'\bcity\b', q_lower))
        has_location_kw = any(w in q_lower for w in ["current location", "location", "address", "postal", "pincode", "zip"]) or has_state or has_city
        if has_location_kw:
            city = personal.get("city", "")
            state = personal.get("state", "")
            country = personal.get("country", "")
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
            return "Yes" if legal.get("require_visa_sponsorship_now_or_future", False) else "No"
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

        # Notice period / Immediate joiner / Serving NP / Days left -> Always '0'
        np_indicators = [
            "serving your np", "notice period", "immediate joiner", "days left",
            "np or", "serving np", "how many days notice", "notice days", "period in days"
        ]
        if any(w in q_lower for w in np_indicators):
            return "0"

        if "start date" in q_lower or "earliest start" in q_lower:
            return str(prefs.get("earliest_start_date", "Immediately"))
        if "relocate" in q_lower:
            return "Yes" if prefs.get("willing_to_relocate", True) else "No"

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

        # USER RULE: Any experience / years question in any technology -> ALWAYS return "2"
        exp_question_indicators = [
            "how many years", "years of experience", "total exp", "exp in", 
            "experience in", "experience with", "years experience", "yoe",
            "hands-on experience", "relevant experience", "work experience"
        ]
        if any(ind in q_lower for ind in exp_question_indicators):
            return "2"

        # Education degree
        if any(w in q_lower for w in ["degree", "highest qualification", "highest education", "education level"]):
            return "Bachelor's Degree"

        # Technical skill check against resume text
        tech_keywords = ["python", "aws", "docker", "kubernetes", "c#", ".net", "react", "sql", "git", "ci/cd", "devops"]
        matched_tech = [t for t in tech_keywords if t in q_lower]
        if matched_tech:
            found_in_resume = all(t in self.resume_text.lower() for t in matched_tech)
            if found_in_resume:
                return "Yes"

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

