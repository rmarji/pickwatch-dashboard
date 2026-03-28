"""
Tests for sport-specific scoring thresholds.

Verifies sport-calibrated recommendation thresholds based on
historical win rates (52 resolved picks, 2026-03-28):
- NBA BET: 67% WR (n=7) → standard BET thresholds
- NHL BET: 50% WR (n=23) → stricter BET thresholds
- MLB: NO DATA (strict early-season thresholds)
- STRONG BET: DISABLED for all sports (47.6% WR overall vs BET at 53.6%)
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

    def test_nba_no_strong_bet_after_cal(self):
        """NBA STRONG BET disabled after calibration showed 44% WR (worse than BET)."""
        # NBA now caps at BET (same as NHL/MLB)
        rec = self._get_rec("NBA", 25, 76)
        self.assertEqual(rec, "BET", "NBA should return BET (STRONG BET disabled, 44% WR)")

    def test_nba_bet_at_edge_15(self):
        """NBA BET at edge >= 15, conf >= 65."""
        rec = self._get_rec("NBA", 16, 68)
        self.assertEqual(rec, "BET")

    def test_nba_lean_at_edge_8(self):
        """NBA LEAN at edge >= 8, conf >= 55."""
        rec = self._get_rec("NBA", 9, 58)
        self.assertEqual(rec, "LEAN")

    def test_nba_pass_on_negative_edge(self):
        """NBA PASS on negative edge."""
        rec = self._get_rec("NBA", -5, 80)
        self.assertEqual(rec, "PASS")

    # ─── Differential Tests ──────────────────────────────────────────────

    def test_nba_vs_nhl_same_edge_same_rec(self):
        """Same edge=25 returns BET for both NBA and NHL (STRONG BET disabled)."""
        nba_rec = self._get_rec("NBA", 25, 78)
        nhl_rec = self._get_rec("NHL", 25, 78)
        # Both now cap at BET (STRONG BET disabled)
        self.assertEqual(nba_rec, "BET")
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

    def test_mlb_uses_strict_early_season_thresholds(self):
        """MLB uses strict early-season thresholds (STRONG BET disabled, bet_edge=35).
        
        Early-season expert panels are small → consensus inflates edge artificially.
        MLB edges of 25% that would be BET in NBA → LEAN in MLB until calibrated.
        Recalibrate after 30+ resolved picks (~late April 2026).
        """
        # Edge 25/conf 78: NBA = BET, MLB = LEAN (strict thresholds)
        mlb_rec = self._get_rec("MLB", 25, 78)
        self.assertEqual(mlb_rec, "LEAN", "MLB edge=25 should be LEAN (strict early-season)")
        
        # Edge 40/conf 85: MLB = BET (above 35% edge threshold)
        mlb_bet_rec = self._get_rec("MLB", 40, 85)
        self.assertEqual(mlb_bet_rec, "BET", "MLB edge=40/conf=85 should be BET")
        
        # Edge 40/conf 95: MLB = BET (STRONG BET disabled, caps at BET)
        mlb_strong_rec = self._get_rec("MLB", 40, 95)
        self.assertEqual(mlb_strong_rec, "BET", "MLB STRONG BET should be disabled (no WR data)")

    def test_unknown_sport_uses_default(self):
        """Unknown sport falls back to DEFAULT thresholds (STRONG BET disabled)."""
        unknown_rec = self._get_rec("UNKNOWN", 25, 78)
        default_rec = self._get_rec("DEFAULT", 25, 78)
        self.assertEqual(unknown_rec, default_rec)

    # ─── score_pick Integration Tests ────────────────────────────────────

    def test_score_pick_passes_sport_to_recommendation(self):
        """score_pick correctly passes sport to get_recommendation."""
        # NHL pick with edge that would be BET in NBA
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
        # NBA with high confidence/edge should be BET (STRONG BET disabled)
        self.assertEqual(nba_pick.recommendation, "BET",
                         "NBA should return BET (STRONG BET disabled)")

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