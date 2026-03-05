"""
Unit + integration tests for the Tennis Steamer Agent.
Run with: .venv/Scripts/python test_steam.py
No external dependencies required for core math tests.
"""

import sys
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from src.models import DatabaseManager, MatchOdds, SteamAlert, generate_match_id
from src.steam import (
    calc_implied_prob,
    calc_pct_change,
    calc_pct_change_norm,
    classify_signal,
    detect_surface_mismatches,
    detect_steam,
)
from src.reporter import generate_report, calc_norm_delta
from src.scraper import classify_tournament, classify_surface, parse_odds_api_response


def make_match(
    p1="Djokovic", p2="Alcaraz", tournament="Australian Open",
    p1_odds=1.65, p2_odds=2.30, surface="hard", level="grand_slam",
) -> MatchOdds:
    return MatchOdds(
        match_id=generate_match_id(tournament, p1, p2),
        tournament=tournament,
        level=level,
        surface=surface,
        player1=p1,
        player2=p2,
        p1_odds=p1_odds,
        p2_odds=p2_odds,
        p1_implied=round(1.0 / p1_odds, 6),
        p2_implied=round(1.0 / p2_odds, 6),
        scraped_at=datetime.now(timezone.utc),
        source="odds_api",
    )


def make_db() -> DatabaseManager:
    """In-memory SQLite database for tests."""
    db = DatabaseManager.__new__(DatabaseManager)
    import sqlite3
    db._conn = sqlite3.connect(":memory:")
    db._conn.row_factory = sqlite3.Row
    db.create_tables()
    return db


class TestImpliedProbMath(unittest.TestCase):
    def test_basic(self):
        self.assertAlmostEqual(calc_implied_prob(2.0), 0.5)
        self.assertAlmostEqual(calc_implied_prob(1.5), 0.6667, places=3)
        self.assertAlmostEqual(calc_implied_prob(4.0), 0.25)

    def test_invalid_odds(self):
        with self.assertRaises(ValueError):
            calc_implied_prob(1.0)
        with self.assertRaises(ValueError):
            calc_implied_prob(0.5)

    def test_pct_change_raw(self):
        # 0.50 → 0.53 = +6%
        self.assertAlmostEqual(calc_pct_change(0.50, 0.53), 6.0)
        # 0.60 → 0.57 = -5%
        self.assertAlmostEqual(calc_pct_change(0.60, 0.57), -5.0)

    def test_pct_change_norm(self):
        # baseline=0.50, current=0.53
        # (0.53-0.50) / (1-0.50) * 100 = 0.03/0.50*100 = 6.0
        self.assertAlmostEqual(calc_pct_change_norm(0.50, 0.53), 6.0)
        # baseline=0.35, current=0.39
        # (0.39-0.35) / 0.65 * 100 = 6.154
        self.assertAlmostEqual(calc_pct_change_norm(0.35, 0.39), 6.154, places=2)

    def test_calc_norm_delta(self):
        self.assertAlmostEqual(calc_norm_delta(0.50, 0.53), 6.0)
        self.assertAlmostEqual(calc_norm_delta(0, 0.5), 0.0)  # edge case


class TestSignalClassification(unittest.TestCase):
    def test_sharp_move_beats_underdog_steam(self):
        # underdog (0.35) with +6% norm → SHARP_MOVE (>=5%) takes priority
        sig = classify_signal(0.35, 0.35 + 0.65 * 0.06, 6.0)
        self.assertEqual(sig, "SHARP_MOVE")

    def test_underdog_steam(self):
        # underdog (0.35) with +3.5% norm → SUSPECTED_RLM (underdog shortening)
        sig = classify_signal(0.35, 0.35 + 0.65 * 0.035, 3.5)
        self.assertIn(sig, ("SUSPECTED_RLM", "UNDERDOG_STEAM"))

    def test_favorite_drift(self):
        # favorite (0.65) drifts -4% → FAVORITE_DRIFT
        sig = classify_signal(0.65, 0.65 - 0.35 * 0.04, -4.0)
        self.assertEqual(sig, "FAVORITE_DRIFT")

    def test_below_threshold(self):
        # 2% change — below 3% threshold → None
        sig = classify_signal(0.50, 0.51, 2.0)
        self.assertIsNone(sig)

    def test_no_signal_at_zero(self):
        sig = classify_signal(0.50, 0.50, 0.0)
        self.assertIsNone(sig)


class TestMatchId(unittest.TestCase):
    def test_deterministic(self):
        id1 = generate_match_id("Australian Open", "Djokovic", "Alcaraz")
        id2 = generate_match_id("Australian Open", "Djokovic", "Alcaraz")
        self.assertEqual(id1, id2)

    def test_order_independent(self):
        id1 = generate_match_id("Australian Open", "Djokovic", "Alcaraz")
        id2 = generate_match_id("Australian Open", "Alcaraz", "Djokovic")
        self.assertEqual(id1, id2)

    def test_different_tournaments(self):
        id1 = generate_match_id("Australian Open", "A", "B")
        id2 = generate_match_id("Roland Garros", "A", "B")
        self.assertNotEqual(id1, id2)

    def test_length(self):
        mid = generate_match_id("X", "A", "B")
        self.assertEqual(len(mid), 12)


class TestDatabaseManager(unittest.TestCase):
    def setUp(self):
        self.db = make_db()

    def tearDown(self):
        self.db.close()

    def test_upsert_match_idempotent(self):
        m = make_match()
        self.db.upsert_match(m)
        self.db.upsert_match(m)  # second call should not raise
        rows = self.db.get_active_matches()
        self.assertEqual(len(rows), 1)

    def test_baseline_odds_first_reading(self):
        m = make_match()
        self.db.upsert_match(m)
        self.db.insert_odds(m)
        baseline = self.db.get_baseline_odds(m.match_id)
        self.assertIsNotNone(baseline)
        self.assertAlmostEqual(baseline[0], m.p1_implied, places=4)

    def test_baseline_returns_none_for_unknown(self):
        result = self.db.get_baseline_odds("nonexistent_id")
        self.assertIsNone(result)

    def test_odds_count(self):
        m = make_match()
        self.db.upsert_match(m)
        self.db.insert_odds(m)
        self.db.insert_odds(m)
        self.assertEqual(self.db.odds_count(m.match_id), 2)


class TestSteamDetection(unittest.TestCase):
    def setUp(self):
        self.db = make_db()

    def tearDown(self):
        self.db.close()

    def test_no_alert_on_first_seen(self):
        m = make_match()
        self.db.upsert_match(m)
        self.db.insert_odds(m)
        # detect_steam should see baseline = current → no alerts
        # But first call: baseline is returned, second call compares
        alerts = detect_steam([m], self.db)
        # On very first reading, baseline == current → delta = 0 → no alert
        self.assertEqual(len(alerts), 0)

    def test_alert_on_significant_shift(self):
        # Cycle 1: baseline
        m1 = make_match(p1_odds=2.85, p2_odds=1.45)  # p1 is underdog ~35%
        self.db.upsert_match(m1)
        self.db.insert_odds(m1)

        # Cycle 2: p1 shortens significantly (implied goes from 35% to 43%)
        m2 = make_match(p1_odds=2.30, p2_odds=1.55)  # p1 implied ~43%
        self.db.upsert_match(m2)
        self.db.insert_odds(m2)

        alerts = detect_steam([m2], self.db)
        self.assertTrue(len(alerts) >= 1)
        self.assertEqual(alerts[0].player, m2.player1)
        self.assertEqual(alerts[0].direction, "UP")
        self.assertIn(alerts[0].signal_type, ("SHARP_MOVE", "SUSPECTED_RLM", "UNDERDOG_STEAM"))

    def test_no_alert_on_small_move(self):
        m1 = make_match(p1_odds=1.65, p2_odds=2.30)
        self.db.upsert_match(m1)
        self.db.insert_odds(m1)

        # Tiny move — less than 3%
        m2 = make_match(p1_odds=1.67, p2_odds=2.27)
        self.db.upsert_match(m2)
        self.db.insert_odds(m2)

        alerts = detect_steam([m2], self.db)
        self.assertEqual(len(alerts), 0)


class TestSurfaceMismatch(unittest.TestCase):
    def test_detects_clay_player_on_hard(self):
        m = make_match(p1="Rafael Nadal", p2="Daniil Medvedev", surface="hard")
        mismatches = detect_surface_mismatches([m])
        players = [sm["player"] for sm in mismatches]
        self.assertIn("Rafael Nadal", players)

    def test_no_mismatch_on_unknown_surface(self):
        m = make_match(p1="Rafael Nadal", p2="Daniil Medvedev", surface="unknown")
        mismatches = detect_surface_mismatches([m])
        self.assertEqual(len(mismatches), 0)


class TestTournamentClassifier(unittest.TestCase):
    def test_grand_slams(self):
        self.assertEqual(classify_tournament("Australian Open"), "grand_slam")
        self.assertEqual(classify_tournament("Roland Garros"), "grand_slam")
        self.assertEqual(classify_tournament("Wimbledon"), "grand_slam")
        self.assertEqual(classify_tournament("US Open"), "grand_slam")

    def test_masters(self):
        self.assertEqual(classify_tournament("ATP Masters 1000 Madrid"), "masters_1000")
        self.assertEqual(classify_tournament("Indian Wells Masters"), "masters_1000")

    def test_unknown(self):
        self.assertEqual(classify_tournament("Bogota Open"), "unknown")


class TestReportGeneration(unittest.TestCase):
    def setUp(self):
        self.db = make_db()

    def tearDown(self):
        self.db.close()

    def test_empty_report_is_valid(self):
        now = datetime.now(timezone.utc)
        report = generate_report([], [], self.db, now)
        self.assertIn("Tennis Steamer Report", report)
        self.assertIn("No steam moves detected", report)
        self.assertIn("0 matches", report)

    def test_report_with_matches(self):
        matches = [
            make_match("Djokovic", "Alcaraz", "Australian Open"),
            make_match("Swiatek", "Gauff", "Roland Garros", surface="clay", level="grand_slam"),
        ]
        for m in matches:
            self.db.upsert_match(m)
            self.db.insert_odds(m)

        now = datetime.now(timezone.utc)
        report = generate_report(matches, [], self.db, now)
        self.assertIn("Djokovic", report)
        self.assertIn("Swiatek", report)
        self.assertIn("Grand Slams", report)
        self.assertIn("2 matches", report)

    def test_report_with_alerts(self):
        m = make_match()
        self.db.upsert_match(m)
        self.db.insert_odds(m)
        alert = SteamAlert(
            match_id=m.match_id,
            timestamp=datetime.now(timezone.utc),
            player="Djokovic",
            direction="UP",
            baseline_prob=0.35,
            current_prob=0.43,
            pct_change=22.9,
            pct_change_norm=12.3,
            signal_type="SHARP_MOVE",
        )
        now = datetime.now(timezone.utc)
        report = generate_report([m], [alert], self.db, now)
        self.assertIn("SHARP_MOVE", report)
        self.assertIn("Djokovic", report)
        self.assertIn("1 matches", report)
        self.assertIn("Steam Alerts:** 1", report)


class TestOddsApiParsing(unittest.TestCase):
    def test_parse_valid_event(self):
        raw = [
            {
                "id": "abc123",
                "sport_title": "Tennis ATP - Australian Open",
                "home_team": "Novak Djokovic",
                "away_team": "Carlos Alcaraz",
                "bookmakers": [
                    {
                        "key": "stake",
                        "markets": [
                            {
                                "key": "h2h",
                                "outcomes": [
                                    {"name": "Novak Djokovic", "price": 1.65},
                                    {"name": "Carlos Alcaraz", "price": 2.30},
                                ],
                            }
                        ],
                    }
                ],
            }
        ]
        results = parse_odds_api_response(raw)
        self.assertEqual(len(results), 1)
        r = results[0]
        self.assertAlmostEqual(r.p1_odds, 1.65)
        self.assertAlmostEqual(r.p2_odds, 2.30)
        self.assertEqual(r.player1, "Novak Djokovic")
        self.assertEqual(r.level, "grand_slam")

    def test_skip_event_without_odds(self):
        raw = [
            {
                "id": "no_odds",
                "sport_title": "Tennis ATP - Australian Open",
                "home_team": "Player A",
                "away_team": "Player B",
                "bookmakers": [],
            }
        ]
        results = parse_odds_api_response(raw)
        self.assertEqual(len(results), 0)


if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite = loader.discover(start_dir=".", pattern="test_*.py")
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
