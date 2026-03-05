"""
Tennis Steamer Alert Agent — Entry Point

Usage:
  python main.py           # Run continuously every 45 minutes, 09:00–22:00
  python main.py --once    # Single cycle then exit (for testing)

Prerequisites:
  export ODDS_API_KEY="your_key_here"
  export GMAIL_APP_PASSWORD="your_16_char_app_password"
  (or set directly in config.py)

Gmail App Password setup:
  Google Account → Security → 2-Step Verification → App Passwords
  Generate for "Mail / Windows Computer"
"""

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

# Ensure project root is on sys.path when running as a script
sys.path.insert(0, str(Path(__file__).parent))

import config
from src.models import DatabaseManager
from src.scheduler import run_cycle


def setup_logging() -> None:
    # Ensure stdout handles UTF-8 player names on Windows
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    config.DATA_DIR.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(str(config.LOG_PATH), encoding="utf-8"),
        ],
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Tennis Steamer Alert Agent")
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run a single cycle then exit (useful for testing)",
    )
    args = parser.parse_args()

    setup_logging()
    logger = logging.getLogger("main")

    logger.info("Tennis Steamer Agent starting up")
    logger.info("  Scrape interval : %d minutes", config.SCRAPE_INTERVAL_MINUTES)
    logger.info("  Active hours    : %02d:00–%02d:00 local", config.ACTIVE_HOURS_START, config.ACTIVE_HOURS_END)
    logger.info("  Steam threshold : %.1f%% normalized", config.STEAM_THRESHOLD_PCT)
    logger.info("  Email target    : %s", config.EMAIL_TO)
    logger.info("  Email enabled   : %s", config.EMAIL_ENABLED)
    logger.info("  DB path         : %s", config.DB_PATH)

    if not config.ODDS_API_KEY:
        logger.warning(
            "ODDS_API_KEY is not set! "
            "Set the ODDS_API_KEY environment variable or edit config.py. "
            "Get a free key at https://the-odds-api.com"
        )

    if config.EMAIL_ENABLED and not config.EMAIL_APP_PASSWORD:
        logger.warning(
            "GMAIL_APP_PASSWORD is not set — emails will be skipped. "
            "Set the GMAIL_APP_PASSWORD environment variable or edit config.py."
        )

    db = DatabaseManager(config.DB_PATH)
    db.create_tables()

    if args.once:
        logger.info("--once flag: running single cycle")
        run_cycle(db)
        db.close()
        logger.info("Single cycle complete. Exiting.")
        return

    # Continuous scheduling
    try:
        from apscheduler.schedulers.blocking import BlockingScheduler
        from apscheduler.triggers.interval import IntervalTrigger
    except ImportError:
        logger.error(
            "APScheduler not installed. Run: .venv/Scripts/pip install apscheduler"
        )
        sys.exit(1)

    # Anchor schedule to 9:00am Irish time (Europe/Dublin handles GMT/IST automatically)
    from datetime import date, time as dtime
    from zoneinfo import ZoneInfo
    dublin_tz = ZoneInfo("Europe/Dublin")
    today_9am = datetime.combine(date.today(), dtime(config.ACTIVE_HOURS_START, 0, 0), tzinfo=dublin_tz)

    scheduler = BlockingScheduler(timezone=dublin_tz)
    scheduler.add_job(
        run_cycle,
        IntervalTrigger(
            minutes=config.SCRAPE_INTERVAL_MINUTES,
            start_date=today_9am,
        ),
        args=[db],
        id="tennis_scrape",
        max_instances=1,        # never overlap cycles
        misfire_grace_time=120, # allow up to 2-min delay before skipping
    )

    logger.info(
        "Scheduler started — every %d minutes from 09:00. Press Ctrl+C to stop.",
        config.SCRAPE_INTERVAL_MINUTES,
    )

    # Run immediately on startup, then let the scheduler take over
    logger.info("Running immediate startup cycle...")
    run_cycle(db)

    try:
        scheduler.start()
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received — shutting down gracefully.")
    finally:
        try:
            scheduler.shutdown(wait=False)
        except Exception:
            pass
        db.close()
        logger.info("Shutdown complete.")


if __name__ == "__main__":
    main()
