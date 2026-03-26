"""
Tests for sport-specific scoring thresholds.

Verifies that NHL uses stricter thresholds than NBA based on
historical win rates (38 resolved picks, cleaned data 2026-03-24):
- NBA: 67% WR (n=13) → standard thresholds
- NHL: 50% WR (n=25) → BET max (no STRONG BET until WR improves)
"""

import unittest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from scoring import ConfidenceScorer


class TestSportSpecificThresholds(unittest.TestCase):
    """Test sport-calibrated recommendation thresholds."""

    def setUp(self):
        self.scorer = ConfidenceScorer()

    def _get_rec(self, sport, edge, confidence):
        """Get recommendation for given sport/edge/confidence."""
        rec, _ = self.scorer.get_recommendation(confidence, edge, 4, sport)
        return rec

    # ─── NHL Threshold Tests ──────────────────────────────────────────────

    def test_nhl_no_strong_bet_ever(self):
        """NHL STRONG BET is disabled — 50% WR not sufficient signal."""
        # Even at max edge, NHL should never return STRONG BET
        rec = self._get_rec("NHL", 50, 99)
        self.assertNotEqual(rec, "STRONG BET", "NHL should never return STRONG BET (50% WR)")
        self.assertEqual(rec, "BET", "NHL max confidence should still be BET")

    def test_nhl_no_strong_bet_at_edge_30(self):
        """NHL edge=30 returns BET (not STRONG BET) due to 50% WR."""
        rec = self._get_rec("NHL", 30, 80)
        self.assertEqual(rec, "BET")

    def test_nhl_no_strong_bet_at_edge_35(self):
        """NHL edge=35 returns BET (not STRONG BET) due to 50% WR."""
        rec = self._get_rec("NHL", 35, 82)
        self.assertEqual(rec, "BET")

    def test_nhl_requires_edge_25_for_bet(self):
        """NHL BET requires edge >= 25, conf >= 75 (raised from edge=20)."""
        # Edge 22 should be LEAN for NHL, not BET
        rec = self._get_rec("NHL", 22, 78)
        self.assertNotEqual(rec, "BET", "NHL edge=22 should not be BET")
        self.assertEqual(rec, "LEAN")

    def test_nhl_bet_at_edge_25(self):
        """NHL BET fires at edge >= 25, conf >= 75."""
        rec = self._get_rec("NHL", 25, 76)
        self.assertEqual(rec, "BET")

    def test_nhl_lean_at_edge_15(self):
        """NHL LEAN fires at edge >= 15, conf >= 65."""
        rec = self._get_rec("NHL", 16, 67)
        self.assertEqual(rec, "LEAN")

    def test_nhl_pass_below_lean_threshold(self):
        """NHL below lean threshold → LEAN (positive edge still considered)."""
        # Edge below 12 still LEAN due to positive EV fallthrough
        rec = self._get_rec("NHL", 5, 60)
        self.assertEqual(rec, "LEAN")

    def test_nhl_pass_on_negative_edge(self):
        """NHL PASS on negative edge."""
        rec = self._get_rec("NHL", -3, 80)
        self.assertEqual(rec, "PASS")

    # ─── NBA Threshold Tests ──────────────────────────────────────────────

    def test_nba_strong_bet_at_edge_25(self):
        """NBA STRONG BET at edge >= 25, conf >= 75."""
        rec = self._get_rec("NBA", 25, 76)
        self.assertEqual(rec, "STRONG BET")

    def test_nba_bet_at_edge_15(self):
        """NBA BET at edge >= 15, conf >= 65."""
        rec = self._get_rec("NBA", 16, 68)
        self.assertEqual(rec, "BET")

    def test_nba_lean_at_edge_8(self):
        """NBA LEAN at edge >= 8, conf >= 55."""
        rec = self._get_rec("NBA", 9, 58)
        self.assertEqual(rec, "LEAN")

    # ─── Differential Tests ──────────────────────────────────────────────

    def test_nba_vs_nhl_same_edge_different_rec(self):
        """Same edge=25 gets STRONG BET for NBA but BET for NHL."""
        nba_rec = self._get_rec("NBA", 25, 78)
        nhl_rec = self._get_rec("NHL", 25, 78)
        self.assertEqual(nba_rec, "STRONG BET")
        self.assertEqual(nhl_rec, "BET")

    def test_nba_vs_nhl_edge_22_different_rec(self):
        """Edge=22, conf=78: NBA gets BET, NHL gets LEAN (NHL requires edge >= 25)."""
        nba_rec = self._get_rec("NBA", 22, 78)
        nhl_rec = self._get_rec("NHL", 22, 78)
        self.assertEqual(nba_rec, "BET")
        self.assertEqual(nhl_rec, "LEAN")

    def test_nba_vs_nhl_edge_17_different_rec(self):
        """Edge=17: NBA gets BET, NHL gets LEAN."""
        nba_rec = self._get_rec("NBA", 17, 69)
        nhl_rec = self._get_rec("NHL", 17, 69)
        self.assertEqual(nba_rec, "BET")
        self.assertEqual(nhl_rec, "LEAN")

    # ─── Default (MLB) Threshold Tests ───────────────────────────────────

    def test_mlb_uses_default_thresholds(self):
        """MLB (unknown sport) uses DEFAULT thresholds (same as NBA)."""
        mlb_rec = self._get_rec("MLB", 25, 78)
        nba_rec = self._get_rec("NBA", 25, 78)
        self.assertEqual(mlb_rec, nba_rec)

    def test_unknown_sport_uses_default(self):
        """Unknown sport falls back to DEFAULT thresholds."""
        unknown_rec = self._get_rec("UNKNOWN", 25, 78)
        default_rec = self._get_rec("DEFAULT", 25, 78)
        self.assertEqual(unknown_rec, default_rec)

    # ─── score_pick Integration Tests ────────────────────────────────────

    def test_score_pick_passes_sport_to_recommendation(self):
        """score_pick correctly passes sport to get_recommendation."""
        # NHL pick with edge that would be STRONG BET in NBA
        nhl_pick = self.scorer.score_pick(
            1, "NHL", "A @ B", "A", "ML", -110,
            cpu_confidence=0.83, expert_pct=85, fan_pct=80
        )
        nba_pick = self.scorer.score_pick(
            1, "NBA", "A @ B", "A", "ML", -110,
            cpu_confidence=0.83, expert_pct=85, fan_pct=80
        )
        # NHL should NEVER be STRONG BET
        self.assertNotEqual(nhl_pick.recommendation, "STRONG BET",
                            "NHL should never return STRONG BET")
        # NBA with high confidence/edge should be STRONG BET
        if nba_pick.edge >= 25:
            self.assertEqual(nba_pick.recommendation, "STRONG BET")

    def test_nhl_pass_on_low_confidence(self):
        """NHL pick with low confidence returns PASS."""
        rec = self._get_rec("NHL", 25, 40)
        self.assertEqual(rec, "PASS")

    def test_case_insensitive_sport(self):
        """Sport names are case-insensitive."""
        upper = self._get_rec("NHL", 25, 78)
        lower = self._get_rec("nhl", 25, 78)
        mixed = self._get_rec("Nhl", 25, 78)
        self.assertEqual(upper, lower)
        self.assertEqual(upper, mixed)


if __name__ == "__main__":
    unittest.main(verbosity=2)
