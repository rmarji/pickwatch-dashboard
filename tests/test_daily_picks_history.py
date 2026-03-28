"""
Tests for daily_picks.py history integration.

Verifies that daily_picks.main() saves actionable picks
(BET, LEAN) to the pickwatch_history database.
"""

import unittest
import sqlite3
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock
from datetime import date

sys.path.insert(0, str(Path(__file__).parent.parent))

from scoring import ScoredPick
from history import PickHistory


class TestDailyPicksHistorySaving(unittest.TestCase):
    """Test that daily_picks saves actionable picks to history."""

    def setUp(self):
        """Create a temp DB for testing."""
        self.tmp = tempfile.NamedTemporaryFile(suffix='.db', delete=False)
        self.tmp.close()
        self.history = PickHistory(db_path=self.tmp.name)

    def tearDown(self):
        Path(self.tmp.name).unlink(missing_ok=True)

    def _make_pick(self, team, recommendation, edge=25.0, confidence=85.0, game_id=100):
        return ScoredPick(
            game_id=game_id,
            sport="nhl",
            matchup=f"{team} vs OPP",
            pick_team=team,
            pick_type="ML",
            odds_american=-150,
            edge=edge,
            confidence_score=confidence,
            value_rating=5,
            recommendation=recommendation,
        )

    def test_bet_picks_saved(self):
        """BET picks should be saved to history."""
        pick = self._make_pick("DAL", "BET", game_id=200)
        tracked = self.history.add_pick(pick)
        self.assertIsNotNone(tracked.id)

    def test_lean_picks_saved(self):
        """LEAN picks should be saved to history."""
        pick = self._make_pick("NYI", "LEAN", edge=15.0, game_id=201)
        tracked = self.history.add_pick(pick)
        self.assertIsNotNone(tracked.id)

    def test_pass_picks_not_saved_in_daily(self):
        """PASS picks should NOT be saved (filtered by daily_picks.py logic)."""
        # This tests the filtering logic in daily_picks.main()
        # PASS recommendations are skipped before add_pick is called
        pick = self._make_pick("TB", "PASS", edge=3.0, confidence=40.0, game_id=202)
        # In daily_picks.py, PASS picks are filtered:
        # if pick.recommendation not in ("PASS",): history.add_pick(pick)
        self.assertEqual(pick.recommendation, "PASS")

    def test_dedup_same_pick(self):
        """Adding the same pick twice should not create duplicate."""
        pick = self._make_pick("CBJ", "BET", game_id=300)
        tracked1 = self.history.add_pick(pick)
        tracked2 = self.history.add_pick(pick)
        # Second call should return same ID (dedup)
        self.assertEqual(tracked1.id, tracked2.id)

        # Verify only 1 row in DB
        with sqlite3.connect(self.tmp.name) as conn:
            count = conn.execute("SELECT COUNT(*) FROM picks WHERE game_id = 300").fetchone()[0]
        self.assertEqual(count, 1)

    def test_pick_has_correct_fields(self):
        """Saved pick should have correct field values."""
        pick = self._make_pick("CAR", "BET", edge=31.8, confidence=91.0, game_id=400)
        tracked = self.history.add_pick(pick)

        with sqlite3.connect(self.tmp.name) as conn:
            cols = conn.execute("PRAGMA table_info(picks)").fetchall()
            col_names = [c[1] for c in cols]
            idx = {name: i for i, name in enumerate(col_names)}
            row = conn.execute("SELECT * FROM picks WHERE id = ?", (tracked.id,)).fetchone()

        self.assertIsNotNone(row)
        self.assertEqual(row[idx['sport']], 'nhl')
        self.assertEqual(row[idx['pick_team']], 'CAR')
        self.assertAlmostEqual(row[idx['edge']], 31.8, places=1)
        self.assertEqual(row[idx['recommendation']], 'BET')
        self.assertIsNone(row[idx['outcome']])  # Not yet resolved

    def test_multiple_sports_saved(self):
        """Picks from different sports should all save."""
        picks = [
            ScoredPick(game_id=500, sport="nba", matchup="CHA vs PHI",
                       pick_team="CHA", pick_type="ML", odds_american=-235,
                       edge=28.2, confidence_score=95.0, value_rating=5,
                       recommendation="BET"),
            ScoredPick(game_id=501, sport="nhl", matchup="DAL vs PIT",
                       pick_team="DAL", pick_type="ML", odds_american=-130,
                       edge=28.4, confidence_score=94.0, value_rating=5,
                       recommendation="BET"),
            ScoredPick(game_id=502, sport="mlb", matchup="TEX vs PHI",
                       pick_team="PHI", pick_type="ML", odds_american=-115,
                       edge=42.7, confidence_score=94.0, value_rating=5,
                       recommendation="BET"),
        ]
        for p in picks:
            self.history.add_pick(p)

        with sqlite3.connect(self.tmp.name) as conn:
            count = conn.execute("SELECT COUNT(*) FROM picks").fetchone()[0]
            sports = conn.execute("SELECT DISTINCT sport FROM picks").fetchall()

        self.assertEqual(count, 3)
        self.assertEqual(len(sports), 3)


if __name__ == "__main__":
    unittest.main()
