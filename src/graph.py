import os
import sys
from pathlib import Path
from typing import Dict, Any, Literal
from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver
from langgraph.types import interrupt

from src.state import ApplicationState
from src.job_filter import fetch_easy_apply_jobs, is_experience_eligible
from src.browser_automation import JobApplicationBrowser
from src.tracker import is_already_applied, record_application
from src.config import load_profile

# -------------------------------------------------------------
# GRAPH NODE IMPLEMENTATIONS
# -------------------------------------------------------------

def discover_jobs_node(state: ApplicationState) -> Dict[str, Any]:
    """
    Node 1: Fetches live Easy Apply jobs from LinkedIn & Indeed
    matching target search criteria from profile.yaml, filtering out previously applied roles.
    """
    profile = load_profile()
    target_search = profile.get("target_search", {})
    profile_titles = target_search.get("job_titles", ["Software Engineer"])
    profile_locations = target_search.get("locations", ["India"])
    profile_yoe = target_search.get("max_years_experience", 3)

    search_terms = state.get("search_terms") or profile_titles
    locations = state.get("locations") or profile_locations
    max_yoe = state.get("max_yoe") or profile_yoe
    platform_pref = (state.get("platform") or "all").lower()
    limit = state.get("limit") or 15

    target_platforms = [platform_pref] if platform_pref in ["indeed", "linkedin"] else ["indeed", "linkedin"]

    print("\n" + "=" * 70)
    print(f"[LangGraph Node: DISCOVER JOBS]")
    print(f"Target Platforms: {', '.join(p.capitalize() for p in target_platforms)}")
    print(f"Target Titles:    {search_terms}")
    print(f"Target Locations: {locations}")
    print(f"Max YOE Barrier:  <= {max_yoe} years")
    print(f"Queue Limit:      {limit} jobs")
    print("=" * 70)

    results_wanted = max(limit * 2, 20)
    raw_jobs = fetch_easy_apply_jobs(
        search_terms=search_terms,
        locations=locations,
        platforms=target_platforms,
        results_per_query=results_wanted,
        hours_old=168,
        max_yoe=max_yoe
    )

    # Filter out jobs that were already applied previously
    unapplied_queue = []
    for job in raw_jobs:
        if not is_already_applied(job):
            unapplied_queue.append(job)
            if len(unapplied_queue) >= limit:
                break
        else:
            print(f"Skipping already applied job: {job.get('title')} @ {job.get('company')}")

    print(f"Total New Eligible Jobs Queued: {len(unapplied_queue)}")
    return {
        "job_queue": unapplied_queue,
        "total_discovered": len(unapplied_queue),
        "current_job_index": 0,
        "applied_jobs": [],
        "skipped_jobs": []
    }

def select_next_job_node(state: ApplicationState) -> Dict[str, Any]:
    """
    Node 2: Pulls the next job from the queue, discarding any that have already been applied.
    """
    queue = list(state.get("job_queue", []))

    while queue and is_already_applied(queue[0]):
        skipped = queue.pop(0)
        print(f"Skipping already applied job in queue: {skipped.get('title')} @ {skipped.get('company')}")

    if not queue:
        print("\n[LangGraph Node: SELECT JOB] No more jobs remaining in the queue.")
        return {"current_job": None, "job_queue": []}

    next_job = queue[0]
    remaining_queue = queue[1:]
    idx = state.get("current_job_index", 0) + 1

    print("\n" + "-" * 70)
    print(f"[LangGraph Node: SELECT JOB #{idx}]")
    print(f"Role:     {next_job.get('title')} @ {next_job.get('company')}")
    print(f"Platform: {'Indeed' if 'indeed.com' in next_job.get('job_url', '') else 'LinkedIn'}")
    print(f"URL:      {next_job.get('job_url')}")
    print("-" * 70)

    return {
        "current_job": next_job,
        "job_queue": remaining_queue,
        "current_job_index": idx,
        "review_approved": True
    }

def filter_experience_node(state: ApplicationState) -> Dict[str, Any]:
    """
    Node 3: Enforces strict <= 3 YOE qualification rules.
    """
    job = state.get("current_job")
    if not job:
        return {"is_eligible": False, "eligibility_reason": "No job selected"}

    max_yoe = state.get("max_yoe", 3)
    eligible, reason = is_experience_eligible(job, max_yoe_allowed=max_yoe)

    print(f"[LangGraph Node: EXPERIENCE FILTER] Eligible: {eligible} | {reason}")

    if not eligible:
        record_application(job, status="skipped", reason=reason)
        skipped = state.get("skipped_jobs", [])
        skipped.append({"job": job, "reason": reason})
        return {
            "is_eligible": False,
            "eligibility_reason": reason,
            "skipped_jobs": skipped
        }

    return {
        "is_eligible": True,
        "eligibility_reason": reason
    }

def review_checkpoint_node(state: ApplicationState) -> Dict[str, Any]:
    """
    Node 4: Human-in-the-Loop review checkpoint before launching browser application.
    Uses LangGraph's native interrupt() primitive when auto_submit=False.
    """
    job = state.get("current_job")
    auto_submit = state.get("auto_submit", True)

    if not auto_submit:
        # Pause graph execution and wait for user approval
        user_response = interrupt({
            "message": f"Review application for {job.get('title')} @ {job.get('company')}",
            "job_url": job.get("job_url"),
            "prompt": "Proceed with application? (yes/no)"
        })
        
        approved = False
        if isinstance(user_response, dict):
            approved = user_response.get("approved", True)
        elif isinstance(user_response, str):
            approved = user_response.lower().strip() in ["yes", "y", "true", "proceed"]

        return {"review_approved": approved}

    return {"review_approved": True}

def apply_job_node(state: ApplicationState) -> Dict[str, Any]:
    """
    Node 5: Launches Playwright browser automation to fill forms & submit.
    """
    job = state.get("current_job")
    approved = state.get("review_approved", True)

    if not approved:
        print("[LangGraph Node: APPLY] Application skipped by user.")
        record_application(job, status="skipped_by_user", reason="User declined in review checkpoint")
        return {"application_status": "skipped_by_user"}

    print(f"[LangGraph Node: APPLY] Executing browser automation for: {job.get('title')}...")
    browser = JobApplicationBrowser(headless=False)
    
    result = browser.process_application(
        job_url=job.get("job_url"),
        auto_submit=state.get("auto_submit", True)
    )
    browser.close()

    status = result.get("status", "failed")
    error_msg = result.get("error", "")
    if "No Direct / Easy Apply button" in str(error_msg):
        status = "no_apply_button"
    elif "daily Easy Apply limit reached" in str(error_msg) or status == "daily_limit_reached":
        status = "daily_limit_reached"

    screenshot = result.get("screenshot_path")
    record_application(job, status=status, reason=error_msg, screenshot_path=screenshot)

    applied = state.get("applied_jobs", [])
    applied.append({
        "title": job.get("title"),
        "company": job.get("company"),
        "url": job.get("job_url"),
        "status": status,
        "screenshot": screenshot
    })

    print(f"[LangGraph Node: APPLY] Finished with status: {status.upper()}")
    return {
        "application_status": status,
        "screenshot_path": screenshot,
        "applied_jobs": applied
    }

# -------------------------------------------------------------
# CONDITIONAL ROUTING FUNCTIONS
# -------------------------------------------------------------

def route_after_selection(state: ApplicationState) -> Literal["filter_experience", "__end__"]:
    """Routes to filter if a job is active, else terminates graph."""
    if state.get("current_job") is not None:
        return "filter_experience"
    return END

def route_after_filter(state: ApplicationState) -> Literal["review_checkpoint", "select_next_job"]:
    """Routes to review if job is eligible, else moves to next job."""
    if state.get("is_eligible", False):
        return "review_checkpoint"
    return "select_next_job"

def route_after_review(state: ApplicationState) -> Literal["apply_job", "select_next_job"]:
    """Routes to apply if approved, else skips to next job."""
    if state.get("review_approved", False):
        return "apply_job"
    return "select_next_job"

# -------------------------------------------------------------
# GRAPH COMPILATION
# -------------------------------------------------------------

def build_job_agent_graph():
    """Builds and compiles the LangGraph StateGraph."""
    workflow = StateGraph(ApplicationState)

    # Add Nodes
    workflow.add_node("discover_jobs", discover_jobs_node)
    workflow.add_node("select_next_job", select_next_job_node)
    workflow.add_node("filter_experience", filter_experience_node)
    workflow.add_node("review_checkpoint", review_checkpoint_node)
    workflow.add_node("apply_job", apply_job_node)

    # Add Edges
    workflow.add_edge(START, "discover_jobs")
    workflow.add_edge("discover_jobs", "select_next_job")

    workflow.add_conditional_edges(
        "select_next_job",
        route_after_selection,
        {
            "filter_experience": "filter_experience",
            END: END
        }
    )

    workflow.add_conditional_edges(
        "filter_experience",
        route_after_filter,
        {
            "review_checkpoint": "review_checkpoint",
            "select_next_job": "select_next_job"
        }
    )

    workflow.add_conditional_edges(
        "review_checkpoint",
        route_after_review,
        {
            "apply_job": "apply_job",
            "select_next_job": "select_next_job"
        }
    )

    # After applying, loop back to select the next job in the queue
    workflow.add_edge("apply_job", "select_next_job")

    # Compile with memory checkpointing for state persistence
    checkpointer = MemorySaver()
    app = workflow.compile(checkpointer=checkpointer)
    return app

