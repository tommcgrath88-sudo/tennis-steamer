"""
Gmail SMTP email delivery.
Sends every cycle report as multipart HTML + plain text.
HTML is built directly (not converted from markdown) for a professional render.
"""

import logging
import smtplib
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import config
from src.models import MatchOdds, SteamAlert

logger = logging.getLogger(__name__)

_SIGNAL_COLOURS = {
    "SHARP_MOVE":     "#EF4444",
    "SUSPECTED_RLM":  "#F97316",
    "UNDERDOG_STEAM": "#2563EB",
    "FAVORITE_DRIFT": "#7C3AED",
}
_DEFAULT_SIGNAL_COLOUR = "#6B7280"

_LEVEL_ORDER = [
    ("grand_slam",   "Grand Slams"),
    ("atp_finals",   "ATP Finals"),
    ("wta_finals",   "WTA Finals"),
    ("masters_1000", "Masters 1000"),
    ("wta_1000",     "WTA 1000"),
    ("atp_500",      "ATP 500"),
    ("wta_500",      "WTA 500"),
    ("challenger",   "Challengers"),
    ("itf",          "ITF"),
    ("unknown",      "Other"),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pct(val: float) -> str:
    sign = "+" if val > 0 else ""
    return f"{sign}{val:.1f}%"


def _prob(val: float) -> str:
    return f"{val * 100:.1f}%"


def _odds(prob: float) -> str:
    if prob <= 0:
        return "N/A"
    return f"{1.0 / prob:.2f}"


def _norm_delta(baseline: float, current: float) -> float:
    try:
        denom = 1.0 - baseline
        if abs(denom) < 1e-9 or baseline <= 0:
            return 0.0
        return (current - baseline) / denom * 100.0
    except Exception:
        return 0.0


def _delta_cell_style(delta: float) -> str:
    """Background colour for a delta cell in the matches table."""
    if delta >= 3.0:
        return "background:#D1FAE5;color:#065F46;font-weight:600;"   # green — shortening
    if delta <= -3.0:
        return "background:#FEE2E2;color:#991B1B;font-weight:600;"   # red — drifting
    return "color:#374151;"


# ---------------------------------------------------------------------------
# HTML builders
# ---------------------------------------------------------------------------

def _html_header(generated_at: datetime, alerts_count: int, matches_count: int) -> str:
    next_at = generated_at + timedelta(minutes=config.SCRAPE_INTERVAL_MINUTES)
    alert_badge = (
        f'<span style="background:#F59E0B;color:#0B1426;padding:4px 14px;'
        f'border-radius:20px;font-size:13px;font-weight:700;margin-left:12px;">'
        f'{alerts_count} ALERT{"S" if alerts_count != 1 else ""}</span>'
        if alerts_count else ""
    )
    return f"""
<div style="background:#0B1426;padding:36px 40px 28px;border-radius:12px 12px 0 0;">
  <div style="display:flex;align-items:center;margin-bottom:6px;">
    <span style="color:#F59E0B;font-size:22px;font-weight:800;letter-spacing:1px;">
      TENNIS STEAMER
    </span>
    {alert_badge}
  </div>
  <div style="color:#94A3B8;font-size:13px;letter-spacing:0.5px;">
    Generated {generated_at.strftime('%d %b %Y  %H:%M UTC')} &nbsp;·&nbsp;
    Next {next_at.strftime('%H:%M UTC')} &nbsp;·&nbsp;
    {matches_count} matches monitored &nbsp;·&nbsp;
    Threshold {config.STEAM_THRESHOLD_PCT}% normalised Δ
  </div>
</div>
"""


def _html_alert_cards(alerts: list[SteamAlert], matches: list[MatchOdds]) -> str:
    if not alerts:
        return """
<div style="padding:24px 40px;">
  <h2 style="color:#1E293B;font-size:17px;font-weight:700;margin:0 0 14px;
             border-left:4px solid #E2E8F0;padding-left:12px;">
    Steam Alerts
  </h2>
  <div style="background:#F8FAFC;border:1px solid #E2E8F0;border-radius:8px;
              padding:18px 20px;color:#64748B;font-size:14px;">
    No steam moves detected this cycle.
  </div>
</div>
"""

    match_lookup = {m.match_id: m for m in matches}
    sorted_alerts = sorted(alerts, key=lambda x: abs(x.pct_change_norm), reverse=True)
    cards = []

    for a in sorted_alerts:
        colour = _SIGNAL_COLOURS.get(a.signal_type, _DEFAULT_SIGNAL_COLOUR)
        m = match_lookup.get(a.match_id)
        match_str = f"{m.player1} vs {m.player2}" if m else a.match_id
        tournament = m.tournament if m else ""
        surface = m.surface.title() if m else ""

        b_odds_str = _odds(a.baseline_prob)
        c_odds_str = _odds(a.current_prob)
        b_prob_str = _prob(a.baseline_prob)
        c_prob_str = _prob(a.current_prob)
        delta_str  = _pct(a.pct_change_norm)

        # Arrow colour: green if shortening (prob going up), red if drifting
        arrow_colour = "#10B981" if a.pct_change_norm > 0 else "#EF4444"
        delta_bg     = "#D1FAE5" if a.pct_change_norm > 0 else "#FEE2E2"
        delta_fg     = "#065F46" if a.pct_change_norm > 0 else "#991B1B"

        surface_tag = (
            f'<span style="background:#E0F2FE;color:#0369A1;font-size:11px;'
            f'padding:2px 8px;border-radius:10px;margin-left:6px;">{surface}</span>'
            if surface else ""
        )

        cards.append(f"""
<div style="border-left:5px solid {colour};background:#FAFAFA;border-radius:0 8px 8px 0;
            padding:18px 20px;margin-bottom:12px;box-shadow:0 1px 3px rgba(0,0,0,0.06);">
  <div style="display:flex;align-items:center;margin-bottom:10px;flex-wrap:wrap;gap:6px;">
    <span style="background:{colour};color:#fff;font-size:11px;font-weight:700;
                 padding:3px 10px;border-radius:12px;letter-spacing:0.5px;">
      {a.signal_type}
    </span>
    <span style="font-size:16px;font-weight:700;color:#1E293B;margin-left:4px;">
      {a.player}
    </span>
  </div>
  <div style="color:#475569;font-size:13px;margin-bottom:14px;">
    {match_str}{surface_tag}
    &nbsp;·&nbsp;
    <span style="color:#6B7280;">{tournament}</span>
  </div>
  <table style="border-collapse:collapse;font-size:14px;width:100%;max-width:520px;">
    <tr>
      <th style="text-align:left;color:#94A3B8;font-weight:600;padding:0 20px 6px 0;
                 font-size:11px;letter-spacing:0.5px;white-space:nowrap;">
        BASELINE (start of day)
      </th>
      <th style="text-align:left;color:#94A3B8;font-weight:600;padding:0 20px 6px 0;
                 font-size:11px;letter-spacing:0.5px;white-space:nowrap;">
        CURRENT
      </th>
      <th style="text-align:left;color:#94A3B8;font-weight:600;padding:0 0 6px 0;
                 font-size:11px;letter-spacing:0.5px;white-space:nowrap;">
        Δ NORMALISED
      </th>
    </tr>
    <tr>
      <td style="padding:0 20px 0 0;white-space:nowrap;">
        <span style="font-size:22px;font-weight:700;color:#1E293B;">{b_odds_str}</span>
        <span style="color:#94A3B8;font-size:13px;margin-left:4px;">({b_prob_str})</span>
      </td>
      <td style="padding:0 20px 0 0;white-space:nowrap;">
        <span style="font-size:22px;font-weight:700;color:{arrow_colour};">{c_odds_str}</span>
        <span style="color:#94A3B8;font-size:13px;margin-left:4px;">({c_prob_str})</span>
      </td>
      <td style="white-space:nowrap;">
        <span style="background:{delta_bg};color:{delta_fg};font-size:18px;font-weight:800;
                     padding:4px 12px;border-radius:6px;">
          {delta_str}
        </span>
      </td>
    </tr>
  </table>
</div>""")

    return f"""
<div style="padding:24px 40px 8px;">
  <h2 style="color:#1E293B;font-size:17px;font-weight:700;margin:0 0 16px;
             border-left:4px solid #F59E0B;padding-left:12px;">
    Steam Alerts
  </h2>
  {''.join(cards)}
</div>
"""


def _html_matches_table(matches: list[MatchOdds], alerts: list[SteamAlert], db) -> str:
    alerted: dict[str, list[str]] = {}
    for a in alerts:
        alerted.setdefault(a.match_id, []).append(a.player)

    by_level: dict[str, list[MatchOdds]] = {}
    for m in matches:
        by_level.setdefault(m.level, []).append(m)

    sections = []
    for level_key, level_label in _LEVEL_ORDER:
        level_matches = by_level.get(level_key, [])
        if not level_matches:
            continue

        rows = []
        for m in sorted(level_matches, key=lambda x: x.tournament):
            baseline = db.get_baseline_odds(m.match_id)
            if baseline:
                b_p1, b_p2 = baseline
                d1 = _norm_delta(b_p1, m.p1_implied)
                d2 = _norm_delta(b_p2, m.p2_implied)
                p1_odds_str = f"{1/b_p1:.2f} → {m.p1_odds:.2f}"
                p2_odds_str = f"{1/b_p2:.2f} → {m.p2_odds:.2f}"
                d1_str = _pct(d1)
                d2_str = _pct(d2)
                d1_style = _delta_cell_style(d1)
                d2_style = _delta_cell_style(d2)
            else:
                p1_odds_str = f"{m.p1_odds:.2f}"
                p2_odds_str = f"{m.p2_odds:.2f}"
                d1_str = d2_str = "NEW"
                d1_style = d2_style = "color:#6B7280;font-style:italic;"

            steamed = alerted.get(m.match_id)
            if steamed:
                status_html = (
                    f'<span style="background:#FEF3C7;color:#92400E;font-size:11px;'
                    f'font-weight:700;padding:2px 8px;border-radius:10px;">'
                    f'STEAM</span>'
                )
            else:
                status_html = '<span style="color:#10B981;font-size:12px;">✓ OK</span>'

            rows.append(f"""
  <tr style="border-bottom:1px solid #F1F5F9;">
    <td style="padding:10px 12px;font-size:13px;color:#1E293B;font-weight:500;
               white-space:nowrap;">
      {m.player1}<br>
      <span style="color:#94A3B8;font-size:11px;">vs {m.player2}</span>
    </td>
    <td style="padding:10px 12px;font-size:12px;color:#64748B;">{m.surface.title()}</td>
    <td style="padding:10px 12px;font-size:13px;font-family:monospace;color:#334155;
               white-space:nowrap;">
      {p1_odds_str}
    </td>
    <td style="padding:10px 12px;font-size:13px;{d1_style}white-space:nowrap;">
      {d1_str}
    </td>
    <td style="padding:10px 12px;font-size:13px;font-family:monospace;color:#334155;
               white-space:nowrap;">
      {p2_odds_str}
    </td>
    <td style="padding:10px 12px;font-size:13px;{d2_style}white-space:nowrap;">
      {d2_str}
    </td>
    <td style="padding:10px 12px;text-align:center;">{status_html}</td>
  </tr>""")

        sections.append(f"""
<div style="margin-bottom:28px;">
  <h3 style="color:#475569;font-size:13px;font-weight:700;letter-spacing:0.8px;
             text-transform:uppercase;margin:0 0 10px;border-bottom:2px solid #F1F5F9;
             padding-bottom:8px;">
    {level_label}
  </h3>
  <table style="border-collapse:collapse;width:100%;font-size:13px;">
    <thead>
      <tr style="background:#F8FAFC;">
        <th style="padding:8px 12px;text-align:left;color:#64748B;font-size:11px;
                   font-weight:700;letter-spacing:0.5px;white-space:nowrap;">MATCH</th>
        <th style="padding:8px 12px;text-align:left;color:#64748B;font-size:11px;
                   font-weight:700;letter-spacing:0.5px;">SURF</th>
        <th style="padding:8px 12px;text-align:left;color:#64748B;font-size:11px;
                   font-weight:700;letter-spacing:0.5px;white-space:nowrap;">P1 ODDS</th>
        <th style="padding:8px 12px;text-align:left;color:#64748B;font-size:11px;
                   font-weight:700;letter-spacing:0.5px;">Δ P1</th>
        <th style="padding:8px 12px;text-align:left;color:#64748B;font-size:11px;
                   font-weight:700;letter-spacing:0.5px;white-space:nowrap;">P2 ODDS</th>
        <th style="padding:8px 12px;text-align:left;color:#64748B;font-size:11px;
                   font-weight:700;letter-spacing:0.5px;">Δ P2</th>
        <th style="padding:8px 12px;text-align:center;color:#64748B;font-size:11px;
                   font-weight:700;letter-spacing:0.5px;">STATUS</th>
      </tr>
    </thead>
    <tbody>{''.join(rows)}</tbody>
  </table>
</div>""")

    if not sections:
        return ""

    return f"""
<div style="padding:8px 40px 24px;">
  <h2 style="color:#1E293B;font-size:17px;font-weight:700;margin:0 0 20px;
             border-left:4px solid #E2E8F0;padding-left:12px;">
    All Monitored Matches
  </h2>
  {''.join(sections)}
</div>
"""


def _html_pro_signals(surface_mismatches: list[dict], injury_flags: list[dict]) -> str:
    # Surface mismatches
    if surface_mismatches:
        sm_rows = "".join(
            f"""<tr style="border-bottom:1px solid #F1F5F9;">
  <td style="padding:9px 12px;font-size:13px;color:#1E293B;">{sm['match']}</td>
  <td style="padding:9px 12px;font-size:13px;font-weight:600;color:#1E293B;">{sm['player']}</td>
  <td style="padding:9px 12px;font-size:13px;color:#10B981;">{sm['preferred_surface'].title()}</td>
  <td style="padding:9px 12px;font-size:13px;color:#EF4444;">{sm['match_surface'].title()}</td>
</tr>"""
            for sm in surface_mismatches
        )
        sm_block = f"""
<table style="border-collapse:collapse;width:100%;font-size:13px;margin-bottom:16px;">
  <thead>
    <tr style="background:#F8FAFC;">
      <th style="padding:8px 12px;text-align:left;color:#64748B;font-size:11px;
                 font-weight:700;letter-spacing:0.5px;">MATCH</th>
      <th style="padding:8px 12px;text-align:left;color:#64748B;font-size:11px;
                 font-weight:700;letter-spacing:0.5px;">PLAYER</th>
      <th style="padding:8px 12px;text-align:left;color:#64748B;font-size:11px;
                 font-weight:700;letter-spacing:0.5px;">PREFERRED</th>
      <th style="padding:8px 12px;text-align:left;color:#64748B;font-size:11px;
                 font-weight:700;letter-spacing:0.5px;">MATCH SURFACE</th>
    </tr>
  </thead>
  <tbody>{sm_rows}</tbody>
</table>"""
    else:
        sm_block = '<p style="color:#94A3B8;font-size:13px;margin:0;">No surface mismatches detected.</p>'

    # Injury flags
    if injury_flags:
        inj_rows = "".join(
            f"""<tr style="border-bottom:1px solid #F1F5F9;">
  <td style="padding:9px 12px;font-size:13px;font-weight:600;color:#1E293B;">
    {inj['player']}
  </td>
  <td style="padding:9px 12px;font-size:13px;color:#1E293B;">
    {inj.get('match', '')}
  </td>
  <td style="padding:9px 12px;font-size:13px;color:#475569;">
    {inj['headline'][:90] + ('…' if len(inj['headline']) > 90 else '')}
  </td>
  <td style="padding:9px 12px;font-size:12px;color:#94A3B8;">{inj['source']}</td>
</tr>"""
            for inj in injury_flags
        )
        inj_block = f"""
<table style="border-collapse:collapse;width:100%;font-size:13px;">
  <thead>
    <tr style="background:#F8FAFC;">
      <th style="padding:8px 12px;text-align:left;color:#64748B;font-size:11px;
                 font-weight:700;letter-spacing:0.5px;">PLAYER</th>
      <th style="padding:8px 12px;text-align:left;color:#64748B;font-size:11px;
                 font-weight:700;letter-spacing:0.5px;">MATCH</th>
      <th style="padding:8px 12px;text-align:left;color:#64748B;font-size:11px;
                 font-weight:700;letter-spacing:0.5px;">HEADLINE</th>
      <th style="padding:8px 12px;text-align:left;color:#64748B;font-size:11px;
                 font-weight:700;letter-spacing:0.5px;">SOURCE</th>
    </tr>
  </thead>
  <tbody>{inj_rows}</tbody>
</table>"""
    else:
        inj_block = '<p style="color:#94A3B8;font-size:13px;margin:0;">No injury news detected for monitored players.</p>'

    return f"""
<div style="padding:8px 40px 32px;">
  <h2 style="color:#1E293B;font-size:17px;font-weight:700;margin:0 0 20px;
             border-left:4px solid #E2E8F0;padding-left:12px;">
    Pro Signal Flags
  </h2>

  <h3 style="color:#475569;font-size:13px;font-weight:700;letter-spacing:0.8px;
             text-transform:uppercase;margin:0 0 10px;">Surface Mismatches</h3>
  {sm_block}

  <h3 style="color:#475569;font-size:13px;font-weight:700;letter-spacing:0.8px;
             text-transform:uppercase;margin:24px 0 10px;">Injury Watch</h3>
  {inj_block}
</div>
"""


def _html_footer() -> str:
    return f"""
<div style="background:#F8FAFC;border-top:1px solid #E2E8F0;padding:16px 40px;
            border-radius:0 0 12px 12px;text-align:center;">
  <span style="color:#94A3B8;font-size:12px;">
    Tennis Steamer Agent &nbsp;·&nbsp;
    Threshold {config.STEAM_THRESHOLD_PCT}% normalised &nbsp;·&nbsp;
    Pre-match only &nbsp;·&nbsp;
    Source: The Odds API
  </span>
</div>
"""


def _build_html(
    matches: list[MatchOdds],
    alerts: list[SteamAlert],
    db,
    generated_at: datetime,
    surface_mismatches: list[dict],
    injury_flags: list[dict],
) -> str:
    divider = '<hr style="border:none;border-top:1px solid #E2E8F0;margin:4px 0;">'
    body = (
        _html_header(generated_at, len(alerts), len(matches))
        + divider
        + _html_alert_cards(alerts, matches)
        + divider
        + _html_matches_table(matches, alerts, db)
        + divider
        + _html_pro_signals(surface_mismatches, injury_flags)
        + _html_footer()
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Tennis Steamer Report</title>
</head>
<body style="margin:0;padding:24px;background:#EFF3F8;
             font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;">
  <div style="max-width:860px;margin:0 auto;background:#FFFFFF;
              border-radius:12px;box-shadow:0 4px 24px rgba(0,0,0,0.10);overflow:hidden;">
    {body}
  </div>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_subject(alerts_count: int, generated_at: datetime, matches_count: int) -> str:
    ts = generated_at.strftime("%Y-%m-%d %H:%M UTC")
    if alerts_count > 0:
        return f"[STEAM ALERT x{alerts_count}] Tennis Steamer — {ts}"
    return f"Tennis Steamer Report — {ts} | {matches_count} matches"


def send_report(
    markdown_content: str,
    alerts: list[SteamAlert],
    matches: list[MatchOdds],
    db,
    generated_at: datetime,
    surface_mismatches: list[dict] | None = None,
    injury_flags: list[dict] | None = None,
) -> bool:
    """
    Send the report email. Returns True on success, False on failure.
    Never raises — logs errors and returns False so the scheduler keeps running.
    """
    if not config.EMAIL_ENABLED:
        logger.debug("Email disabled — skipping send.")
        return True

    if not config.EMAIL_APP_PASSWORD:
        logger.warning(
            "GMAIL_APP_PASSWORD not set. Skipping email. "
            "Set env var GMAIL_APP_PASSWORD or add to config.py."
        )
        return False

    surface_mismatches = surface_mismatches or []
    injury_flags = injury_flags or []
    alerts_count = len(alerts)
    matches_count = len(matches)

    subject = build_subject(alerts_count, generated_at, matches_count)

    html_full = _build_html(
        matches=matches,
        alerts=alerts,
        db=db,
        generated_at=generated_at,
        surface_mismatches=surface_mismatches,
        injury_flags=injury_flags,
    )

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = config.EMAIL_FROM
    msg["To"] = config.EMAIL_TO

    # Plain text fallback (markdown as-is — readable in plain clients)
    msg.attach(MIMEText(markdown_content, "plain", "utf-8"))
    # HTML part (rendered)
    msg.attach(MIMEText(html_full, "html", "utf-8"))

    try:
        with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=30) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.ehlo()
            smtp.login(config.EMAIL_FROM, config.EMAIL_APP_PASSWORD)
            smtp.sendmail(config.EMAIL_FROM, [config.EMAIL_TO], msg.as_string())
        logger.info("Email sent to %s — subject: %s", config.EMAIL_TO, subject)
        return True
    except smtplib.SMTPAuthenticationError:
        logger.error(
            "Gmail authentication failed. Check GMAIL_APP_PASSWORD. "
            "Note: App Password required (not regular Gmail password). "
            "Generate at: Google Account → Security → App Passwords."
        )
        return False
    except smtplib.SMTPException as exc:
        logger.error("SMTP error sending report email: %s", exc)
        return False
    except OSError as exc:
        logger.error("Network error sending report email: %s", exc)
        return False
