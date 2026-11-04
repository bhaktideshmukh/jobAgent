import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.rag_engine import ProfileRAG
from src.config import get_resume_path, get_cover_letter_path, PROFILE_PATH

def run_phase1_test():
    print("=" * 60)
    print("PHASE 1 VERIFICATION: RAG & KNOWLEDGE BASE")
    print("=" * 60)

    # 1. Check file discovery
    resume_file = get_resume_path()
    cover_file = get_cover_letter_path()

    print(f"Profile config:  {PROFILE_PATH} (Exists: {PROFILE_PATH.exists()})")
    print(f"Resume file:     {resume_file.name} (Exists: {resume_file.exists()})")
    print(f"Cover letter:    {cover_file.name} (Exists: {cover_file.exists()})")
    print("-" * 60)

    # 2. Initialize RAG
    rag = ProfileRAG()

    print(f"Resume text extracted:       {len(rag.resume_text)} characters")
    print(f"Cover letter text extracted: {len(rag.cover_letter_text)} characters")
    print("-" * 60)

    # 3. Test Screening Questions
    sample_questions = [
        "Full Name?",
        "Email address?",
        "Phone number?",
        "Current company / Employer name?",
        "Are you legally authorized to work in this country?",
        "Will you now or in the future require visa sponsorship?",
        "What is your current CTC?",
        "What is your expected salary or CTC?",
        "Current CTC (in LPA)?",
        "Rate yourself in Python on a scale of 1 to 5?",
        "Rate your communication skills (1-10)?",
        "What is your notice period or earliest start date?",
        "What is your current location / city?",
        "Do you have experience with Python / Software Engineering?"
    ]

    print("SAMPLE APPLICATION SCREENING QUESTIONS & EXTRACTED ANSWERS:\n")
    for q in sample_questions:
        answer = rag.answer_screening_question(q)
        print(f"  Q: {q}")
        print(f"  A: {answer}\n")

    print("=" * 60)
    print("Resume Snippet (First 300 chars):")
    print(rag.resume_text[:300].strip())
    print("=" * 60)

if __name__ == "__main__":
    run_phase1_test()

