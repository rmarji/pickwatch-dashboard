"""
Pickwatch Betting Tracker

Bankroll management, bet sizing, and P&L tracking.
Uses Kelly criterion for optimal bet sizing with configurable risk levels.
"""

import json
from datetime import datetime, date, timedelta
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, List, Dict
from decimal import Decimal
import sqlite3

from history import PickHistory, TrackedPick, calculate_performance, PerformanceStats


TRACKER_DB = Path(__file__).parent / "betting_tracker.db"


@dataclass
class BankrollState:
    """Current bankroll status."""
    initial_balance: float = 1000.0
    current_balance: float = 1000.0
    total_deposited: float = 1000.0
    total_withdrawn: float = 0.0
    
    # Performance
    peak_balance: float = 1000.0
    valley_balance: float = 1000.0
    current_drawdown_pct: float = 0.0
    max_drawdown_pct: float = 0.0
    
    # Streaks
    current_streak: int = 0  # +ve = wins, -ve = losses
    longest_win_streak: int = 0
    longest_loss_streak: int = 0
    
    # Today
    today_bets: int = 0
    today_wagered: float = 0.0
    today_profit: float = 0.0
    
    @property
    def total_profit(self) -> float:
        return self.current_balance - self.total_deposited + self.total_withdrawn
    
    @property
    def roi(self) -> float:
        if self.total_deposited == 0:
            return 0
        return (self.total_profit / self.total_deposited) * 100


@dataclass
class BetSizing:
    """Recommended bet size based on edge and bankroll."""
    kelly_fraction: float = 0.0  # Full Kelly
    recommended_bet: float = 0.0  # Fractional Kelly (safer)
    max_bet: float = 0.0  # Max allowed
    min_bet: float = 0.0  # Min viable
    confidence: str = ""  # HIGH, MEDIUM, LOW
    
    def to_dict(self) -> dict:
        return {
            "kelly_fraction": round(self.kelly_fraction, 4),
            "recommended_bet": round(self.recommended_bet, 2),
            "max_bet": round(self.max_bet, 2),
            "min_bet": round(self.min_bet, 2),
            "confidence": self.confidence,
        }


class BettingTracker:
    """
    Bankroll and bet management system.
    
    Features:
    - Kelly criterion bet sizing with fractional safety
    - Bankroll tracking with deposit/withdraw
    - Drawdown monitoring
    - Win/loss streak tracking
    - Daily limits enforcement
    """
    
    # Risk profiles (fraction of Kelly)
    RISK_PROFILES = {
        "conservative": 0.25,  # Quarter Kelly
        "moderate": 0.50,      # Half Kelly (recommended)
        "aggressive": 0.75,    # Three-quarter Kelly
        "full": 1.0,           # Full Kelly (dangerous)
    }
    
    # Default limits
    MAX_BET_PCT = 0.05  # Max 5% of bankroll per bet
    MIN_BET = 10.0      # Minimum viable bet
    MAX_DAILY_BETS = 10  # Daily bet limit
    MAX_DAILY_RISK_PCT = 0.20  # Max 20% daily risk
    
    def __init__(
        self,
        db_path: Path = TRACKER_DB,
        history: PickHistory = None,
        risk_profile: str = "moderate",
    ):
        self.db_path = db_path
        self.history = history or PickHistory()
        self.risk_factor = self.RISK_PROFILES.get(risk_profile, 0.5)
        self._init_db()
    
    def _init_db(self):
        """Initialize tracker database."""
        with sqlite3.connect(self.db_path) as conn:
            # Bankroll transactions
            conn.execute("""
                CREATE TABLE IF NOT EXISTS transactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    type TEXT NOT NULL,  -- DEPOSIT, WITHDRAW, BET, WIN, LOSS, PUSH
                    amount REAL NOT NULL,
                    balance_after REAL NOT NULL,
                    pick_id INTEGER,
                    note TEXT,
                    FOREIGN KEY (pick_id) REFERENCES picks(id)
                )
            """)
            
            # Bankroll state (single row)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS bankroll (
                    id INTEGER PRIMARY KEY CHECK (id = 1),
                    initial_balance REAL NOT NULL,
                    current_balance REAL NOT NULL,
                    total_deposited REAL NOT NULL,
                    total_withdrawn REAL NOT NULL,
                    peak_balance REAL NOT NULL,
                    valley_balance REAL NOT NULL,
                    max_drawdown_pct REAL NOT NULL,
                    longest_win_streak INTEGER NOT NULL,
                    longest_loss_streak INTEGER NOT NULL,
                    current_streak INTEGER NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            
            # Initialize if empty
            row = conn.execute("SELECT COUNT(*) FROM bankroll").fetchone()
            if row[0] == 0:
                now = datetime.utcnow().isoformat()
                conn.execute("""
                    INSERT INTO bankroll (
                        id, initial_balance, current_balance, total_deposited,
                        total_withdrawn, peak_balance, valley_balance,
                        max_drawdown_pct, longest_win_streak, longest_loss_streak,
                        current_streak, updated_at
                    ) VALUES (1, 1000, 1000, 1000, 0, 1000, 1000, 0, 0, 0, 0, ?)
                """, (now,))
    
    def get_state(self) -> BankrollState:
        """Get current bankroll state."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM bankroll WHERE id = 1").fetchone()
            
            state = BankrollState(
                initial_balance=row["initial_balance"],
                current_balance=row["current_balance"],
                total_deposited=row["total_deposited"],
                total_withdrawn=row["total_withdrawn"],
                peak_balance=row["peak_balance"],
                valley_balance=row["valley_balance"],
                max_drawdown_pct=row["max_drawdown_pct"],
                longest_win_streak=row["longest_win_streak"],
                longest_loss_streak=row["longest_loss_streak"],
                current_streak=row["current_streak"],
            )
            
            # Calculate current drawdown
            if state.peak_balance > 0:
                state.current_drawdown_pct = (
                    (state.peak_balance - state.current_balance) / state.peak_balance
                ) * 100
            
            # Get today's stats
            today = date.today().isoformat()
            today_stats = conn.execute("""
                SELECT 
                    COUNT(*) as count,
                    COALESCE(SUM(CASE WHEN type = 'BET' THEN amount ELSE 0 END), 0) as wagered,
                    COALESCE(SUM(CASE WHEN type IN ('WIN', 'LOSS', 'PUSH') THEN amount ELSE 0 END), 0) as profit
                FROM transactions
                WHERE date(timestamp) = ?
            """, (today,)).fetchone()
            
            state.today_bets = today_stats["count"] // 2 if today_stats["count"] > 0 else 0
            state.today_wagered = abs(today_stats["wagered"])
            state.today_profit = today_stats["profit"]
            
            return state
    
    def _update_state(self, conn: sqlite3.Connection, balance: float, streak_delta: int = 0):
        """Update bankroll state after transaction."""
        now = datetime.utcnow().isoformat()
        
        row = conn.execute("SELECT * FROM bankroll WHERE id = 1").fetchone()
        new_peak = max(row[5], balance)  # peak_balance
        new_valley = min(row[6], balance)  # valley_balance
        
        current_streak = row[10] + streak_delta
        if streak_delta > 0:  # Win
            if current_streak < 0:
                current_streak = 1
            longest_win = max(row[8], current_streak)
            longest_loss = row[9]
        elif streak_delta < 0:  # Loss
            if current_streak > 0:
                current_streak = -1
            longest_win = row[8]
            longest_loss = max(row[9], abs(current_streak))
        else:  # Push or deposit/withdraw
            longest_win = row[8]
            longest_loss = row[9]
        
        max_dd = max(
            row[7],
            ((new_peak - balance) / new_peak * 100) if new_peak > 0 else 0
        )
        
        conn.execute("""
            UPDATE bankroll SET
                current_balance = ?,
                peak_balance = ?,
                valley_balance = ?,
                max_drawdown_pct = ?,
                longest_win_streak = ?,
                longest_loss_streak = ?,
                current_streak = ?,
                updated_at = ?
            WHERE id = 1
        """, (balance, new_peak, new_valley, max_dd, longest_win, longest_loss, current_streak, now))
    
    def deposit(self, amount: float, note: str = "") -> float:
        """Add funds to bankroll."""
        if amount <= 0:
            raise ValueError("Deposit must be positive")
        
        with sqlite3.connect(self.db_path) as conn:
            row = conn.execute("SELECT current_balance, total_deposited FROM bankroll WHERE id = 1").fetchone()
            new_balance = row[0] + amount
            
            conn.execute("""
                INSERT INTO transactions (timestamp, type, amount, balance_after, note)
                VALUES (?, 'DEPOSIT', ?, ?, ?)
            """, (datetime.utcnow().isoformat(), amount, new_balance, note))
            
            conn.execute("""
                UPDATE bankroll SET current_balance = ?, total_deposited = ? WHERE id = 1
            """, (new_balance, row[1] + amount))
            
            self._update_state(conn, new_balance)
            return new_balance
    
    def withdraw(self, amount: float, note: str = "") -> float:
        """Withdraw funds from bankroll."""
        state = self.get_state()
        if amount > state.current_balance:
            raise ValueError(f"Insufficient balance: ${state.current_balance:.2f}")
        
        with sqlite3.connect(self.db_path) as conn:
            new_balance = state.current_balance - amount
            
            conn.execute("""
                INSERT INTO transactions (timestamp, type, amount, balance_after, note)
                VALUES (?, 'WITHDRAW', ?, ?, ?)
            """, (datetime.utcnow().isoformat(), -amount, new_balance, note))
            
            conn.execute("""
                UPDATE bankroll SET current_balance = ?, total_withdrawn = ? WHERE id = 1
            """, (new_balance, state.total_withdrawn + amount))
            
            self._update_state(conn, new_balance)
            return new_balance
    
    def calculate_kelly(self, odds_american: int, win_probability: float) -> float:
        """
        Calculate Kelly criterion bet fraction.
        
        Kelly = (bp - q) / b
        where:
            b = decimal odds - 1 (net profit per unit wagered)
            p = probability of winning
            q = probability of losing (1 - p)
        """
        if win_probability <= 0 or win_probability >= 1:
            return 0
        
        # Convert American to decimal odds
        if odds_american > 0:
            decimal_odds = (odds_american / 100) + 1
        else:
            decimal_odds = (100 / abs(odds_american)) + 1
        
        b = decimal_odds - 1  # Net profit per unit
        p = win_probability
        q = 1 - p
        
        kelly = (b * p - q) / b
        return max(0, kelly)  # Can't bet negative
    
    def get_bet_sizing(self, pick: TrackedPick) -> BetSizing:
        """
        Calculate recommended bet size for a pick.
        
        Uses:
        - Kelly criterion for edge-based sizing
        - Fractional Kelly for safety
        - Bankroll limits
        """
        state = self.get_state()
        sizing = BetSizing(min_bet=self.MIN_BET)
        
        # Max bet based on bankroll %
        sizing.max_bet = state.current_balance * self.MAX_BET_PCT
        
        # Calculate implied probability from edge
        # Edge = (True Prob - Implied Prob) / Implied Prob * 100
        # Reverse: True Prob = Implied Prob * (1 + Edge/100)
        if pick.odds_american > 0:
            implied_prob = 100 / (pick.odds_american + 100)
        else:
            implied_prob = abs(pick.odds_american) / (abs(pick.odds_american) + 100)
        
        true_prob = implied_prob * (1 + pick.edge / 100)
        true_prob = min(0.95, max(0.05, true_prob))  # Clamp
        
        # Kelly fraction
        sizing.kelly_fraction = self.calculate_kelly(pick.odds_american, true_prob)
        
        # Apply risk factor (fractional Kelly)
        fractional_kelly = sizing.kelly_fraction * self.risk_factor
        kelly_bet = state.current_balance * fractional_kelly
        
        # Apply limits
        sizing.recommended_bet = min(kelly_bet, sizing.max_bet)
        sizing.recommended_bet = max(sizing.min_bet, sizing.recommended_bet)
        
        # Confidence rating
        if sizing.kelly_fraction >= 0.10:
            sizing.confidence = "HIGH"
        elif sizing.kelly_fraction >= 0.05:
            sizing.confidence = "MEDIUM"
        else:
            sizing.confidence = "LOW"
        
        # Check daily limits
        if state.today_bets >= self.MAX_DAILY_BETS:
            sizing.recommended_bet = 0
            sizing.confidence = "LIMIT_REACHED"
        elif state.today_wagered + sizing.recommended_bet > state.current_balance * self.MAX_DAILY_RISK_PCT:
            sizing.recommended_bet = (state.current_balance * self.MAX_DAILY_RISK_PCT) - state.today_wagered
            if sizing.recommended_bet < sizing.min_bet:
                sizing.recommended_bet = 0
                sizing.confidence = "DAILY_LIMIT"
        
        return sizing
    
    def place_bet(self, pick_id: int, amount: float) -> float:
        """
        Record a bet placement.
        Returns new balance.
        """
        state = self.get_state()
        if amount > state.current_balance:
            raise ValueError(f"Insufficient balance: ${state.current_balance:.2f}")
        if amount < self.MIN_BET:
            raise ValueError(f"Minimum bet is ${self.MIN_BET:.2f}")
        
        # Record in history
        self.history.record_bet(pick_id, amount)
        
        with sqlite3.connect(self.db_path) as conn:
            new_balance = state.current_balance - amount
            
            conn.execute("""
                INSERT INTO transactions (timestamp, type, amount, balance_after, pick_id, note)
                VALUES (?, 'BET', ?, ?, ?, ?)
            """, (datetime.utcnow().isoformat(), -amount, new_balance, pick_id, f"Bet placed: ${amount:.2f}"))
            
            self._update_state(conn, new_balance)
            return new_balance
    
    def record_result(self, pick_id: int, outcome: str, payout: float = 0) -> float:
        """
        Record bet result.
        Returns new balance.
        """
        if outcome not in ("WIN", "LOSS", "PUSH"):
            raise ValueError(f"Invalid outcome: {outcome}")
        
        # Get pick to determine bet amount
        pick = self.history.get_pick(pick_id)
        if not pick or not pick.bet_placed:
            raise ValueError(f"No bet found for pick {pick_id}")
        
        # Update history
        self.history.record_outcome(pick_id, outcome, payout)
        
        state = self.get_state()
        
        with sqlite3.connect(self.db_path) as conn:
            if outcome == "WIN":
                profit = payout - pick.bet_amount
                new_balance = state.current_balance + payout
                streak_delta = 1
                note = f"Win: +${profit:.2f}"
            elif outcome == "LOSS":
                new_balance = state.current_balance  # Already deducted
                streak_delta = -1
                note = f"Loss: -${pick.bet_amount:.2f}"
            else:  # PUSH
                new_balance = state.current_balance + pick.bet_amount
                streak_delta = 0
                payout = pick.bet_amount
                note = f"Push: +${pick.bet_amount:.2f} (refund)"
            
            conn.execute("""
                INSERT INTO transactions (timestamp, type, amount, balance_after, pick_id, note)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (datetime.utcnow().isoformat(), outcome, payout if outcome != "LOSS" else 0, new_balance, pick_id, note))
            
            self._update_state(conn, new_balance, streak_delta)
            return new_balance
    
    def get_transactions(
        self,
        start_date: date = None,
        end_date: date = None,
        tx_type: str = None,
        limit: int = 50,
    ) -> List[Dict]:
        """Get transaction history."""
        query = "SELECT * FROM transactions WHERE 1=1"
        params = []
        
        if start_date:
            query += " AND date(timestamp) >= ?"
            params.append(start_date.isoformat())
        if end_date:
            query += " AND date(timestamp) <= ?"
            params.append(end_date.isoformat())
        if tx_type:
            query += " AND type = ?"
            params.append(tx_type)
        
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(query, params).fetchall()
            return [dict(row) for row in rows]


def format_bankroll_telegram(state: BankrollState) -> str:
    """Format bankroll state for Telegram."""
    # Sparkline for profit
    if state.total_profit >= 0:
        profit_bar = "▓" * min(10, int(state.roi / 5)) + "░" * max(0, 10 - int(state.roi / 5))
    else:
        profit_bar = "░" * 10
    
    streak_icon = "🔥" if state.current_streak > 0 else "❄️" if state.current_streak < 0 else "➖"
    streak_val = abs(state.current_streak)
    
    lines = [
        "💰 **Bankroll Status**",
        "━━━━━━━━━━━━━━━━━━━",
        f"Balance: **${state.current_balance:,.2f}**",
        f"Profit:  ${state.total_profit:+,.2f} ({state.roi:+.1f}%)",
        f"[{profit_bar}]",
        "",
        f"📈 Peak: ${state.peak_balance:,.2f}",
        f"📉 Drawdown: {state.current_drawdown_pct:.1f}% (max: {state.max_drawdown_pct:.1f}%)",
        f"{streak_icon} Streak: {streak_val} {'W' if state.current_streak > 0 else 'L' if state.current_streak < 0 else ''}",
        "",
        f"📅 Today: {state.today_bets} bets, ${state.today_profit:+.2f}",
    ]
    
    return "\n".join(lines)


def format_bet_sizing_telegram(pick: TrackedPick, sizing: BetSizing) -> str:
    """Format bet sizing recommendation for Telegram."""
    confidence_icon = {"HIGH": "🔥", "MEDIUM": "✅", "LOW": "👀", "LIMIT_REACHED": "🚫", "DAILY_LIMIT": "⚠️"}
    icon = confidence_icon.get(sizing.confidence, "❓")
    
    lines = [
        f"{icon} **{pick.pick_team}** ({pick.matchup})",
        "━━━━━━━━━━━━━━━━━━━",
        f"Edge: {pick.edge:+.1f}% | Odds: {pick.odds_american:+d}",
        f"Kelly: {sizing.kelly_fraction*100:.1f}%",
        f"Recommended: **${sizing.recommended_bet:.2f}**",
        f"Max allowed: ${sizing.max_bet:.2f}",
    ]
    
    if sizing.confidence in ("LIMIT_REACHED", "DAILY_LIMIT"):
        lines.append(f"\n⚠️ {sizing.confidence.replace('_', ' ')}")
    
    return "\n".join(lines)


# CLI
if __name__ == "__main__":
    import sys
    
    tracker = BettingTracker(risk_profile="moderate")
    
    if len(sys.argv) < 2:
        # Show status
        state = tracker.get_state()
        print(format_bankroll_telegram(state))
        sys.exit(0)
    
    cmd = sys.argv[1]
    
    if cmd == "deposit":
        amount = float(sys.argv[2]) if len(sys.argv) > 2 else 100
        new_bal = tracker.deposit(amount)
        print(f"✅ Deposited ${amount:.2f}")
        print(f"New balance: ${new_bal:.2f}")
    
    elif cmd == "withdraw":
        amount = float(sys.argv[2]) if len(sys.argv) > 2 else 100
        new_bal = tracker.withdraw(amount)
        print(f"✅ Withdrew ${amount:.2f}")
        print(f"New balance: ${new_bal:.2f}")
    
    elif cmd == "history":
        txns = tracker.get_transactions(limit=20)
        print("📋 Recent Transactions")
        print("━" * 50)
        for tx in txns:
            ts = tx["timestamp"][:16].replace("T", " ")
            amt = tx["amount"]
            bal = tx["balance_after"]
            print(f"{ts} | {tx['type']:8} | ${amt:+8.2f} | ${bal:,.2f}")
    
    elif cmd == "sizing":
        # Demo bet sizing
        from scoring import ConfidenceScorer
        scorer = ConfidenceScorer()
        
        pick = scorer.score_pick(
            game_id=1001,
            sport="NBA",
            matchup="LAL @ BOS",
            pick_team="LAL",
            pick_type="ML",
            odds_american=+150,
            cpu_confidence=0.65,
            expert_pct=70,
            fan_pct=45,
        )
        
        # Create tracked pick
        tracked = TrackedPick(
            id=1,
            sport=pick.sport,
            matchup=pick.matchup,
            pick_team=pick.pick_team,
            odds_american=pick.odds_american,
            edge=pick.edge,
            confidence_score=pick.confidence_score,
        )
        
        sizing = tracker.get_bet_sizing(tracked)
        print(format_bet_sizing_telegram(tracked, sizing))
    
    else:
        print(f"Unknown command: {cmd}")
        print("Usage: betting_tracker.py [status|deposit|withdraw|history|sizing]")
