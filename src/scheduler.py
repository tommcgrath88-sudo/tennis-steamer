"""
Single cycle orchestration logic.
Called by main.py both on startup and on the APScheduler interval.
"""

import logging
from datetime import datetime, timezone, timedelta

import config
from src.emailer import send_report
from src.models import DatabaseManager
from src.reporter import cleanup_old_reports, generate_report, save_report
from src.scraper import fetch_injury_news, get_tennis_odds, match_injury_to_players
from src.steam import detect_steam, detect_surface_mismatches

logger = logging.getLogger(__name__)


def run_cycle(db: DatabaseManager) -> None:
    """
    One full scrape → detect → report → email cycle.
    Wrapped in a broad try/except so a transient failure never kills the scheduler.
    """
    try:
        _run_cycle_inner(db)
    except Exception as exc:
        logger.exception("Unhandled error in cycle — will retry next interval: %s", exc)


def _in_active_hours() -> bool:
    """Returns True if current Irish time is within the configured active window."""
    from zoneinfo import ZoneInfo
    hour = datetime.now(ZoneInfo("Europe/Dublin")).hour
    return config.ACTIVE_HOURS_START <= hour < config.ACTIVE_HOURS_END


def _run_cycle_inner(db: DatabaseManager) -> None:
    now = datetime.now(timezone.utc)

    if not _in_active_hours():
        local_now = datetime.now()
        logger.info(
            "Outside active hours (%02d:00–%02d:00 local). Current local time: %s. Skipping.",
            config.ACTIVE_HOURS_START, config.ACTIVE_HOURS_END,
            local_now.strftime("%H:%M"),
        )
        return

    logger.info("=== Cycle start %s ===", now.strftime("%Y-%m-%d %H:%M UTC"))

    # Step 1: Fetch current odds
    matches = get_tennis_odds()
    logger.info("Fetched %d tennis matches", len(matches))

    # Step 2: Persist to DB (upsert match + insert odds snapshot)
    for m in matches:
        db.upsert_match(m)
        db.insert_odds(m)

    # Step 3: Detect steam moves
    alerts = detect_steam(matches, db)

    # Step 4: Persist alerts
    for a in alerts:
        db.insert_steam_alert(a)

    # Step 5: Pro signals — surface mismatches
    surface_mismatches = detect_surface_mismatches(matches)

    # Step 6: Pro signals — injury news
    injury_headlines = fetch_injury_news()
    injury_flags = match_injury_to_players(injury_headlines, matches)

    # Step 7: Generate markdown report
    report_md = generate_report(
        matches=matches,
        alerts=alerts,
        db=db,
        generated_at=now,
        surface_mismatches=surface_mismatches,
        injury_flags=injury_flags,
    )

    # Step 8: Save to disk
    report_path = save_report(report_md, config.REPORTS_DIR, now)

    # Step 9: Send email (every cycle, regardless of alerts)
    send_report(
        markdown_content=report_md,
        alerts=alerts,
        matches=matches,
        db=db,
        generated_at=now,
        surface_mismatches=surface_mismatches,
        injury_flags=injury_flags,
    )

    # Step 10: Console summary
    if alerts:
        print(f"\n{'='*60}")
        print(f"  STEAM ALERTS DETECTED: {len(alerts)}")
        for a in alerts:
            print(f"  [{a.signal_type}] {a.player} | {_get_tournament(a.match_id, matches)} "
                  f"| base={a.baseline_prob*100:.1f}% curr={a.current_prob*100:.1f}% "
                  f"delta={a.pct_change_norm:+.1f}%")
        print(f"{'='*60}\n")

    logger.info(
        "=== Cycle complete: %d matches | %d steam alerts | %d surface flags | "
        "%d injury flags | report: %s ===",
        len(matches), len(alerts), len(surface_mismatches), len(injury_flags),
        report_path.name,
    )

    # Step 11: Cleanup old reports
    cleanup_old_reports(config.REPORTS_DIR)


def _get_tournament(match_id: str, matches) -> str:
    for m in matches:
        if m.match_id == match_id:
            return m.tournament
    return match_id
