"""
Data acquisition layer.
Primary source: The Odds API (legal, documented, free tier).
Secondary: ATP/WTA news headlines for injury detection (cached).
"""

import logging
import random
import re
import time
from datetime import datetime, timedelta, timezone

import requests
from bs4 import BeautifulSoup

import config
from src.models import MatchOdds, generate_match_id

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tournament level classifier
# ---------------------------------------------------------------------------

_LEVEL_PATTERNS: list[tuple[str, str]] = [
    # Grand Slams
    (r"australian open", "grand_slam"),
    (r"roland.garros|french open", "grand_slam"),
    (r"wimbledon", "grand_slam"),
    (r"us open", "grand_slam"),
    # Year-end finals
    (r"atp finals|nitto atp", "atp_finals"),
    (r"wta finals", "wta_finals"),
    # Masters / WTA 1000
    (r"masters 1000|masters1000|atp 1000|rolex monte", "masters_1000"),
    (r"wta 1000", "wta_1000"),
    (r"indian wells|miami open|madrid open|rome|canada|cincinnati|shanghai|paris masters|monte.carlo", "masters_1000"),
    (r"wta.*1000", "wta_1000"),
    # 500
    (r"atp 500|atp500", "atp_500"),
    (r"wta 500|wta500", "wta_500"),
    (r"barcelona|queen.s club|halle|washington|beijing|tokyo|vienna|basel|dubai", "atp_500"),
    # Challenger / ITF
    (r"challenger", "challenger"),
    (r"itf", "itf"),
]


def classify_tournament(name: str) -> str:
    name_lower = name.lower()
    for pattern, level in _LEVEL_PATTERNS:
        if re.search(pattern, name_lower):
            return level
    return "unknown"


# ---------------------------------------------------------------------------
# Surface lookup
# ---------------------------------------------------------------------------

_SURFACE_KEYWORDS: dict[str, str] = {
    "australian open": "hard",
    "us open": "hard",
    "miami": "hard",
    "indian wells": "hard",
    "cincinnati": "hard",
    "canada": "hard",
    "shanghai": "hard",
    "paris": "hard",
    "vienna": "hard",
    "washington": "hard",
    "beijing": "hard",
    "tokyo": "hard",
    "roland garros": "clay",
    "french open": "clay",
    "madrid": "clay",
    "rome": "clay",
    "monte carlo": "clay",
    "barcelona": "clay",
    "hamburg": "clay",
    "budapest": "clay",
    "wimbledon": "grass",
    "queen": "grass",
    "halle": "grass",
    "eastbourne": "grass",
    "'s-hertogenbosch": "grass",
}


def classify_surface(tournament_name: str) -> str:
    name_lower = tournament_name.lower()
    for keyword, surface in _SURFACE_KEYWORDS.items():
        if keyword in name_lower:
            return surface
    return "unknown"


# ---------------------------------------------------------------------------
# The Odds API client
# ---------------------------------------------------------------------------

class OddsAPIClient:
    def __init__(self, api_key: str) -> None:
        self._key = api_key
        self._session = requests.Session()
        self._session.headers.update({"Accept": "application/json"})
        self.last_requests_remaining: int | None = None
        self.last_requests_used: int | None = None

    def get_active_tennis_sport_keys(self) -> list[str]:
        """
        Fetch all currently active tennis tournament sport keys.
        The Odds API uses per-tournament keys (e.g. tennis_atp_indian_wells)
        rather than a generic 'tennis' key — querying each gives the full match list.
        """
        try:
            resp = self._session.get(
                f"{config.ODDS_API_BASE}/sports",
                params={"apiKey": self._key},
                timeout=20,
            )
            self._update_quota(resp)
            if not resp.ok:
                logger.warning("Could not fetch sport keys (HTTP %s) — falling back to 'tennis'", resp.status_code)
                return ["tennis"]
            sports = resp.json()
            keys = [
                s["key"] for s in sports
                if s.get("active") and s["key"].startswith("tennis_")
            ]
            logger.info("Active tennis sport keys: %s", keys)
            return keys if keys else ["tennis"]
        except Exception as exc:
            logger.warning("Sport key fetch failed (%s) — falling back to 'tennis'", exc)
            return ["tennis"]

    def get_tennis_events(self) -> list[dict]:
        """
        Fetch upcoming tennis h2h odds across ALL active tennis tournaments.
        Queries each tournament's sport key separately and combines results.
        """
        sport_keys = self.get_active_tennis_sport_keys()
        all_events: list[dict] = []

        params_base: dict = {
            "apiKey": self._key,
            "regions": "eu",
            "markets": "h2h",
            "oddsFormat": "decimal",
        }
        if config.ODDS_API_BOOKMAKERS:
            params_base["bookmakers"] = config.ODDS_API_BOOKMAKERS

        for key in sport_keys:
            url = f"{config.ODDS_API_BASE}/sports/{key}/odds/"
            logger.debug("GET %s", url)
            try:
                resp = self._session.get(url, params=params_base, timeout=20)
                self._update_quota(resp)
                if resp.status_code == 401:
                    logger.error("Odds API: invalid API key (401).")
                    break
                if resp.status_code == 429:
                    logger.warning("Odds API: rate limited (429). Stopping early.")
                    break
                if not resp.ok:
                    logger.warning("Odds API HTTP %s for %s — skipping", resp.status_code, key)
                    continue
                events = resp.json()
                logger.debug("  %s → %d events", key, len(events))
                all_events.extend(events)
            except requests.RequestException as exc:
                logger.error("Request failed for %s: %s", key, exc)

        logger.info("Fetched %d total raw events across %d tournament(s)", len(all_events), len(sport_keys))
        return all_events

    def _update_quota(self, resp) -> None:
        self.last_requests_remaining = resp.headers.get("x-requests-remaining")
        self.last_requests_used = resp.headers.get("x-requests-used")
        if self.last_requests_remaining is not None:
            remaining = int(self.last_requests_remaining)
            logger.info("Odds API quota — used: %s, remaining: %s", self.last_requests_used, remaining)
            if remaining < config.ODDS_API_QUOTA_WARN_THRESHOLD:
                logger.warning("QUOTA WARNING: only %d requests remaining this month!", remaining)

    def close(self) -> None:
        self._session.close()


def parse_odds_api_response(events: list[dict]) -> list[MatchOdds]:
    """
    Convert raw Odds API event dicts into MatchOdds dataclasses.
    Picks the best available price (highest) across bookmaker responses.
    """
    results: list[MatchOdds] = []
    now = datetime.now(timezone.utc)

    for event in events:
        home = event.get("home_team", "")
        away = event.get("away_team", "")
        tournament = event.get("sport_title", "Tennis")

        if not home or not away:
            continue

        # Pre-match only — skip matches that have already started
        commence_raw = event.get("commence_time", "")
        if commence_raw:
            commence_dt = datetime.fromisoformat(commence_raw.replace("Z", "+00:00"))
            if commence_dt <= now:
                logger.debug("Skipping in-play/started: %s vs %s (started %s)", home, away, commence_raw)
                continue

        # Aggregate best odds across all bookmakers returned
        best_p1: float | None = None
        best_p2: float | None = None

        for bm in event.get("bookmakers", []):
            for market in bm.get("markets", []):
                if market.get("key") != "h2h":
                    continue
                outcomes = {o["name"]: o["price"] for o in market.get("outcomes", [])}
                p1_price = outcomes.get(home)
                p2_price = outcomes.get(away)
                if p1_price and (best_p1 is None or p1_price > best_p1):
                    best_p1 = p1_price
                if p2_price and (best_p2 is None or p2_price > best_p2):
                    best_p2 = p2_price

        if best_p1 is None or best_p2 is None:
            logger.debug("Skipping %s vs %s — no h2h odds found", home, away)
            continue

        level = classify_tournament(tournament)
        if level not in config.TOURNAMENT_LEVELS:
            continue

        surface = classify_surface(tournament)
        match_id = generate_match_id(tournament, home, away)

        results.append(
            MatchOdds(
                match_id=match_id,
                tournament=tournament,
                level=level,
                surface=surface,
                player1=home,
                player2=away,
                p1_odds=best_p1,
                p2_odds=best_p2,
                p1_implied=round(1.0 / best_p1, 6),
                p2_implied=round(1.0 / best_p2, 6),
                scraped_at=now,
                source="odds_api",
            )
        )

    logger.info("Parsed %d tennis matches from Odds API", len(results))
    return results


def get_tennis_odds() -> list[MatchOdds]:
    """Top-level function: fetch + parse. Returns empty list on any failure."""
    if not config.ODDS_API_KEY:
        logger.error(
            "ODDS_API_KEY not set. Export ODDS_API_KEY env var or set in config.py."
        )
        return []

    client = OddsAPIClient(config.ODDS_API_KEY)
    delay = random.uniform(config.REQUEST_DELAY_MIN, config.REQUEST_DELAY_MAX)
    time.sleep(delay)
    try:
        events = client.get_tennis_events()
        return parse_odds_api_response(events)
    finally:
        client.close()


# ---------------------------------------------------------------------------
# Injury news scraper (cached)
# ---------------------------------------------------------------------------

_injury_cache: dict = {"fetched_at": None, "headlines": []}


def fetch_injury_news() -> list[dict]:
    """
    Scrape ATP + WTA news for injury/withdrawal headlines.
    Results cached for INJURY_CACHE_MINUTES to avoid hammering news sites.
    Returns list of {player_hint, headline, url, source, timestamp}.
    """
    now = datetime.now(timezone.utc)
    cached_at = _injury_cache.get("fetched_at")
    if cached_at and (now - cached_at) < timedelta(minutes=config.INJURY_CACHE_MINUTES):
        return _injury_cache["headlines"]

    headlines: list[dict] = []

    sources = [
        (config.ATP_NEWS_URL, "ATP"),
        (config.WTA_NEWS_URL, "WTA"),
    ]

    session = requests.Session()
    session.headers.update(
        {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    )

    for url, source_name in sources:
        try:
            time.sleep(random.uniform(2.0, 4.0))
            resp = session.get(url, timeout=15)
            if not resp.ok:
                logger.warning("News fetch %s returned HTTP %s", source_name, resp.status_code)
                continue
            soup = BeautifulSoup(resp.text, "lxml")
            for tag in soup.find_all(["h1", "h2", "h3", "a"]):
                text = tag.get_text(strip=True)
                if not text or len(text) < 10:
                    continue
                text_lower = text.lower()
                if any(kw in text_lower for kw in config.INJURY_KEYWORDS):
                    href = tag.get("href", "")
                    if href and not href.startswith("http"):
                        href = url.rstrip("/") + href
                    headlines.append(
                        {
                            "headline": text,
                            "url": href or url,
                            "source": source_name,
                            "timestamp": now.isoformat(),
                        }
                    )
        except Exception as exc:
            logger.warning("Failed to scrape %s news: %s", source_name, exc)

    session.close()

    _injury_cache["fetched_at"] = now
    _injury_cache["headlines"] = headlines
    logger.info("Injury news cache refreshed: %d headlines", len(headlines))
    return headlines


def match_injury_to_players(
    headlines: list[dict], matches: list[MatchOdds]
) -> list[dict]:
    """
    Cross-reference injury headlines against active match players.
    Returns headlines enriched with matched player + match_id.
    """
    matched: list[dict] = []
    for h in headlines:
        text_lower = h["headline"].lower()
        for m in matches:
            for player in (m.player1, m.player2):
                # Match on last name (most reliable in headlines)
                last_name = player.split()[-1].lower()
                if last_name in text_lower and len(last_name) > 3:
                    matched.append(
                        {
                            **h,
                            "player": player,
                            "match_id": m.match_id,
                            "match": f"{m.player1} vs {m.player2}",
                        }
                    )
                    break
    return matched
