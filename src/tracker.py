import sqlite3
import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List

from src.config import DB_PATH

def init_db():
    """Initializes the SQLite application history database."""
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
            status TEXT,
            reason TEXT,
            screenshot_path TEXT,
            applied_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()

def is_already_applied(job_url: str) -> bool:
    """Checks if a job URL has already been processed and applied."""
    if not job_url:
        return False
    init_db()
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT id FROM application_history WHERE job_url = ? AND status = 'submitted'", (job_url,))
    row = cursor.fetchone()
    conn.close()
    return row is not None

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

    cursor.execute("""
        INSERT OR REPLACE INTO application_history 
        (platform, title, company, location, job_url, status, reason, screenshot_path, applied_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        platform,
        title,
        company,
        location,
        job_url,
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

