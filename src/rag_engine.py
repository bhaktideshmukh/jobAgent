import os
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
        if "first name" in q_lower:
            return personal.get("full_name", "").split()[0]
        if "last name" in q_lower:
            parts = personal.get("full_name", "").split()
            return parts[-1] if len(parts) > 1 else ""
        if "full name" in q_lower or q_lower == "name" or "your name" in q_lower:
            return str(personal.get("full_name", ""))

        # Contact info
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
        if any(w in q_lower for w in ["city", "current location", "location", "address", "state", "postal"]):
            city = personal.get("city", "")
            state = personal.get("state", "")
            country = personal.get("country", "")
            if "city" in q_lower and "state" not in q_lower and "country" not in q_lower:
                return city
            return f"{city}, {state}, {country}".strip(", ")

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

        # Work preferences
        if "salary" in q_lower or "compensation" in q_lower or "ctc" in q_lower:
            currency = prefs.get("currency", "INR")
            amount = prefs.get("expected_salary_usd", prefs.get("expected_salary", "1500000"))
            return f"{currency} {amount}"
        if "notice period" in q_lower or "start date" in q_lower:
            return str(prefs.get("earliest_start_date", "Immediately"))
        if "relocate" in q_lower:
            return "Yes" if prefs.get("willing_to_relocate", True) else "No"

        # Technical skill check against resume text
        # E.g. "Do you have experience with Python?" -> Check if Python is in resume
        tech_keywords = ["python", "aws", "docker", "kubernetes", "c#", ".net", "react", "sql", "git", "ci/cd", "devops"]
        matched_tech = [t for t in tech_keywords if t in q_lower]
        if matched_tech:
            found_in_resume = all(t in self.resume_text.lower() for t in matched_tech)
            if "how many years" in q_lower:
                # Based on resume profile experience
                return "2" if found_in_resume else "0"
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

