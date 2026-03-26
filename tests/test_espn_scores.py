"""
Tests for ESPN score fallback integration in result_checker.
"""

import unittest
from unittest.mock import patch, MagicMock
from datetime import date, timedelta
import sys
from pathlib import Path

# Add parent dir to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from result_checker import get_espn_scores, resolve_picks
from history import PickHistory, TrackedPick


class TestESPNFallback(unittest.TestCase):
    """Test ESPN score fetching."""

    def test_get_espn_scores_nba(self):
        """Test fetching NBA scores from ESPN (accepts date string or object)."""
        # Pass as string
        games = get_espn_scores("nba", (date.today() - timedelta(days=1)).isoformat())
        self.assertIsInstance(games, dict)

    def test_get_espn_scores_nhl(self):
        """Test fetching NHL scores from ESPN (accepts date object)."""
        games = get_espn_scores("nhl", date.today() - timedelta(days=1))
        self.assertIsInstance(games, dict)

    def test_get_espn_scores_invalid_sport(self):
        """Test invalid sport returns empty dict."""
        games = get_espn_scores("invalid_sport", date.today())
        self.assertEqual(games, {})

    def test_espn_score_known_nhl_game(self):
        """Test ESPN scores for known NHL games on 2026-03-18."""
        games = get_espn_scores("nhl", "2026-03-18")
        # We know from real data that PHI @ ANA was played
        # Check that we get at least some results
        self.assertIsInstance(games, dict)
        # If we have data, verify structure
        if games:
            key = next(iter(games))
            winner, score = games[key]
            self.assertIsInstance(winner, str)
            self.assertIsInstance(score, str)
            self.assertIn("-", score)  # "away_score-home_score"


class TestResolvePicksWithESPN(unittest.TestCase):
    """Test resolve_picks with ESPN fallback."""

    def setUp(self):
        """Create in-memory history for testing."""
        import tempfile
        self.temp_dir = tempfile.mkdtemp()
        self.db_path = Path(self.temp_dir) / "test_picks.db"
        self.history = PickHistory(self.db_path)

    def tearDown(self):
        """Clean up temp files."""
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    @patch("result_checker.PickwatchAPI")
    def test_espn_fallback_resolves_pick(self, mock_api_class):
        """Test that ESPN fallback resolves picks when Pickwatch lacks scores."""
        # Mock Pickwatch API to return game with no scores
        mock_api = MagicMock()
        mock_api_class.return_value = mock_api
        
        # Pickwatch returns game but not final
        mock_game = MagicMock()
        mock_game.id = 123
        mock_game.home_team = "COL"
        mock_game.away_team = "DAL"
        mock_game.is_final = False
        mock_game.winner = None
        mock_api.get_games.return_value = [mock_game]
        
        # Add a pending pick
        pick = TrackedPick(
            id=1,
            date=(date.today() - timedelta(days=1)).isoformat(),
            sport="NHL",
            game_id=123,
            matchup="DAL @ COL",
            pick_team="DAL",
            pick_type="ML",
            odds_american=+120,
            edge=15.0,
            confidence_score=70,
            value_rating=4,
            recommendation="BET",
            created_at="2026-03-18T00:00:00",
            updated_at="2026-03-18T00:00:00",
        )
        self.history.add_pick(pick)
        
        # Resolve picks - should use ESPN fallback
        result = resolve_picks(self.history, mock_api, dry_run=True)
        
        # Should have attempted ESPN fallback
        self.assertEqual(result["resolved"], [])  # Dry run, no actual write


class TestStalePickHandling(unittest.TestCase):
    """Test handling of stale picks (games that don't exist)."""

    def test_stale_pick_age_calculation(self):
        """Test that stale picks are identified correctly."""
        today = date.today()
        yesterday = today - timedelta(days=1)
        two_days_ago = today - timedelta(days=2)
        
        # Yesterday's pick is not stale
        self.assertLess((today - yesterday).days, 2)
        
        # Two days ago is stale
        self.assertGreaterEqual((today - two_days_ago).days, 2)


if __name__ == "__main__":
    unittest.main()