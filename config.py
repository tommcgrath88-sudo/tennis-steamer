"""
Tennis Steamer Agent — Central Configuration
All tunable settings live here. Sensitive values (API keys, passwords) should
be set as environment variables rather than hardcoded.
"""

import os
from pathlib import Path

# ---------------------------------------------------------------------------
# Load .env file (if present) — no external packages needed
# ---------------------------------------------------------------------------
_env_path = Path(__file__).parent / ".env"
if _env_path.exists():
    for _line in _env_path.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _key, _, _val = _line.partition("=")
            os.environ.setdefault(_key.strip(), _val.strip())

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
REPORTS_DIR = BASE_DIR / "reports"
DB_PATH = DATA_DIR / "tennis.db"
LOG_PATH = DATA_DIR / "agent.log"

# ---------------------------------------------------------------------------
# Scheduling
# ---------------------------------------------------------------------------
SCRAPE_INTERVAL_MINUTES = 45
REPORT_RETENTION_DAYS = 7

# Active hours (local time) — agent skips cycles outside this window
ACTIVE_HOURS_START = 9   # 09:00
ACTIVE_HOURS_END = 22    # 22:00 (10pm)

# ---------------------------------------------------------------------------
# Steam Detection Thresholds
# ---------------------------------------------------------------------------
STEAM_THRESHOLD_PCT = 3.0       # min normalized implied prob shift to flag
SHARP_MOVE_THRESHOLD_PCT = 5.0  # threshold for SHARP_MOVE signal

# ---------------------------------------------------------------------------
# The Odds API
# ---------------------------------------------------------------------------
ODDS_API_KEY = os.environ.get("ODDS_API_KEY", "")
ODDS_API_BASE = "https://api.the-odds-api.com/v4"
# Leave empty to pull all available bookmakers (recommended).
# Set to e.g. "stake,pinnacle,bet365" to filter to specific books.
ODDS_API_BOOKMAKERS = ""
ODDS_API_QUOTA_WARN_THRESHOLD = 50  # warn when remaining requests drop below this

# Tournament levels to monitor (all below will be included)
TOURNAMENT_LEVELS = {
    "grand_slam",
    "atp_finals",
    "wta_finals",
    "masters_1000",
    "wta_1000",
    "atp_500",
    "wta_500",
    "challenger",
    "itf",
    "unknown",  # include unrecognised tournaments rather than silently drop
}

# ---------------------------------------------------------------------------
# Email (Gmail SMTP)
# ---------------------------------------------------------------------------
EMAIL_ENABLED = True
EMAIL_TO = os.environ.get("EMAIL_TO", "tommcgrath88@gmail.com")
EMAIL_FROM = os.environ.get("EMAIL_FROM", "tommcgrath88@gmail.com")
# Set GMAIL_APP_PASSWORD env var (preferred) or paste here.
# Generate at: Google Account → Security → App Passwords
EMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587

# ---------------------------------------------------------------------------
# Request Timing
# ---------------------------------------------------------------------------
REQUEST_DELAY_MIN = 1.5   # seconds between outbound HTTP requests
REQUEST_DELAY_MAX = 3.5

# ---------------------------------------------------------------------------
# Injury News Scraping
# ---------------------------------------------------------------------------
INJURY_CACHE_MINUTES = 60   # only re-fetch ATP/WTA news once per hour
ATP_NEWS_URL = "https://www.atptour.com/en/news"
WTA_NEWS_URL = "https://www.wtatennis.com/news"
INJURY_KEYWORDS = [
    "injury", "injured", "withdraw", "withdrawn", "retire", "retires",
    "ruled out", "doubt", "doubtful", "fitness", "not playing", "scratched",
    "pulled out", "unable to",
]
