"""
Markdown report generator (plain-text / disk storage version).
The HTML email is built separately in emailer.py.
"""

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import config
from src.models import DatabaseManager, MatchOdds, SteamAlert

logger = logging.getLogger(__name__)

_LEVEL_ORDER = [
    ("grand_slam",   "Grand Slams"),
    ("atp_finals",   "ATP Finals"),
    ("wta_finals",   "WTA Finals"),
    ("masters_1000", "ATP / WTA Masters 1000"),
    ("wta_1000",     "WTA 1000"),
    ("atp_500",      "ATP 500"),
    ("wta_500",      "WTA 500"),
    ("challenger",   "Challengers"),
    ("itf",          "ITF"),
    ("unknown",      "Other Tennis"),
]


def _fmt_pct(val: float) -> str:
    sign = "+" if val > 0 else ""
    return f"{sign}{val:.1f}%"


def _fmt_prob(val: float) -> str:
    return f"{val * 100:.1f}%"


def _odds_from_prob(prob: float) -> str:
    if prob <= 0:
        return "N/A"
    return f"{1.0 / prob:.2f}"


def calc_norm_delta(baseline: float, current: float) -> float:
    try:
        denom = 1.0 - baseline
        if abs(denom) < 1e-9 or baseline <= 0:
            return 0.0
        return (current - baseline) / denom * 100.0
    except Exception:
        return 0.0


def generate_report(
    matches: list[MatchOdds],
    alerts: list[SteamAlert],
    db: DatabaseManager,
    generated_at: datetime,
    surface_mismatches: list[dict] | None = None,
    injury_flags: list[dict] | None = None,
) -> str:
    next_at = generated_at + timedelta(minutes=config.SCRAPE_INTERVAL_MINUTES)
    surface_mismatches = surface_mismatches or []
    injury_flags = injury_flags or []
    lines: list[str] = []

    # Header
    lines.append("# Tennis Steamer Report")
    lines.append(f"**Generated:** {generated_at.strftime('%Y-%m-%d %H:%M UTC')}  | **Next:** {next_at.strftime('%H:%M UTC')}")
    lines.append(f"**Monitored:** {len(matches)} matches  | **Steam Alerts:** {len(alerts)}")
    lines.append(f"**Source:** The Odds API  | **Threshold:** {config.STEAM_THRESHOLD_PCT}% normalised Δ implied prob")
    lines.append("")
    lines.append("---")
    lines.append("")

    # Steam Alerts
    lines.append("## Steam Alerts")
    if alerts:
        match_lookup = {m.match_id: m for m in matches}
        lines.append("| Signal | Player | Match | Tournament | Baseline Odds | Current Odds | Δ Norm |")
        lines.append("|--------|--------|-------|-----------|--------------|-------------|--------|")
        for a in sorted(alerts, key=lambda x: abs(x.pct_change_norm), reverse=True):
            m = match_lookup.get(a.match_id)
            match_str = f"{m.player1} vs {m.player2}" if m else a.match_id
            tournament = m.tournament if m else ""
            b_odds = _odds_from_prob(a.baseline_prob)
            c_odds = _odds_from_prob(a.current_prob)
            lines.append(
                f"| **{a.signal_type}** | **{a.player}** | {match_str} | {tournament} "
                f"| {b_odds} ({_fmt_prob(a.baseline_prob)}) "
                f"| {c_odds} ({_fmt_prob(a.current_prob)}) "
                f"| {_fmt_pct(a.pct_change_norm)} |"
            )
    else:
        lines.append("> No steam moves detected this cycle.")

    lines.append("")
    lines.append("---")
    lines.append("")

    # All Matches
    lines.append("## All Monitored Matches")
    lines.append("")

    alerted_match_players: dict[str, list[str]] = {}
    for a in alerts:
        alerted_match_players.setdefault(a.match_id, []).append(a.player)

    by_level: dict[str, list[MatchOdds]] = {}
    for m in matches:
        by_level.setdefault(m.level, []).append(m)

    for level_key, level_label in _LEVEL_ORDER:
        level_matches = by_level.get(level_key, [])
        if not level_matches:
            continue

        lines.append(f"### {level_label}")
        lines.append("| Match | Surf | P1 Odds | P1 Prob | Δ P1 | P2 Odds | P2 Prob | Δ P2 | Status |")
        lines.append("|-------|------|---------|---------|------|---------|---------|------|--------|")

        for m in sorted(level_matches, key=lambda x: x.tournament):
            baseline = db.get_baseline_odds(m.match_id)
            if baseline:
                b_p1, b_p2 = baseline
                d_p1 = _fmt_pct(calc_norm_delta(b_p1, m.p1_implied))
                d_p2 = _fmt_pct(calc_norm_delta(b_p2, m.p2_implied))
                b_p1_odds = f"{1/b_p1:.2f}→{m.p1_odds:.2f}"
                b_p2_odds = f"{1/b_p2:.2f}→{m.p2_odds:.2f}"
            else:
                d_p1 = d_p2 = "NEW"
                b_p1_odds = f"{m.p1_odds:.2f}"
                b_p2_odds = f"{m.p2_odds:.2f}"

            steamed = alerted_match_players.get(m.match_id)
            status = f"STEAM ({', '.join(steamed)})" if steamed else "OK"

            lines.append(
                f"| {m.player1} vs {m.player2} | {m.surface.title()} "
                f"| {b_p1_odds} | {_fmt_prob(m.p1_implied)} | {d_p1} "
                f"| {b_p2_odds} | {_fmt_prob(m.p2_implied)} | {d_p2} | {status} |"
            )
        lines.append("")

    lines.append("---")
    lines.append("")

    # Pro Signals
    lines.append("## Pro Signal Flags")
    lines.append("")
    lines.append("### Surface Mismatches")
    if surface_mismatches:
        lines.append("| Match | Player | Preferred | Match Surface |")
        lines.append("|-------|--------|-----------|---------------|")
        for sm in surface_mismatches:
            lines.append(f"| {sm['match']} | {sm['player']} | {sm['preferred_surface'].title()} | {sm['match_surface'].title()} |")
    else:
        lines.append("> No surface mismatches detected.")
    lines.append("")

    lines.append("### Injury Watch")
    if injury_flags:
        lines.append("| Player | Match | Headline | Source |")
        lines.append("|--------|-------|---------|--------|")
        for inj in injury_flags:
            headline = inj["headline"][:80] + ("…" if len(inj["headline"]) > 80 else "")
            lines.append(f"| {inj['player']} | {inj.get('match', '')} | {headline} | {inj['source']} |")
    else:
        lines.append("> No injury news detected for monitored players.")
    lines.append("")

    lines.append("---")
    lines.append(f"*Tennis Steamer Agent  ·  Threshold: {config.STEAM_THRESHOLD_PCT}% normalised  ·  Pre-match only  ·  Source: The Odds API*")

    return "\n".join(lines)


def save_report(content: str, reports_dir: Path, timestamp: datetime) -> Path:
    reports_dir.mkdir(parents=True, exist_ok=True)
    filename = f"report_{timestamp.strftime('%Y-%m-%d_%H-%M')}.md"
    path = reports_dir / filename
    path.write_text(content, encoding="utf-8")
    logger.info("Report saved: %s", path)
    return path


def cleanup_old_reports(reports_dir: Path, keep_days: int = None) -> None:
    if keep_days is None:
        keep_days = config.REPORT_RETENTION_DAYS
    if not reports_dir.exists():
        return
    cutoff = datetime.now(timezone.utc) - timedelta(days=keep_days)
    deleted = 0
    for f in reports_dir.glob("report_*.md"):
        try:
            mtime = datetime.fromtimestamp(f.stat().st_mtime, tz=timezone.utc)
            if mtime < cutoff:
                f.unlink()
                deleted += 1
        except Exception as exc:
            logger.warning("Could not delete old report %s: %s", f, exc)
    if deleted:
        logger.info("Cleaned up %d old report(s)", deleted)
