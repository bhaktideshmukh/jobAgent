import os
from typing import TypedDict, List, Dict, Any, Optional

class ApplicationState(TypedDict):
    """
    Main state schema for the LangGraph Job Application Agent.
    """
    # Search parameters
    search_terms: List[str]
    locations: List[str]
    max_yoe: int

    # Job queues
    job_queue: List[Dict[str, Any]]
    current_job: Optional[Dict[str, Any]]
    current_job_index: int
    total_discovered: int

    # Evaluation & Automation flags
    is_eligible: bool
    eligibility_reason: str
    application_status: str
    screenshot_path: Optional[str]

    # Audit records
    applied_jobs: List[Dict[str, Any]]
    skipped_jobs: List[Dict[str, Any]]
    
    # Control flags
    auto_submit: bool
    review_approved: bool

