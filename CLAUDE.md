## Workflow Orchestration for Tennis Steamer Alert Agent

### 1. Plan Mode Default
- Enter plan mode for ANY non-trivial task (e.g., scraping logic, data storage design, alert thresholds, or report formatting – anything with 3+ steps or decisions involving betting signals)
- If something goes sideways (e.g., scraping fails due to site changes or false positive alerts), STOP and re-plan immediately – don't keep pushing
- Use plan mode for verification steps, not just building (e.g., simulate price movements to test alerts)
- Write detailed specs upfront to reduce ambiguity, including how to incorporate pro gambler insights like reverse line movements or injury signals

### 2. Subagent Strategy
- Use subagents liberally to keep main context window clean (e.g., one for scraping Stake.com, one for analyzing tennis tournament data, one for generating reports)
- Offload research, exploration, and parallel analysis to subagents (e.g., research additional betting signals like surface impacts or live momentum shifts)
- For complex problems (e.g., handling dynamic odds pages or integrating external news APIs), throw more compute at it via subagents
- One task per subagent for focused execution (e.g., Subagent 1: Scrape and store initial odds; Subagent 2: Detect 3%+ movements and flag RLM)

### 3. Self-Improvement Loop
- After ANY correction from the user: update `tasks/lessons.md` with the pattern (e.g., "Avoid over-scraping to prevent IP bans – implement rotating proxies")
- Write rules for yourself that prevent the same mistake (e.g., "Always test scraping on a dummy site before live")
- Ruthlessly iterate on these lessons until mistake rate drops, thinking like a pro gambler: prioritize signals that maximize edge
- Review lessons at session start for relevant project (e.g., recall past tennis-specific market quirks like clay-court volatility)

### 4. Verification Before Done
- Never mark a task complete without proving it works (e.g., run a full 20-min cycle simulation with mock data showing a 4% price move)
- Diff behavior between main and your changes when relevant (e.g., compare baseline scraper vs. one with added RLM detection)
- Ask yourself: "Would a professional gambler approve this edge-detection logic?"
- Run tests, check logs, demonstrate correctness (e.g., generate sample reports with/without movements, verify 3% threshold accuracy)

### 5. Demand Elegance (Balanced)
- For non-trivial changes (e.g., report formatting or signal integration): pause and ask "is there a more elegant way?" (e.g., use Pandas for clean dataframes instead of raw lists)
- If a fix feels hacky (e.g., brittle XPath for scraping): "Knowing everything I know now, implement the elegant solution" (e.g., use APIs if available or robust selectors)
- Skip this for simple, obvious fixes – don't over-engineer (e.g., basic scheduling with cron is fine)
- Challenge your own work before presenting it: "Does this capture steamers effectively without false alerts?"

### 6. Autonomous Bug Fixing
- When given a bug report (e.g., "Alerts missing on WTA 500 matches"): just fix it. Don't ask for hand-holding
- Point at logs, errors, failing tests – then resolve them (e.g., debug why initial odds weren't captured)
- Zero context switching required from the user
- Go fix failing CI tests or scraping errors without being told how (e.g., handle Stake.com anti-bot measures proactively)

## Task Management
1. Plan First: Write plan to `tasks/todo.md` with checkable items (e.g., [ ] Define tennis levels from table; [ ] Implement 20-min scraper loop)
2. Verify Plan: Check in before starting implementation (e.g., confirm Stake.com scraping feasibility and legal notes)
3. Track Progress: Mark items complete as you go (e.g., [x] Set up DB for odds history)
4. Explain Changes: High-level summary at each step (e.g., "Added RLM detection to flag sharp action")
5. Document Results: Add review section to `tasks/todo.md` (e.g., "Tested with 5% mock move: Alert fired correctly")
6. Capture Lessons: Update `tasks/lessons.md` after corrections (e.g., "Incorporate weather APIs for outdoor slams to enhance signals")

## Core Principles
- Simplicity First: Make every change as simple as possible. Impact minimal code (e.g., use Selenium only if needed; prefer requests/BS4).
- No Laziness: Find root causes (e.g., why a price move was missed). No temporary fixes. Pro gambler standards: Maximize signal accuracy for betting edge.
- Minimal Impact: Changes should only touch what's necessary. Avoid introducing bugs (e.g., don't scrape unrelated pages; focus on tennis odds sections).
- Pro Gambler Mindset: Always add value-adding aspects like alerting on injuries (scrape ATP/WTA news), surface mismatches, or volume spikes. Prioritize signals where market "speaks volumes" (e.g., underdog steam in early rounds).

## Agent Configuration (as built)
- **Markets:** PRE-MATCH ONLY — in-play events are always excluded (filtered by `commence_time`)
- **Timezone:** `Europe/Dublin` (Irish Standard Time / GMT, handles DST automatically)
- **Schedule:** Every 45 minutes, 09:00–22:00 Irish time
- **Source:** The Odds API (The Odds API key + Gmail App Password stored in `.env`)
- **Stack:** Python 3.14, APScheduler (BlockingScheduler), sqlite3, smtplib, requests/BS4