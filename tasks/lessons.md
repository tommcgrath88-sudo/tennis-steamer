# Lessons Learned

## 2026-03-04 — Project Init
- Stake.com requires Cloudflare bypass and violates ToS; The Odds API is the correct legal source.
- Use raw sqlite3 (stdlib) over SQLAlchemy for simple 3-table schemas — zero install friction.
- BlockingScheduler (not AsyncIOScheduler) is correct for standalone CLI agents with no event loop.
- Sort player names alphabetically before hashing match_id — APIs return home/away inconsistently.
- Normalized implied probability change `(curr - base) / (1 - base)` removes overround distortion; use as primary signal, not raw pct change.
