import os
from pathlib import Path
import yaml
from typing import Dict, Any
from dotenv import load_dotenv

# Base directories
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")
DATA_DIR = BASE_DIR / "data"
LOGS_DIR = BASE_DIR / "logs"
BROWSER_USER_DATA_DIR = BASE_DIR / "browser_profile"
DB_PATH = BASE_DIR / "applications.db"

def get_resume_path() -> Path:
    """Finds candidate resume file (PDF/DOCX) dynamically."""
    # Check exact default
    default = DATA_DIR / "resume.pdf"
    if default.exists():
        return default
    # Search for files with 'resume' in name
    for ext in ["*.pdf", "*.docx"]:
        matches = list(DATA_DIR.glob(f"*{ext}"))
        for match in matches:
            if "resume" in match.name.lower():
                return match
    # Fallback to any PDF in data that is not a cover letter
    for pdf in DATA_DIR.glob("*.pdf"):
        if "cover" not in pdf.name.lower():
            return pdf
    return default

def get_cover_letter_path() -> Path:
    """Finds candidate cover letter file (PDF/DOCX) dynamically."""
    default = DATA_DIR / "cover_letter.pdf"
    if default.exists():
        return default
    for ext in ["*.pdf", "*.docx", "*.txt"]:
        for match in DATA_DIR.glob(f"*{ext}"):
            if "cover" in match.name.lower():
                return match
    return default

RESUME_PATH = get_resume_path()
COVER_LETTER_PATH = get_cover_letter_path()
PROFILE_PATH = DATA_DIR / "profile.yaml"

def load_profile() -> Dict[str, Any]:
    """Loads candidate profile configuration from YAML."""
    if not PROFILE_PATH.exists():
        raise FileNotFoundError(f"Profile config not found at {PROFILE_PATH}")
    with open(PROFILE_PATH, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

