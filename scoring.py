"""
Pickwatch Confidence Scoring System

Based on historical analysis of 3,965 MLB games (Mar-Apr 2024):
- +Edge bets: 70% win rate (best signal)
- 96%+ confidence: 60.8% win rate
- 3-4 star value: 66-69% win rate
- ML recommendations: 72.2% accurate

Live calibration (52 resolved picks, Mar 28 2026):
- BET tier:  15W/13L (53.6% WR) — working
- STRONG BET: 10W/11L (47.6% WR) — UNDERPERFORMING, DISABLED ALL SPORTS
  - Higher edge/confidence does NOT improve WR in current data
  - STRONG BET adds noise, not signal — reverting to BET max for all sports
  - Reenable only after 30+ STRONG BET picks at WR >60%

Sport-specific calibration (52 resolved picks, cleaned of duplicates):
- NBA: BET 4W/2L (67% WR, n=7) | STRONG BET 4W/5L (44%, n=9) → STRONG BET DISABLED
- NHL: BET 11W/11L (50% WR, n=23) | STRONG BET 6W/6L (50%, n=13) → STRONG BET DISABLED
- MLB: NO DATA (season starts Mar 28 2026) → STRICT thresholds (early-season edge inflation)
  - Early-season expert panels are small → consensus artificially inflates edge
  - STRONG BET disabled; BET requires 35%+ edge + 82% confidence until 30+ picks resolved

Updated: 2026-03-28 (STRONG BET disabled across all sports — 47.6% WR < BET tier 53.6% WR)
"""

from dataclasses import dataclass, field
from typing import Optional
from decimal import Decimal


@dataclass
class ScoredPick:
    """A pick with calculated confidence scores."""
    game_id: int
    sport: str
    matchup: str
    pick_team: str
    pick_type: str  # 'ML' or 'ATS'
    
    # Raw inputs
    odds_american: int = 0
    cpu_confidence: float = 0  # From premium picks API
    expert_pct: float = 0
    fan_pct: float = 0
    
    # Calculated scores
    implied_prob: float = 0
    true_prob: float = 0
    edge: float = 0
    confidence_score: float = 0
    value_rating: int = 0  # 1-5 stars
    
    # Final recommendation
    recommendation: str = ""  # "STRONG BET", "BET", "LEAN", "PASS"
    reasons: list = field(default_factory=list)
    
    @property
    def is_positive_ev(self) -> bool:
        return self.edge > 0
    
    @property
    def stars(self) -> str:
        return "⭐" * self.value_rating
    

class ConfidenceScorer:
    """
    Calculate confidence scores for picks.
    
    Scoring weights based on historical backtesting:
    - Edge (true prob vs implied): 40% weight (70% WR when positive)
    - CPU Confidence: 30% weight
    - Expert Consensus: 20% weight  
    - Expert vs Fan Divergence: 10% weight (contrarian signal)
    """
    
    # Weights from backtesting
    WEIGHT_EDGE = 0.40
    WEIGHT_CPU = 0.30
    WEIGHT_EXPERT = 0.20
    WEIGHT_CONTRARIAN = 0.10
    
    # Thresholds (tuned from historical data)
    MIN_CONFIDENCE = 50  # Minimum confidence to consider
    STRONG_CONFIDENCE = 75  # Strong bet threshold
    MIN_EDGE = 0  # Must be positive EV
    
    def american_to_implied_prob(self, odds: int) -> float:
        """Convert American odds to implied probability."""
        if odds == 0:
            return 0.5
        if odds > 0:
            return 100 / (odds + 100)
        else:
            return abs(odds) / (abs(odds) + 100)
    
    def calculate_true_prob(
        self,
        cpu_confidence: float,
        expert_pct: float,
        fan_pct: float,
    ) -> float:
        """
        Estimate true probability from multiple signals.
        
        Historical accuracy:
        - CPU (when available): 72.2%
        - Expert consensus: 53-57%
        - Fan consensus: 51-52%
        
        Contrarian edge: When experts differ from fans by >20%,
        experts are more reliable.
        """
        expert_vs_fan_diff = abs(expert_pct - fan_pct)
        
        if cpu_confidence > 0:
            # CPU available: weight it heavily
            true_prob = (
                cpu_confidence * 0.60 +
                (expert_pct / 100) * 0.30 +
                (fan_pct / 100) * 0.10
            )
        elif expert_vs_fan_diff > 20:
            # Strong contrarian signal: trust experts more
            true_prob = (expert_pct * 0.85 + fan_pct * 0.15) / 100
        else:
            # Normal: blend expert/fan
            true_prob = (expert_pct * 0.70 + fan_pct * 0.30) / 100
        
        return min(max(true_prob, 0.01), 0.99)
    
    def calculate_edge(self, true_prob: float, implied_prob: float) -> float:
        """Calculate edge (positive = good bet)."""
        return (true_prob - implied_prob) * 100
    
    def calculate_value_rating(self, edge: float, confidence: float) -> int:
        """
        Calculate 1-5 star rating.
        
        Historical insight: 3-4 stars (mid-value) performed best.
        """
        if edge < 0:
            return 2  # Negative EV
        
        # Combined score
        score = edge * 0.6 + confidence * 0.4
        
        if score >= 25:
            return 5
        elif score >= 18:
            return 4
        elif score >= 12:
            return 3
        elif score >= 6:
            return 2
        return 1
    
    def calculate_confidence_score(
        self,
        edge: float,
        cpu_confidence: float,
        expert_pct: float,
        expert_vs_fan_diff: float,
    ) -> float:
        """
        Calculate final confidence score (0-100).
        
        Adapts weights based on available signals.
        """
        # Normalize edge to 0-100 scale (cap at 20% edge)
        edge_score = min(max(edge, -20), 20) * 2.5 + 50
        
        # Expert consensus (already 0-100)
        expert_score = expert_pct
        
        # Contrarian signal (experts disagree with public)
        contrarian_score = min(expert_vs_fan_diff, 30) * 3.33  # 30% diff = 100
        
        if cpu_confidence > 0:
            # CPU available: use full weighting
            cpu_score = cpu_confidence * 100
            final = (
                edge_score * self.WEIGHT_EDGE +
                cpu_score * self.WEIGHT_CPU +
                expert_score * self.WEIGHT_EXPERT +
                contrarian_score * self.WEIGHT_CONTRARIAN
            )
        else:
            # No CPU: redistribute weights to edge + expert
            final = (
                edge_score * 0.50 +  # Edge gets more weight
                expert_score * 0.35 +  # Expert gets more weight
                contrarian_score * 0.15  # Contrarian bonus
            )
        
        return round(min(max(final, 0), 100), 1)
    
    # Sport-specific thresholds (calibrated from live results 2026-03-28)
    # STRONG BET disabled all sports: 47.6% WR (10W/11L) — worse than BET tier (53.6%)
    # BET tier working: NBA=67% WR (n=7), NHL=50% WR (n=23)
    # Reenable STRONG BET only after: 30+ picks at WR >60% per sport
    SPORT_THRESHOLDS = {
        "NHL": {
            "strong_bet_edge": 999,  # DISABLED: NHL 50% WR at STRONG BET — not enough edge
            "strong_bet_conf": 999,  # Cap NHL at BET max until sample >= 30 with >60% WR
            "bet_edge": 25,          # Stricter — 25% edge required for BET
            "bet_conf": 75,
            "lean_edge": 15,
            "lean_conf": 65,
        },
        "NBA": {
            "strong_bet_edge": 999,  # DISABLED: NBA STRONG BET 44% WR (4W/5L) < BET 67% WR
            "strong_bet_conf": 999,  # Reenable after 30+ picks at >60% WR
            "bet_edge": 15,
            "bet_conf": 65,
            "lean_edge": 8,
            "lean_conf": 55,
        },
        # MLB: Opening Day 2026 = Mar 28. STRICT thresholds for early season.
        # Issue: Early-season expert panels are small → consensus inflates edge artificially.
        # Every game showing 30-40% edge on Day 1 = model miscalibration, NOT real edge.
        # Action: Raise thresholds dramatically until 30+ resolved picks accumulate (~late April).
        # STRONG BET disabled until WR data established.
        "MLB": {
            "strong_bet_edge": 999,  # DISABLED: No MLB WR data yet — early season inflation risk
            "strong_bet_conf": 999,  # Reenable after 30+ picks with WR >65%
            "bet_edge": 35,          # Strict: require 35% edge to cut through early-season noise
            "bet_conf": 82,          # High confidence bar too
            "lean_edge": 25,
            "lean_conf": 75,
        },
        # Default (other sports — STRONG BET disabled until WR data available)
        "DEFAULT": {
            "strong_bet_edge": 999,  # DISABLED: No WR data for unknown sports
            "strong_bet_conf": 999,
            "bet_edge": 15,
            "bet_conf": 65,
            "lean_edge": 8,
            "lean_conf": 55,
        },
    }

    def get_recommendation(
        self,
        confidence: float,
        edge: float,
        value_rating: int,
        sport: str = "DEFAULT",
    ) -> tuple[str, list[str]]:
        """
        Get recommendation based on all factors.
        
        Sport-specific thresholds applied based on live historical WR:
        - NBA: 75% WR → standard thresholds
        - NHL: 46% WR → stricter thresholds (+5% edge at each tier)
        
        Returns (recommendation, reasons)
        """
        reasons = []
        
        # Get sport-specific thresholds
        thresholds = self.SPORT_THRESHOLDS.get(sport.upper(), self.SPORT_THRESHOLDS["DEFAULT"])
        
        # Must have positive edge (70% WR historically)
        if edge <= 0:
            reasons.append(f"Negative edge ({edge:.1f}%)")
            return "PASS", reasons
        else:
            reasons.append(f"+EV edge: {edge:.1f}%")
        
        # Confidence assessment
        if confidence >= 75:
            reasons.append(f"High confidence: {confidence:.0f}%")
        elif confidence >= 55:
            reasons.append(f"Moderate confidence: {confidence:.0f}%")
        else:
            reasons.append(f"Low confidence: {confidence:.0f}%")
            return "PASS", reasons
        
        # Value rating check (3-4 stars best historically)
        if value_rating in [3, 4]:
            reasons.append(f"Optimal value ({value_rating}★)")
        elif value_rating == 5:
            reasons.append(f"High value ({value_rating}★)")
        else:
            reasons.append(f"Low value ({value_rating}★)")
        
        # Sport-calibrated recommendation
        if edge >= thresholds["strong_bet_edge"] and confidence >= thresholds["strong_bet_conf"]:
            return "STRONG BET", reasons
        elif edge >= thresholds["bet_edge"] and confidence >= thresholds["bet_conf"]:
            return "BET", reasons
        elif edge >= thresholds["lean_edge"] and confidence >= thresholds["lean_conf"]:
            return "LEAN", reasons
        elif edge > 0:
            return "LEAN", reasons
        
        return "PASS", reasons
    
    def score_pick(
        self,
        game_id: int,
        sport: str,
        matchup: str,
        pick_team: str,
        pick_type: str,
        odds_american: int,
        cpu_confidence: float = 0,
        expert_pct: float = 50,
        fan_pct: float = 50,
    ) -> ScoredPick:
        """
        Score a single pick with all calculations.
        """
        # Calculate probabilities
        implied_prob = self.american_to_implied_prob(odds_american)
        true_prob = self.calculate_true_prob(cpu_confidence, expert_pct, fan_pct)
        edge = self.calculate_edge(true_prob, implied_prob)
        
        # Calculate scores
        expert_vs_fan = abs(expert_pct - fan_pct)
        confidence = self.calculate_confidence_score(
            edge, cpu_confidence, expert_pct, expert_vs_fan
        )
        value_rating = self.calculate_value_rating(edge, confidence)
        
        # Get recommendation (with sport-specific thresholds)
        recommendation, reasons = self.get_recommendation(
            confidence, edge, value_rating, sport
        )
        
        return ScoredPick(
            game_id=game_id,
            sport=sport,
            matchup=matchup,
            pick_team=pick_team,
            pick_type=pick_type,
            odds_american=odds_american,
            cpu_confidence=cpu_confidence,
            expert_pct=expert_pct,
            fan_pct=fan_pct,
            implied_prob=round(implied_prob, 3),
            true_prob=round(true_prob, 3),
            edge=round(edge, 2),
            confidence_score=confidence,
            value_rating=value_rating,
            recommendation=recommendation,
            reasons=reasons,
        )


# Demo
if __name__ == "__main__":
    scorer = ConfidenceScorer()
    
    # Example pick
    pick = scorer.score_pick(
        game_id=12345,
        sport="MLB",
        matchup="LAD @ SD",
        pick_team="LAD",
        pick_type="ML",
        odds_american=-150,
        cpu_confidence=0.72,
        expert_pct=68,
        fan_pct=55,
    )
    
    print(f"Game: {pick.matchup}")
    print(f"Pick: {pick.pick_team} ({pick.pick_type})")
    print(f"Odds: {pick.odds_american}")
    print(f"True Prob: {pick.true_prob:.1%}")
    print(f"Implied Prob: {pick.implied_prob:.1%}")
    print(f"Edge: {pick.edge:+.1f}%")
    print(f"Confidence: {pick.confidence_score:.0f}%")
    print(f"Value: {pick.stars}")
    print(f"Recommendation: {pick.recommendation}")
    print(f"Reasons: {', '.join(pick.reasons)}")
