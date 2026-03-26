"""
Pickwatch Historical Tracking

SQLite storage for picks, outcomes, and P&L analysis.
Tracks betting performance over time to refine strategies.
"""

import sqlite3
import json
from datetime import datetime, date
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Optional, List
from decimal import Decimal

from scoring import ScoredPick


DB_PATH = Path(__file__).parent / "pickwatch_history.db"


@dataclass
class TrackedPick:
    """A pick with outcome tracking."""
    id: Optional[int] = None
    date: str = ""
    sport: str = ""
    game_id: int = 0
    matchup: str = ""
    pick_team: str = ""
    pick_type: str = ""
    odds_american: int = 0
    
    # Scoring data
    edge: float = 0
    confidence_score: float = 0
    value_rating: int = 0
    recommendation: str = ""
    
    # Bet tracking
    bet_amount: float = 0  # 0 = tracked but not bet
    bet_placed: bool = False
    
    # Outcome (filled in after game)
    outcome: Optional[str] = None  # "WIN", "LOSS", "PUSH", None=pending
    payout: float = 0
    
    # Metadata
    created_at: str = ""
    updated_at: str = ""
    
    @property
    def profit(self) -> float:
        if not self.bet_placed or self.outcome is None:
            return 0
        if self.outcome == "WIN":
            return self.payout - self.bet_amount
        elif self.outcome == "LOSS":
            return -self.bet_amount
        return 0  # PUSH
    
    @property
    def roi(self) -> float:
        if self.bet_amount <= 0:
            return 0
        return (self.profit / self.bet_amount) * 100


class PickHistory:
    """SQLite-backed pick history tracker."""
    
    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self._init_db()
    
    def _init_db(self):
        """Initialize database schema."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS picks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT NOT NULL,
                    sport TEXT NOT NULL,
                    game_id INTEGER NOT NULL,
                    matchup TEXT NOT NULL,
                    pick_team TEXT NOT NULL,
                    pick_type TEXT NOT NULL,
                    odds_american INTEGER NOT NULL,
                    
                    edge REAL NOT NULL,
                    confidence_score REAL NOT NULL,
                    value_rating INTEGER NOT NULL,
                    recommendation TEXT NOT NULL,
                    
                    bet_amount REAL DEFAULT 0,
                    bet_placed INTEGER DEFAULT 0,
                    
                    outcome TEXT,
                    payout REAL DEFAULT 0,
                    
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    
                    UNIQUE(date, sport, game_id, pick_team, pick_type)
                )
            """)
            
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_picks_date ON picks(date)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_picks_sport ON picks(sport)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_picks_outcome ON picks(outcome)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_picks_recommendation ON picks(recommendation)
            """)
    
    def add_pick(self, pick: ScoredPick, pick_date: date = None) -> TrackedPick:
        """Add a scored pick to history."""
        now = datetime.utcnow().isoformat()
        pick_date = pick_date or date.today()
        
        tracked = TrackedPick(
            date=pick_date.isoformat(),
            sport=pick.sport,
            game_id=pick.game_id,
            matchup=pick.matchup,
            pick_team=pick.pick_team,
            pick_type=pick.pick_type,
            odds_american=pick.odds_american,
            edge=pick.edge,
            confidence_score=pick.confidence_score,
            value_rating=pick.value_rating,
            recommendation=pick.recommendation,
            created_at=now,
            updated_at=now,
        )
        
        with sqlite3.connect(self.db_path) as conn:
            # Dedup guard: skip if same game_id+pick_team already exists (any date)
            existing = conn.execute(
                "SELECT id FROM picks WHERE game_id = ? AND pick_team = ? AND pick_type = ?",
                (tracked.game_id, tracked.pick_team, tracked.pick_type)
            ).fetchone()
            if existing:
                tracked.id = existing[0]
                return tracked  # Already tracked — skip duplicate
            
            cursor = conn.execute("""
                INSERT OR REPLACE INTO picks (
                    date, sport, game_id, matchup, pick_team, pick_type,
                    odds_american, edge, confidence_score, value_rating,
                    recommendation, bet_amount, bet_placed, outcome, payout,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                tracked.date, tracked.sport, tracked.game_id, tracked.matchup,
                tracked.pick_team, tracked.pick_type, tracked.odds_american,
                tracked.edge, tracked.confidence_score, tracked.value_rating,
                tracked.recommendation, tracked.bet_amount, int(tracked.bet_placed),
                tracked.outcome, tracked.payout, tracked.created_at, tracked.updated_at
            ))
            tracked.id = cursor.lastrowid
        
        return tracked
    
    def record_bet(self, pick_id: int, amount: float) -> bool:
        """Record that a bet was placed."""
        now = datetime.utcnow().isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                UPDATE picks SET bet_amount = ?, bet_placed = 1, updated_at = ?
                WHERE id = ?
            """, (amount, now, pick_id))
        return True
    
    def record_outcome(self, pick_id: int, outcome: str, payout: float = 0) -> bool:
        """Record the outcome of a pick."""
        if outcome not in ("WIN", "LOSS", "PUSH"):
            raise ValueError(f"Invalid outcome: {outcome}")
        
        now = datetime.utcnow().isoformat()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                UPDATE picks SET outcome = ?, payout = ?, updated_at = ?
                WHERE id = ?
            """, (outcome, payout, now, pick_id))
        return True
    
    def get_pick(self, pick_id: int) -> Optional[TrackedPick]:
        """Get a single pick by ID."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM picks WHERE id = ?", (pick_id,)).fetchone()
            if row:
                return self._row_to_pick(row)
        return None
    
    def get_picks(
        self,
        sport: str = None,
        start_date: date = None,
        end_date: date = None,
        recommendation: str = None,
        outcome: str = None,
        bet_only: bool = False,
        limit: int = 100,
    ) -> List[TrackedPick]:
        """Query picks with filters."""
        query = "SELECT * FROM picks WHERE 1=1"
        params = []
        
        if sport:
            query += " AND sport = ?"
            params.append(sport)
        if start_date:
            query += " AND date >= ?"
            params.append(start_date.isoformat())
        if end_date:
            query += " AND date <= ?"
            params.append(end_date.isoformat())
        if recommendation:
            query += " AND recommendation = ?"
            params.append(recommendation)
        if outcome:
            query += " AND outcome = ?"
            params.append(outcome)
        if bet_only:
            query += " AND bet_placed = 1"
        
        query += " ORDER BY date DESC, id DESC LIMIT ?"
        params.append(limit)
        
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(query, params).fetchall()
            return [self._row_to_pick(row) for row in rows]
    
    def get_pending_outcomes(self) -> List[TrackedPick]:
        """Get picks that need outcome updates."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("""
                SELECT * FROM picks 
                WHERE outcome IS NULL AND date < date('now')
                ORDER BY date ASC
            """).fetchall()
            return [self._row_to_pick(row) for row in rows]
    
    def _row_to_pick(self, row: sqlite3.Row) -> TrackedPick:
        return TrackedPick(
            id=row["id"],
            date=row["date"],
            sport=row["sport"],
            game_id=row["game_id"],
            matchup=row["matchup"],
            pick_team=row["pick_team"],
            pick_type=row["pick_type"],
            odds_american=row["odds_american"],
            edge=row["edge"],
            confidence_score=row["confidence_score"],
            value_rating=row["value_rating"],
            recommendation=row["recommendation"],
            bet_amount=row["bet_amount"],
            bet_placed=bool(row["bet_placed"]),
            outcome=row["outcome"],
            payout=row["payout"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


@dataclass
class PerformanceStats:
    """Aggregated performance statistics."""
    total_picks: int = 0
    total_bets: int = 0
    wins: int = 0
    losses: int = 0
    pushes: int = 0
    pending: int = 0
    
    total_wagered: float = 0
    total_payout: float = 0
    net_profit: float = 0
    roi: float = 0
    win_rate: float = 0
    
    # By recommendation
    strong_bet_record: str = ""
    bet_record: str = ""
    lean_record: str = ""
    
    avg_edge: float = 0
    avg_confidence: float = 0


def calculate_performance(
    history: PickHistory,
    sport: str = None,
    start_date: date = None,
    end_date: date = None,
    bet_only: bool = True,
) -> PerformanceStats:
    """Calculate performance statistics."""
    picks = history.get_picks(
        sport=sport,
        start_date=start_date,
        end_date=end_date,
        bet_only=bet_only,
        limit=10000,
    )
    
    stats = PerformanceStats()
    stats.total_picks = len(picks)
    
    # Counters by recommendation
    rec_records = {"STRONG BET": [0, 0], "BET": [0, 0], "LEAN": [0, 0]}
    
    edges = []
    confidences = []
    
    for pick in picks:
        if pick.bet_placed:
            stats.total_bets += 1
            stats.total_wagered += pick.bet_amount
            stats.total_payout += pick.payout
        
        if pick.outcome == "WIN":
            stats.wins += 1
            if pick.recommendation in rec_records:
                rec_records[pick.recommendation][0] += 1
        elif pick.outcome == "LOSS":
            stats.losses += 1
            if pick.recommendation in rec_records:
                rec_records[pick.recommendation][1] += 1
        elif pick.outcome == "PUSH":
            stats.pushes += 1
        else:
            stats.pending += 1
        
        edges.append(pick.edge)
        confidences.append(pick.confidence_score)
    
    # Calculate aggregates
    decided = stats.wins + stats.losses
    if decided > 0:
        stats.win_rate = (stats.wins / decided) * 100
    
    stats.net_profit = stats.total_payout - stats.total_wagered
    if stats.total_wagered > 0:
        stats.roi = (stats.net_profit / stats.total_wagered) * 100
    
    if edges:
        stats.avg_edge = sum(edges) / len(edges)
        stats.avg_confidence = sum(confidences) / len(confidences)
    
    # Format records
    w, l = rec_records["STRONG BET"]
    stats.strong_bet_record = f"{w}-{l}" if (w + l) > 0 else "—"
    w, l = rec_records["BET"]
    stats.bet_record = f"{w}-{l}" if (w + l) > 0 else "—"
    w, l = rec_records["LEAN"]
    stats.lean_record = f"{w}-{l}" if (w + l) > 0 else "—"
    
    return stats


def format_stats_telegram(stats: PerformanceStats, title: str = "Performance") -> str:
    """Format stats for Telegram (no markdown tables)."""
    lines = [
        f"📊 **{title}**",
        f"━━━━━━━━━━━━━━━━━━━",
    ]
    
    if stats.total_bets > 0:
        lines.extend([
            f"Record: **{stats.wins}W-{stats.losses}L** ({stats.win_rate:.1f}%)",
            f"ROI: **{stats.roi:+.1f}%** (${stats.net_profit:+.2f})",
            f"Wagered: ${stats.total_wagered:.2f}",
            "",
            "By Recommendation:",
            f"  🔥 Strong Bet: {stats.strong_bet_record}",
            f"  ✅ Bet: {stats.bet_record}",
            f"  👀 Lean: {stats.lean_record}",
        ])
    else:
        lines.extend([
            f"Tracked: {stats.total_picks} picks",
            f"Pending: {stats.pending}",
            f"Avg Edge: {stats.avg_edge:+.1f}%",
            f"Avg Conf: {stats.avg_confidence:.0f}%",
        ])
    
    return "\n".join(lines)


# Demo / CLI
if __name__ == "__main__":
    from scoring import ConfidenceScorer
    
    # Create test data
    history = PickHistory()
    scorer = ConfidenceScorer()
    
    # Add sample picks
    pick1 = scorer.score_pick(
        game_id=1001,
        sport="NBA",
        matchup="LAL @ BOS",
        pick_team="LAL",
        pick_type="ML",
        odds_american=+150,
        cpu_confidence=0.58,
        expert_pct=62,
        fan_pct=48,
    )
    
    tracked = history.add_pick(pick1)
    print(f"Added pick: {tracked.matchup} → {tracked.pick_team}")
    print(f"  Edge: {tracked.edge:+.1f}%")
    print(f"  Confidence: {tracked.confidence_score:.0f}%")
    print(f"  Recommendation: {tracked.recommendation}")
    
    # Simulate bet + outcome
    history.record_bet(tracked.id, 100)
    history.record_outcome(tracked.id, "WIN", 250)
    
    # Get stats
    stats = calculate_performance(history)
    print("\n" + format_stats_telegram(stats))
