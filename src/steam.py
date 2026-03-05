"""
Steam detection logic, signal classification, and pro signals.
Implied probability math, RLM heuristic, surface mismatch detection.
"""

import logging
from datetime import datetime, timezone

import config
from src.models import DatabaseManager, MatchOdds, SteamAlert

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Player preferred surface lookup (top ~60 players)
# ---------------------------------------------------------------------------

PLAYER_PREFERRED_SURFACE: dict[str, str] = {
    # ATP
    "novak djokovic": "hard",
    "carlos alcaraz": "clay",
    "jannik sinner": "hard",
    "daniil medvedev": "hard",
    "alexander zverev": "clay",
    "andrey rublev": "hard",
    "casper ruud": "clay",
    "holger rune": "clay",
    "stefanos tsitsipas": "clay",
    "taylor fritz": "hard",
    "tommy paul": "hard",
    "ben shelton": "hard",
    "alex de minaur": "hard",
    "grigor dimitrov": "hard",
    "ugo humbert": "hard",
    "sebastian baez": "clay",
    "francisco cerundolo": "clay",
    "nicolas jarry": "clay",
    "karen khachanov": "hard",
    "felix auger-aliassime": "hard",
    "rafael nadal": "clay",
    "roger federer": "grass",
    "dominic thiem": "clay",
    "jack draper": "grass",
    "cameron norrie": "grass",
    "matteo berrettini": "grass",
    "lorenzo musetti": "clay",
    "gael monfils": "hard",
    "richard gasquet": "clay",
    "stan wawrinka": "clay",
    # WTA
    "iga swiatek": "clay",
    "aryna sabalenka": "hard",
    "coco gauff": "hard",
    "elena rybakina": "grass",
    "jessica pegula": "hard",
    "caroline wozniacki": "hard",
    "maria sakkari": "hard",
    "barbora krejcikova": "clay",
    "marketa vondrousova": "grass",
    "madison keys": "hard",
    "karolina muchova": "clay",
    "ons jabeur": "grass",
    "caroline garcia": "hard",
    "petra kvitova": "grass",
    "victoria azarenka": "hard",
    "elina svitolina": "clay",
    "diana shnaider": "hard",
    "mirra andreeva": "clay",
    "daria kasatkina": "clay",
    "jasmine paolini": "clay",
    "anna kalinskaya": "hard",
    "paula badosa": "clay",
    "emma raducanu": "hard",
    "belinda bencic": "hard",
    "sorana cirstea": "clay",
}


def get_preferred_surface(player_name: str) -> str | None:
    return PLAYER_PREFERRED_SURFACE.get(player_name.lower().strip())


# ---------------------------------------------------------------------------
# Core math
# ---------------------------------------------------------------------------

def calc_implied_prob(decimal_odds: float) -> float:
    if decimal_odds <= 1.0:
        raise ValueError(f"Invalid decimal odds: {decimal_odds}")
    return 1.0 / decimal_odds


def calc_pct_change(baseline: float, current: float) -> float:
    """Raw percentage change in implied probability."""
    if baseline <= 0:
        raise ValueError(f"Invalid baseline probability: {baseline}")
    return (current - baseline) / baseline * 100.0


def calc_pct_change_norm(baseline: float, current: float) -> float:
    """
    Normalized (devigged) percentage change.
    Removes overround distortion. This is the PRIMARY signal value.
    Formula: (current - baseline) / (1 - baseline) * 100
    """
    if baseline <= 0:
        raise ValueError(f"Invalid baseline probability: {baseline}")
    denom = 1.0 - baseline
    if abs(denom) < 1e-9:
        return 0.0
    return (current - baseline) / denom * 100.0


# ---------------------------------------------------------------------------
# Signal classification
# ---------------------------------------------------------------------------

def classify_signal(
    baseline_implied: float,
    current_implied: float,
    pct_change_norm: float,
) -> str | None:
    """
    Returns signal type string or None if no signal threshold met.
    Priority: SHARP_MOVE > SUSPECTED_RLM > UNDERDOG_STEAM > FAVORITE_DRIFT
    """
    abs_norm = abs(pct_change_norm)

    if abs_norm < config.STEAM_THRESHOLD_PCT:
        return None

    direction_up = pct_change_norm > 0
    is_underdog = baseline_implied < 0.50

    # SHARP_MOVE: magnitude alone qualifies
    if abs_norm >= config.SHARP_MOVE_THRESHOLD_PCT:
        return "SHARP_MOVE"

    # SUSPECTED_RLM: underdog shortening (price implies sharps backing longshot)
    if is_underdog and direction_up:
        return "SUSPECTED_RLM"

    # UNDERDOG_STEAM
    if is_underdog and direction_up:
        return "UNDERDOG_STEAM"

    # FAVORITE_DRIFT
    if not is_underdog and not direction_up:
        return "FAVORITE_DRIFT"

    # Generic steam (e.g. underdog drifts or favorite shortens)
    return "STEAM"


# ---------------------------------------------------------------------------
# Surface mismatch detection
# ---------------------------------------------------------------------------

def detect_surface_mismatches(matches: list[MatchOdds]) -> list[dict]:
    """
    Returns list of {match, player, preferred_surface, match_surface}
    for players whose preferred surface differs from the match surface.
    """
    mismatches: list[dict] = []
    for m in matches:
        if m.surface == "unknown":
            continue
        for player in (m.player1, m.player2):
            preferred = get_preferred_surface(player)
            if preferred and preferred != m.surface:
                mismatches.append(
                    {
                        "match": f"{m.player1} vs {m.player2}",
                        "tournament": m.tournament,
                        "player": player,
                        "preferred_surface": preferred,
                        "match_surface": m.surface,
                    }
                )
    return mismatches


# ---------------------------------------------------------------------------
# Main steam detection
# ---------------------------------------------------------------------------

def detect_steam(
    current_matches: list[MatchOdds],
    db: DatabaseManager,
) -> list[SteamAlert]:
    """
    Compare current odds against baseline (first-ever reading per match).
    Returns list of new SteamAlert instances (not yet saved to DB).
    """
    alerts: list[SteamAlert] = []
    now = datetime.now(timezone.utc)
    # "this cycle" window: anything within the last 25 minutes
    from datetime import timedelta
    cycle_start = datetime(
        now.year, now.month, now.day, now.hour,
        (now.minute // 20) * 20, 0, tzinfo=timezone.utc
    )

    for m in current_matches:
        baseline = db.get_baseline_odds(m.match_id)
        if baseline is None:
            # First time we've seen this match — will be stored as baseline by scheduler
            logger.info("New match (baseline): %s vs %s (%s)", m.player1, m.player2, m.tournament)
            continue

        baseline_p1, baseline_p2 = baseline
        pairs = [
            (m.player1, baseline_p1, m.p1_implied),
            (m.player2, baseline_p2, m.p2_implied),
        ]

        for player, base_impl, curr_impl in pairs:
            try:
                pct_raw = calc_pct_change(base_impl, curr_impl)
                pct_norm = calc_pct_change_norm(base_impl, curr_impl)
            except ValueError as exc:
                logger.warning("Steam calc error for %s: %s", player, exc)
                continue

            signal = classify_signal(base_impl, curr_impl, pct_norm)
            if signal is None:
                continue

            direction = "UP" if pct_norm > 0 else "DOWN"

            # Deduplicate within same cycle
            if db.alert_exists_this_cycle(m.match_id, player, direction, cycle_start):
                logger.debug("Duplicate alert suppressed: %s %s %s", player, direction, signal)
                continue

            alert = SteamAlert(
                match_id=m.match_id,
                timestamp=now,
                player=player,
                direction=direction,
                baseline_prob=round(base_impl, 6),
                current_prob=round(curr_impl, 6),
                pct_change=round(pct_raw, 2),
                pct_change_norm=round(pct_norm, 2),
                signal_type=signal,
            )
            alerts.append(alert)
            logger.info(
                "STEAM ALERT: %s | %s | %s | base=%.1f%% curr=%.1f%% norm_delta=%+.1f%%",
                signal, player, m.tournament,
                base_impl * 100, curr_impl * 100, pct_norm,
            )

    return alerts
