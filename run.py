"""
Entry point for the Opportunity Intelligence Agent.

Usage:
  python run.py              # Start the web UI
  python run.py --scrape     # Run a one-off scrape now (no web UI)
  python run.py --brief      # Regenerate this month's brief (no web UI)
  python run.py --score <id> # Re-score a specific opportunity by ID
"""
import sys
import logging
import argparse

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="Opportunity Intelligence Agent")
    parser.add_argument("--scrape", action="store_true", help="Run a scrape now")
    parser.add_argument("--brief", action="store_true", help="Regenerate this month's brief")
    parser.add_argument("--sources", nargs="*", help="Specific source IDs to scrape")
    parser.add_argument("--port", type=int, default=None, help="Override port")
    parser.add_argument("--no-scheduler", action="store_true", help="Disable background scheduler")
    args = parser.parse_args()

    from app import create_app
    from config import Config

    app = create_app()

    if args.scrape:
        logger.info("Running one-off scrape...")
        with app.app_context():
            from scheduler import _run_scrape_in_context
            summary = _run_scrape_in_context(source_ids=args.sources)
            logger.info(f"Scrape complete: {summary}")
        return

    if args.brief:
        logger.info("Regenerating intelligence brief...")
        with app.app_context():
            from scheduler import _generate_monthly_brief
            _generate_monthly_brief()
        return

    # Start web server
    if not args.no_scheduler:
        from scheduler import start_scheduler
        start_scheduler(app)

    port = args.port or Config.PORT
    logger.info(f"Starting Opportunity Agent UI at http://localhost:{port}")
    logger.info("Press Ctrl+C to stop")

    app.run(
        host="0.0.0.0",
        port=port,
        debug=Config.DEBUG,
        use_reloader=False,  # reloader conflicts with APScheduler
    )


if __name__ == "__main__":
    main()
