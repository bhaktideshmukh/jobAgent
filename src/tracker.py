import sqlite3
import datetime
import re
from pathlib import Path
from typing import Dict, Any, Optional, List, Union

from src.config import DB_PATH

def extract_job_identifier(job_url: str) -> str:
    """Extracts a unique platform job key or normalized URL from a job link."""
    if not job_url:
        return ""
    url = job_url.strip()
    
    # Indeed key: jk=...
    indeed_match = re.search(r'[?&]jk=([a-zA-Z0-9]+)', url)
    if indeed_match:
        return f"indeed_{indeed_match.group(1)}"
        
    # LinkedIn key: /jobs/view/(\d+) or currentJobId=(\d+)
    li_match = re.search(r'(?:/view/|currentJobId=)(\d{8,})', url)
    if li_match:
        return f"linkedin_{li_match.group(1)}"
        
    # Generic normalization: strip query params and trailing slash
    return url.split('?')[0].rstrip('/').lower()

def init_db():
    """Initializes the SQLite application history database with proper schema."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS application_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            platform TEXT,
            title TEXT,
            company TEXT,
            location TEXT,
            job_url TEXT UNIQUE,
            job_key TEXT,
            status TEXT,
            reason TEXT,
            screenshot_path TEXT,
            applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    # Check if job_key column exists
    cursor.execute("PRAGMA table_info(application_history)")
    columns = [col[1] for col in cursor.fetchall()]
    if "job_key" not in columns:
        cursor.execute("ALTER TABLE application_history ADD COLUMN job_key TEXT")
    
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_job_key ON application_history(job_key)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_title_comp ON application_history(title, company)")
    conn.commit()
    conn.close()

def is_already_applied(job_info: Union[str, Dict[str, Any]]) -> bool:
    """
    Checks if a job has already been processed or applied.
    Accepts either a job URL string or a full job dict with {job_url, title, company}.
    Matches against job_url, normalized job_key, and (title, company).
    Prevents reapplying to jobs with status 'submitted', 'already_applied', or 'no_apply_button'.
    """
    if not job_info:
        return False
        
    init_db()
    
    job_url = ""
    title = ""
    company = ""
    
    if isinstance(job_info, dict):
        job_url = job_info.get("job_url", "")
        title = job_info.get("title", "").strip().lower()
        company = job_info.get("company", "").strip().lower()
    else:
        job_url = str(job_info).strip()
        
    job_key = extract_job_identifier(job_url)
    clean_url = job_url.split('?')[0].rstrip('/') if job_url else ""
    
    # Filter statuses that indicate the job should not be queued again
    filter_statuses = ('submitted', 'already_applied', 'no_apply_button')
    placeholders = ",".join("?" * len(filter_statuses))
    
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # 1. Match by job_key if extracted (e.g. indeed_123456 or linkedin_123456)
    if job_key:
        cursor.execute(
            f"SELECT id FROM application_history WHERE job_key = ? AND status IN ({placeholders})",
            (job_key, *filter_statuses)
        )
        if cursor.fetchone():
            conn.close()
            return True
            
    # 2. Match by exact job_url
    if job_url:
        cursor.execute(
            f"SELECT id FROM application_history WHERE job_url = ? AND status IN ({placeholders})",
            (job_url, *filter_statuses)
        )
        if cursor.fetchone():
            conn.close()
            return True

        # Only match prefix if clean_url retains unique job identifier (never for generic base paths like /viewjob)
        if clean_url and not clean_url.rstrip('/').endswith("/viewjob"):
            cursor.execute(
                f"SELECT id FROM application_history WHERE job_url LIKE ? AND status IN ({placeholders})",
                (f"{clean_url}%", *filter_statuses)
            )
            if cursor.fetchone():
                conn.close()
                return True
            
    # 3. Match by normalized (title, company) if both present
    if title and company:
        cursor.execute(
            f"SELECT id FROM application_history WHERE LOWER(title) = ? AND LOWER(company) = ? AND status IN ('submitted', 'already_applied')",
            (title, company)
        )
        if cursor.fetchone():
            conn.close()
            return True
            
    conn.close()
    return False

def record_application(
    job: Dict[str, Any],
    status: str,
    reason: str = "",
    screenshot_path: Optional[str] = None
):
    """Records an application attempt into the SQLite database."""
    init_db()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    platform = "Indeed" if "indeed.com" in job.get("job_url", "").lower() else "LinkedIn"
    title = job.get("title", "Unknown")
    company = job.get("company", "Unknown")
    location = job.get("location", "Unknown")
    job_url = job.get("job_url", "")
    job_key = extract_job_identifier(job_url)

    cursor.execute("""
        INSERT OR REPLACE INTO application_history 
        (platform, title, company, location, job_url, job_key, status, reason, screenshot_path, applied_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        platform,
        title,
        company,
        location,
        job_url,
        job_key,
        status,
        reason,
        screenshot_path,
        datetime.datetime.now().isoformat()
    ))
    conn.commit()
    conn.close()

def get_application_history() -> List[Dict[str, Any]]:
    """Returns all recorded applications."""
    init_db()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM application_history ORDER BY id DESC")
    rows = [dict(r) for r in cursor.fetchall()]
    conn.close()
    return rows
