"""
Data models: typed dataclasses + SQLite DatabaseManager.
All other modules import MatchOdds and SteamAlert from here.
"""

import hashlib
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


# ---------------------------------------------------------------------------
# Typed dataclasses (in-memory representation)
# ---------------------------------------------------------------------------

@dataclass
class MatchOdds:
    match_id: str
    tournament: str
    level: str          # grand_slam / masters_1000 / etc.
    surface: str        # hard / clay / grass / unknown
    player1: str
    player2: str
    p1_odds: float
    p2_odds: float
    p1_implied: float   # 1 / p1_odds
    p2_implied: float   # 1 / p2_odds
    scraped_at: datetime
    source: str         # "odds_api"


@dataclass
class SteamAlert:
    match_id: str
    timestamp: datetime
    player: str
    direction: str          # "UP" | "DOWN"
    baseline_prob: float
    current_prob: float
    pct_change: float       # raw
    pct_change_norm: float  # devigged normalized (primary signal)
    signal_type: str        # SHARP_MOVE / SUSPECTED_RLM / UNDERDOG_STEAM / FAVORITE_DRIFT


# ---------------------------------------------------------------------------
# Match ID generation
# ---------------------------------------------------------------------------

def generate_match_id(tournament: str, p1: str, p2: str) -> str:
    """Deterministic 12-char hex ID regardless of player display order."""
    players = sorted([p1.strip().lower(), p2.strip().lower()])
    key = f"{tournament.strip().lower()}:{players[0]}:{players[1]}"
    return hashlib.md5(key.encode()).hexdigest()[:12]


# ---------------------------------------------------------------------------
# DatabaseManager
# ---------------------------------------------------------------------------

DDL = """
CREATE TABLE IF NOT EXISTS matches (
    match_id    TEXT PRIMARY KEY,
    tournament  TEXT NOT NULL,
    level       TEXT NOT NULL,
    surface     TEXT DEFAULT 'unknown',
    player1     TEXT NOT NULL,
    player2     TEXT NOT NULL,
    first_seen  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS odds (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id    TEXT NOT NULL,
    timestamp   TEXT NOT NULL,
    p1_odds     REAL NOT NULL,
    p2_odds     REAL NOT NULL,
    p1_implied  REAL NOT NULL,
    p2_implied  REAL NOT NULL,
    source      TEXT NOT NULL,
    FOREIGN KEY (match_id) REFERENCES matches(match_id)
);

CREATE TABLE IF NOT EXISTS steam_alerts (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    match_id         TEXT NOT NULL,
    timestamp        TEXT NOT NULL,
    player           TEXT NOT NULL,
    direction        TEXT NOT NULL,
    baseline_prob    REAL NOT NULL,
    current_prob     REAL NOT NULL,
    pct_change       REAL NOT NULL,
    pct_change_norm  REAL NOT NULL,
    signal_type      TEXT NOT NULL,
    FOREIGN KEY (match_id) REFERENCES matches(match_id)
);
"""


class DatabaseManager:
    def __init__(self, db_path: Path) -> None:
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row

    def create_tables(self) -> None:
        self._conn.executescript(DDL)
        self._conn.commit()

    # --- matches -----------------------------------------------------------

    def upsert_match(self, m: MatchOdds) -> None:
        """Insert match if not already present (first-seen wins)."""
        self._conn.execute(
            """
            INSERT OR IGNORE INTO matches
                (match_id, tournament, level, surface, player1, player2, first_seen)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                m.match_id, m.tournament, m.level, m.surface,
                m.player1, m.player2, m.scraped_at.isoformat(),
            ),
        )
        self._conn.commit()

    def get_active_matches(self) -> list[dict]:
        """All matches in the DB (callers filter by time if needed)."""
        rows = self._conn.execute("SELECT * FROM matches").fetchall()
        return [dict(r) for r in rows]

    # --- odds --------------------------------------------------------------

    def insert_odds(self, m: MatchOdds) -> None:
        self._conn.execute(
            """
            INSERT INTO odds
                (match_id, timestamp, p1_odds, p2_odds, p1_implied, p2_implied, source)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                m.match_id, m.scraped_at.isoformat(),
                m.p1_odds, m.p2_odds,
                m.p1_implied, m.p2_implied,
                m.source,
            ),
        )
        self._conn.commit()

    def get_baseline_odds(self, match_id: str) -> tuple[float, float] | None:
        """Return (p1_implied, p2_implied) from first-ever odds row, or None."""
        row = self._conn.execute(
            "SELECT p1_implied, p2_implied FROM odds WHERE match_id = ? ORDER BY id ASC LIMIT 1",
            (match_id,),
        ).fetchone()
        return (row["p1_implied"], row["p2_implied"]) if row else None

    def get_latest_odds(self, match_id: str) -> tuple[float, float] | None:
        """Return most recent (p1_implied, p2_implied), or None."""
        row = self._conn.execute(
            "SELECT p1_implied, p2_implied FROM odds WHERE match_id = ? ORDER BY id DESC LIMIT 1",
            (match_id,),
        ).fetchone()
        return (row["p1_implied"], row["p2_implied"]) if row else None

    def odds_count(self, match_id: str) -> int:
        """Number of odds readings for this match."""
        row = self._conn.execute(
            "SELECT COUNT(*) AS n FROM odds WHERE match_id = ?", (match_id,)
        ).fetchone()
        return row["n"]

    # --- steam_alerts ------------------------------------------------------

    def insert_steam_alert(self, alert: SteamAlert) -> None:
        self._conn.execute(
            """
            INSERT INTO steam_alerts
                (match_id, timestamp, player, direction, baseline_prob,
                 current_prob, pct_change, pct_change_norm, signal_type)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                alert.match_id, alert.timestamp.isoformat(),
                alert.player, alert.direction,
                alert.baseline_prob, alert.current_prob,
                alert.pct_change, alert.pct_change_norm,
                alert.signal_type,
            ),
        )
        self._conn.commit()

    def alert_exists_this_cycle(self, match_id: str, player: str, direction: str,
                                 since: datetime) -> bool:
        """Prevent duplicate alerts within the same 20-min cycle."""
        row = self._conn.execute(
            """
            SELECT 1 FROM steam_alerts
            WHERE match_id = ? AND player = ? AND direction = ? AND timestamp >= ?
            LIMIT 1
            """,
            (match_id, player, direction, since.isoformat()),
        ).fetchone()
        return row is not None

    # --- housekeeping ------------------------------------------------------

    def close(self) -> None:
        self._conn.commit()
        self._conn.close()
