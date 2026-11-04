import sys
import argparse
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.config import load_profile
from src.graph import build_job_agent_graph
from src.tracker import get_application_history

def parse_args():
    parser = argparse.ArgumentParser(description="LangGraph Autonomous Job Application Agent")
    parser.add_argument("--auto", action="store_true", default=True, help="Automatically submit without review prompt")
    parser.add_argument("--review", dest="auto", action="store_false", help="Prompt for approval before submitting each job")
    parser.add_argument("--titles", nargs="+", help="Specific job titles to search (defaults to all job_titles in profile.yaml)")
    parser.add_argument("--locations", nargs="+", help="Specific locations to search (defaults to all locations in profile.yaml)")
    parser.add_argument("--limit", type=int, default=15, help="Maximum number of jobs to process in this run")
    parser.add_argument("--history", action="store_true", help="Print past application history and exit")
    return parser.parse_args()

def show_history():
    history = get_application_history()
    print("=" * 75)
    print(f"APPLICATION HISTORY LOG ({len(history)} entries)")
    print("=" * 75)
    if not history:
        print("No applications recorded yet.")
        return
    for item in history:
        print(f"[{item.get('status').upper():9}] {item.get('title')} @ {item.get('company')} ({item.get('platform')})")
        print(f"            Applied at: {item.get('applied_at')}")
        print(f"            URL:        {item.get('job_url')}")
        if item.get("screenshot_path"):
            print(f"            Proof:      {item.get('screenshot_path')}")
        print("-" * 75)

def main():
    args = parse_args()

    if args.history:
        show_history()
        return

    print("=" * 75)
    print("🚀 STARTING LANGGRAPH JOB APPLICATION AGENT")
    print("=" * 75)

    profile = load_profile()
    target_search = profile.get("target_search", {})
    
    # Use all titles from profile.yaml unless overridden by CLI
    search_titles = args.titles if args.titles else target_search.get("job_titles", ["Software Engineer"])
    search_locations = args.locations if args.locations else target_search.get("locations", ["India"])
    max_yoe = target_search.get("max_years_experience", 3)

    # Initial state
    initial_state = {
        "search_terms": search_titles,
        "locations": search_locations,
        "max_yoe": max_yoe,
        "auto_submit": args.auto,
        "job_queue": [],
        "current_job": None,
        "current_job_index": 0,
        "total_discovered": 0,
        "is_eligible": False,
        "eligibility_reason": "",
        "application_status": "",
        "screenshot_path": None,
        "applied_jobs": [],
        "skipped_jobs": [],
        "review_approved": True
    }

    print(f"Search Criteria:  {initial_state['search_terms']} in {initial_state['locations']}")
    print(f"Experience Gate:  <= {max_yoe} YOE")
    print(f"Execution Mode:   {'Autonomous Auto-Submit' if args.auto else 'Human-in-the-Loop Review'}")
    print("=" * 75)

    # Compile Graph
    agent = build_job_agent_graph()
    
    # Thread config for state checkpointing
    config = {"configurable": {"thread_id": "job_application_session_1"}}

    # Stream execution
    final_state = None
    for event in agent.stream(initial_state, config=config, stream_mode="values"):
        final_state = event

    print("\n" + "=" * 75)
    print("🏁 LANGGRAPH EXECUTION COMPLETE")
    print("=" * 75)
    if final_state:
        print(f"Total Discovered: {final_state.get('total_discovered', 0)}")
        print(f"Applied Jobs:     {len(final_state.get('applied_jobs', []))}")
        print(f"Skipped Jobs:     {len(final_state.get('skipped_jobs', []))}")

        if final_state.get("applied_jobs"):
            print("\nSuccessfully Applied To:")
            for j in final_state.get("applied_jobs"):
                print(f"  • {j.get('title')} @ {j.get('company')} [{j.get('status')}]")
                if j.get("screenshot"):
                    print(f"    Screenshot: {j.get('screenshot')}")

if __name__ == "__main__":
    main()

