import sys
import argparse
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.config import load_profile
from src.graph import build_job_agent_graph
from src.tracker import get_application_history

def parse_args():
    parser = argparse.ArgumentParser(
        description="LangGraph Autonomous Job Application Agent",
        epilog="Examples:\n"
               "  python main.py indeed --limit 5\n"
               "  python main.py linkedin --review\n"
               "  python main.py all --limit 10\n"
               "  python main.py --platform indeed --review",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )
    # Positional or flag platform parameter
    parser.add_argument(
        "platform_pos",
        nargs="?",
        choices=["indeed", "linkedin", "all", None],
        help="Target platform: 'indeed', 'linkedin', or 'all' (default: all)"
    )
    parser.add_argument(
        "--platform", "-p",
        choices=["indeed", "linkedin", "all"],
        default=None,
        help="Target platform flag: 'indeed', 'linkedin', or 'all'"
    )
    parser.add_argument("--auto", action="store_true", default=True, help="Automatically submit without review prompt")
    parser.add_argument("--review", dest="auto", action="store_false", help="Prompt for approval before submitting each job")
    parser.add_argument("--titles", nargs="+", help="Specific job titles to search (defaults to all job_titles in profile.yaml)")
    parser.add_argument("--locations", nargs="+", help="Specific locations to search (defaults to all locations in profile.yaml)")
    parser.add_argument("--limit", type=int, default=15, help="Maximum number of jobs to process in this run (default: 15)")
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
    
    # Platform selection: positional takes precedence, then flag, default 'all'
    target_platform = (args.platform or args.platform_pos or "all").lower()

    # Use all titles from profile.yaml unless overridden by CLI
    search_titles = args.titles if args.titles else target_search.get("job_titles", ["Software Engineer"])
    search_locations = args.locations if args.locations else target_search.get("locations", ["India"])
    max_yoe = target_search.get("max_years_experience", 3)
    limit = args.limit

    # Initial state
    initial_state = {
        "search_terms": search_titles,
        "locations": search_locations,
        "max_yoe": max_yoe,
        "platform": target_platform,
        "limit": limit,
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

    platform_display = "LinkedIn & Indeed (Both)" if target_platform == "all" else target_platform.capitalize()
    print(f"Target Platform:  {platform_display}")
    print(f"Search Criteria:  {initial_state['search_terms']} in {initial_state['locations']}")
    print(f"Experience Gate:  <= {max_yoe} YOE")
    print(f"Execution Limit:  Up to {limit} applications")
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
        applied = final_state.get('applied_jobs', [])
        submitted = [j for j in applied if j.get('status') == 'submitted']
        daily_limit = [j for j in applied if j.get('status') == 'daily_limit_reached']
        already_applied = [j for j in applied if j.get('status') == 'already_applied']
        no_apply = [j for j in applied if j.get('status') == 'no_apply_button']
        failed = [j for j in applied if j.get('status') not in ['submitted', 'already_applied', 'daily_limit_reached', 'no_apply_button']]

        print(f"Total Discovered: {final_state.get('total_discovered', 0)}")
        print(f"Submitted:        {len(submitted)}")
        print(f"Already Applied:  {len(already_applied)}")
        print(f"No Apply Button:  {len(no_apply)}")
        if daily_limit:
            print(f"Daily Limit:      {len(daily_limit)} (Platform quota reached)")
        if failed:
            print(f"Failed / Errors:  {len(failed)}")
        print(f"Skipped (YOE >3): {len(final_state.get('skipped_jobs', []))}")

        if submitted:
            print("\nSuccessfully Submitted Applications:")
            for j in submitted:
                print(f"  • {j.get('title')} @ {j.get('company')}")
                if j.get("screenshot"):
                    print(f"    Proof Screenshot: {j.get('screenshot')}")

        if daily_limit:
            print("\n[!] Platform Daily Quota Reached:")
            for j in daily_limit:
                print(f"  • {j.get('title')} @ {j.get('company')} [Daily Easy Apply limit reached for today]")

        if no_apply:
            print("\nNot Submitted (No Direct/Easy Apply button or external redirect):")
            for j in no_apply:
                print(f"  • {j.get('title')} @ {j.get('company')}")

if __name__ == "__main__":
    main()

