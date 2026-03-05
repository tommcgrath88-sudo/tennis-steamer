# Tennis Steamer Alert Agent — Task Checklist

> **Project path:** `c:\Users\tommc\my_ai_projects\Insurance\`
> **Python venv:** `.venv\Scripts\python`
> **Started:** 2026-03-04

---

## Phase 0 — Setup ✅
- [x] Create project directory structure (`src/`, `data/`, `reports/`, `tasks/`)
- [x] Create Python venv from Python 3.14
- [x] Install dependencies: `apscheduler`, `lxml`, `markdown`, `requests`, `beautifulsoup4`
- [x] Write `requirements.txt`
- [x] Write `.gitignore` (excludes `.venv/`, `data/`, `reports/`)
- [x] Write `config.py` with all settings
- [x] Write `tasks/lessons.md`

## Phase 2 — Data Layer ✅
- [x] Write `src/models.py` — `MatchOdds`, `SteamAlert` dataclasses
- [x] Write `DatabaseManager` with sqlite3 DDL (matches, odds, steam_alerts tables)
- [x] Implement `generate_match_id()` — MD5 hash, player-order-independent
- [x] Implement all DB methods: upsert_match, insert_odds, get_baseline_odds, insert_steam_alert, etc.

## Phase 1 — Scraping Layer ✅
- [x] Write `src/scraper.py` — `OddsAPIClient` class
- [x] Implement `get_tennis_events()` with quota tracking headers
- [x] Implement `parse_odds_api_response()` — best odds across bookmakers
- [x] Implement `classify_tournament()` — level pattern matching
- [x] Implement `classify_surface()` — surface from tournament name
- [x] Implement `get_tennis_odds()` top-level function

## Phase 3 — Steam Detection ✅
- [x] Write `src/steam.py`
- [x] Implement `calc_implied_prob()`, `calc_pct_change()`, `calc_pct_change_norm()`
- [x] Implement `classify_signal()` — SHARP_MOVE / SUSPECTED_RLM / UNDERDOG_STEAM / FAVORITE_DRIFT
- [x] Implement `detect_steam()` — cycle deduplication via `alert_exists_this_cycle()`

## Phase 4 — Report Generator ✅
- [x] Write `src/reporter.py`
- [x] Header section (timestamp, match count, alert count, source)
- [x] Steam alerts table (sorted by Δ norm, bold flagged player)
- [x] All matches grouped by level, with delta columns
- [x] Pro signals: surface mismatches, injury watch, RLM notes
- [x] `save_report()` and `cleanup_old_reports()`

## Phase 4b — Email Delivery ✅
- [x] Write `src/emailer.py`
- [x] Gmail SMTP via `smtplib` + STARTTLS
- [x] Multipart HTML + plain text
- [x] Markdown → HTML via `markdown` package with table extension
- [x] Subject line: `[STEAM ALERT xN]` prefix when alerts present
- [x] Graceful failure (logs error, never crashes scheduler)

## Phase 5 — Scheduler ✅
- [x] Write `src/scheduler.py` — `run_cycle()` function
- [x] Write `main.py` — `BlockingScheduler`, `--once` flag, graceful shutdown
- [x] Initial cycle runs immediately on startup
- [x] `max_instances=1` prevents overlap

## Phase 6 — Pro Signals ✅
- [x] `PLAYER_PREFERRED_SURFACE` dict in `src/steam.py` (~60 players)
- [x] `detect_surface_mismatches()` in `src/steam.py`
- [x] `fetch_injury_news()` in `src/scraper.py` (60-min cache, ATP + WTA)
- [x] `match_injury_to_players()` cross-reference

## Phase 7 — Verification
- [x] Write `test_steam.py` — unit + integration tests
- [ ] **Run tests** — `.venv/Scripts/python test_steam.py`
- [ ] **Single cycle test** — set `ODDS_API_KEY` and run `python main.py --once`
- [ ] Verify `data/tennis.db` created with correct tables
- [ ] Verify `reports/` has one `.md` file
- [ ] Verify email arrives at tommcgrath88@gmail.com
- [ ] Run for 2 full cycles (40 min) — confirm 2 reports + steady DB growth
- [ ] Check `data/agent.log` for errors

---

## Before Running — Setup Checklist

1. **Get a free Odds API key:**
   - Go to https://the-odds-api.com — free tier, no credit card
   - `set ODDS_API_KEY=your_key_here`

2. **Gmail App Password:**
   - Google Account → Security → 2-Step Verification → App Passwords
   - Generate for "Mail / Windows Computer"
   - `set GMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx`

3. **Run once to verify:**
   ```
   .venv\Scripts\python main.py --once
   ```

---

## Review (fill in after implementation)

- [ ] All unit tests passing
- [ ] Single --once cycle generates valid report
- [ ] Email received at tommcgrath88@gmail.com
- [ ] Steam detection verified with simulated data
- [ ] 2-cycle continuous run tested
