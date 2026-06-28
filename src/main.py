#!/usr/bin/env python3
"""
LinkedIn Resume Agent — main entry point.

Searches for Senior Software Developer / Tech Lead roles at geospatial
companies (priority 1: outside India, priority 2: India — excluding
SatSure and SkyServe) and logs matching opportunities.

Usage:
    python -m src.main                       # full pipeline
    python -m src.main --dry-run             # default: dry run
    python -m src.main --apply               # open apply links in browser
    python -m src.main --list-only           # just list matching jobs
"""

import argparse
import logging
import sys
import os

# Ensure project root is on the path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.mcp.mcp import MCP
from src.utils.config import load_config, setup_logging
   

def parse_args():
    parser = argparse.ArgumentParser(
        description="LinkedIn Resume Agent — find & apply to geospatial jobs"
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Actually open job apply links in the browser (disables dry-run)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Run the full pipeline but only log results (default)",
    )
    parser.add_argument(
        "--list-only",
        action="store_true",
        help="Only scrape and list jobs; skip application step",
    )
    parser.add_argument(
        "--max-results",
        type=int,
        default=None,
        help="Override max results per search query",
    )
    parser.add_argument(
        "--location",
        type=str,
        default=None,
        help="Override search to a single location",
    )
    parser.add_argument(
        "--max-jobs",
        type=int,
        default=None,
        help="Maximum total jobs to process/apply to (default: 10)",
    )
    parser.add_argument(
        "--telegram",
        action="store_true",
        help="Enable Telegram notifications (sends jobs + tailored resumes to your channel)",
    )
    parser.add_argument(
        "--setup-telegram",
        action="store_true",
        help="Interactive setup: configure Telegram bot token and chat ID",
    )
    parser.add_argument(
        "--login-only",
        action="store_true",
        help="Just open browser for LinkedIn login setup (saves session for future runs)",
    )
    parser.add_argument(
        "--crew",
        action="store_true",
        help="Enable CrewAI agents with SerperDevTool for web-wide job search (requires SERPER_API_KEY)",
    )
    parser.add_argument(
        "--connect",
        metavar="PROFILES_CSV",
        type=str,
        default=None,
        help=(
            "Send LinkedIn connection requests. "
            "Pass a CSV file with columns: url, note (note is optional). "
            "Example: --connect profiles_to_connect.csv"
        ),
    )
    parser.add_argument(
        "--connect-dry-run",
        action="store_true",
        help="Preview connection requests from --connect CSV without actually sending them",
    )
    return parser.parse_args()


def main():
    config = load_config()
    setup_logging(config)
    logger = logging.getLogger(__name__)

    args = parse_args()

    # Handle --connect
    if args.connect:
        _run_connect(config, args.connect, dry_run=args.connect_dry_run)
        return

    # Handle --setup-telegram
    if args.setup_telegram:
        _setup_telegram(config)
        return

    # Handle --login-only
    if args.login_only:
        from src.submitters.linkedin_easy_apply import login_only
        login_only(config)
        return

    # Enable Telegram if --telegram flag is passed
    if args.telegram:
        config.setdefault("telegram", {})["enabled"] = True
        logger.info("📱 Telegram notifications ENABLED")

    # Enable CrewAI if --crew is passed
    if args.crew:
        config.setdefault("crewai", {})["enabled"] = True
        logger.info("🤖 CrewAI agents ENABLED — web-wide search via SerperDevTool")

    # Override dry_run if --apply is passed
    if args.apply:
        config["application_submitter"]["dry_run"] = False
        logger.info("🚀 LIVE MODE — will open apply links in browser")
    else:
        config.setdefault("application_submitter", {})["dry_run"] = True
        logger.info("🔍 DRY-RUN MODE — logging results only")

    # Runtime overrides
    criteria_overrides = {}
    if args.max_results:
        criteria_overrides["max_results_per_search"] = args.max_results
    if args.location:
        criteria_overrides["locations"] = [{"name": args.location, "priority": 1}]

    logger.info("=" * 60)
    logger.info("  LinkedIn Resume Agent — Job Search Pipeline")
    logger.info("  Target: Senior Software Developer / Tech Lead")
    logger.info("  Focus: Geospatial companies worldwide")
    logger.info("  Excluded: SatSure, SkyServe")
    if config.get("crewai", {}).get("enabled"):
        logger.info("  🤖 CrewAI: Web-wide search ENABLED")
    logger.info("=" * 60)

    mcp = MCP(config)

    if args.list_only:
        # Just scrape and list — don't submit
        from src.scrapers.job_scraper import JobScraper
        from src.analyzers.job_analyzer import JobAnalyzer

        scraper = JobScraper(config)
        analyzer = JobAnalyzer(config)
        raw = scraper.search_jobs(criteria_overrides or None)
        filtered = scraper.filter_jobs(
            raw,
            {"excluded_companies": config.get("job_search", {}).get("excluded_companies", [])},
        )
        ranked = analyzer.rank_jobs(filtered)
        print(f"\n{'='*70}")
        print(f"  Found {len(ranked)} matching jobs")
        print(f"{'='*70}\n")
        for i, job in enumerate(ranked[:30], 1):
            geo = "🌍 GEOSPATIAL" if job.is_geospatial else ""
            print(
                f"  {i:2d}. [P{job.priority}] {job.title}\n"
                f"      {job.company} — {job.location}  {geo}\n"
                f"      Score: {job.relevance_score:.1f}  |  Skills: {', '.join(job.matched_skills)}\n"
                f"      {job.url}\n"
            )
    else:
        max_jobs = args.max_jobs or 10  # default to 10 jobs
        ranked = mcp.search_and_apply(criteria_overrides or None, max_jobs=max_jobs)
        print(f"\n✅ Pipeline complete — {len(ranked)} jobs found, top {max_jobs} processed.")
        print(f"   See output/applications_log.csv for details.")
        if config.get("telegram", {}).get("enabled"):
            print(f"   📱 Jobs + tailored resumes sent to your Telegram channel!")
        print(f"   📎 Tailored PDFs saved in output/resumes/\n")


def _setup_telegram(config: dict) -> None:
    """Interactive Telegram setup wizard."""
    import yaml

    print("\n" + "=" * 60)
    print("  📱 Telegram Bot Setup Wizard")
    print("=" * 60)
    print("\nFollow these steps:")
    print("  1. Open Telegram and message @BotFather")
    print("  2. Send /newbot and follow the prompts")
    print("  3. Copy the bot token you receive")
    print("  4. Create a channel/group and add the bot as admin")
    print("  5. Send any message to the channel")
    print("  6. Visit: https://api.telegram.org/bot<TOKEN>/getUpdates")
    print("  7. Find the chat ID in the response\n")

    token = input("Enter your bot token: ").strip()
    chat_id = input("Enter your chat ID (e.g. -1001234567890): ").strip()

    if not token or not chat_id:
        print("\n❌ Both token and chat_id are required. Aborting.")
        return

    # Test the connection
    print("\n🔄 Testing connection…")
    from src.notifiers.telegram_notifier import TelegramNotifier
    test_config = {"telegram": {"enabled": True, "bot_token": token, "chat_id": chat_id}}
    notifier = TelegramNotifier(test_config)
    if notifier.send_test_message():
        print("✅ Test message sent successfully!")
    else:
        print("❌ Failed to send test message. Check your token and chat_id.")
        return

    # Update the config file
    config_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "config", "settings.yaml",
    )
    with open(config_path, "r") as f:
        raw = f.read()

    raw = raw.replace('enabled: false', 'enabled: true')
    raw = raw.replace('bot_token: ""', f'bot_token: "{token}"')
    raw = raw.replace('chat_id: ""', f'chat_id: "{chat_id}"')

    with open(config_path, "w") as f:
        f.write(raw)

    print(f"\n✅ Config saved to {config_path}")
    print("   You can now run: python -m src.main --telegram")
    print()


def _run_connect(config: dict, csv_path: str, dry_run: bool = False) -> None:
    """Load a CSV of profiles and send LinkedIn connection requests."""
    import csv as csv_module

    if not os.path.exists(csv_path):
        print(f"\n❌ File not found: {csv_path}")
        print("   Create a CSV with columns: url, note")
        print("   Example row: https://www.linkedin.com/in/someone/,Hi I'd love to connect!\n")
        return

    profiles = []
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv_module.DictReader(f)
        for row in reader:
            url = row.get("url", "").strip()
            note = row.get("note", "").strip() or None
            if url:
                profiles.append({"url": url, "note": note})

    if not profiles:
        print(f"\n❌ No valid profiles found in {csv_path}\n")
        return

    max_per_run = config.get("linkedin_connect", {}).get("max_per_run", 10)
    print(f"\n{'='*60}")
    print(f"  LinkedIn Connection Requests")
    print(f"  Profiles loaded : {len(profiles)}")
    print(f"  Cap per run     : {max_per_run}")
    print(f"  Mode            : {'DRY-RUN' if dry_run else 'LIVE'}")
    print(f"{'='*60}\n")

    from src.submitters.linkedin_connect import LinkedInConnect

    with LinkedInConnect(config) as connector:
        if not dry_run:
            if not connector.ensure_logged_in():
                print("\n❌ Could not log in to LinkedIn. Run --login-only first.\n")
                return

        summary = connector.connect_batch(profiles, dry_run=dry_run)

    print(f"\n{'='*60}")
    print(f"  Connection requests complete")
    print(f"  Sent             : {summary['sent']}")
    print(f"  Already connected: {summary['already_connected']}")
    print(f"  Skipped          : {summary['skipped']}")
    print(f"  Failed           : {summary['failed']}")
    print(f"  Log              : output/connections_log.csv")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()