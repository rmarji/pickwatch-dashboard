#!/usr/bin/env python3
"""
Daily Picks Report - Generates Telegram-formatted picks notification.

Run daily to get scored picks for active sports.
"""

import os
import sys
from datetime import date, datetime

# Load token from config
CONFIG_PATH = "/data/workspace-cto/config/pickwatch.env"
if os.path.exists(CONFIG_PATH):
    with open(CONFIG_PATH) as f:
        for line in f:
            if line.startswith("PICKWATCH_TOKEN="):
                os.environ["PICKWATCH_TOKEN"] = line.split("=", 1)[1].strip()

from api_client import PickwatchAPI
from scoring import ConfidenceScorer, ScoredPick
from history import PickHistory


def get_active_sports() -> list[str]:
    """Return sports in season based on current date.
    
    Season ranges (US leagues):
    - NBA:  Oct 15 - Jun 30
    - NHL:  Oct 15 - Jun 30
    - NFL:  Sep 1  - Feb 28
    - MLB:  Mar 25 - Sep 30  (Opening Day 2026 is Mar 25; spring training before that = preseason)
    
    MLB is gated to Mar 25+ (Opening Day 2026). Spring training games before that are NOT real picks.
    """
    today = datetime.now().date()
    month = today.month
    day = today.day
    active = []

    # NBA: Oct 15 – Jun 30
    if (month == 10 and day >= 15) or month in [11, 12, 1, 2, 3, 4, 5] or (month == 6 and day <= 30):
        active.append("nba")

    # NHL: Oct 15 – Jun 30
    if (month == 10 and day >= 15) or month in [11, 12, 1, 2, 3, 4, 5] or (month == 6 and day <= 30):
        active.append("nhl")

    # NFL: Sep 1 – Feb 28
    if month in [9, 10, 11, 12, 1, 2]:
        active.append("nfl")

    # MLB: Mar 25 – Sep 30 (Opening Day 2026 = Mar 25; no spring training before that)
    if (month == 3 and day >= 25) or month in [4, 5, 6, 7, 8] or (month == 9 and day <= 30):
        active.append("mlb")

    return active if active else ["nba"]


def score_games(games, scorer) -> list[ScoredPick]:
    """Score all games and return sorted picks."""
    picks = []
    
    for game in games:
        # Skip finished games
        if game.is_final:
            continue
        
        # Score home team pick
        home_pick = scorer.score_pick(
            game_id=game.id,
            sport=game.sport,
            matchup=game.matchup,
            pick_team=game.home_team,
            pick_type="ML",
            odds_american=game.home_odds,
            cpu_confidence=game.cpu_home_confidence,
            expert_pct=game.expert_home_pct,
            fan_pct=game.fan_home_pct,
        )
        
        # Score away team pick
        away_pick = scorer.score_pick(
            game_id=game.id,
            sport=game.sport,
            matchup=game.matchup,
            pick_team=game.away_team,
            pick_type="ML",
            odds_american=game.away_odds,
            cpu_confidence=game.cpu_away_confidence,
            expert_pct=game.expert_away_pct,
            fan_pct=game.fan_away_pct,
        )
        
        # Take the better pick
        best = home_pick if home_pick.confidence_score >= away_pick.confidence_score else away_pick
        picks.append(best)
    
    # Sort by confidence score descending
    picks.sort(key=lambda p: p.confidence_score, reverse=True)
    return picks


def format_telegram(picks: list[ScoredPick], sport: str) -> str:
    """Format picks for Telegram."""
    if not picks:
        return f"No {sport.upper()} games today"
    
    lines = [f"🏀 **{sport.upper()} PICKS** ({date.today().strftime('%b %d')})"]
    lines.append("━" * 24)
    
    # Emojis for recommendations
    rec_emoji = {
        "STRONG BET": "🔥",
        "BET": "✅",
        "LEAN": "👀",
        "PASS": "⚪"
    }
    
    # Only show actionable picks (non-PASS)
    actionable = [p for p in picks if p.recommendation != "PASS"]
    
    if not actionable:
        lines.append("No high-confidence plays today")
    else:
        for pick in actionable[:6]:  # Top 6
            emoji = rec_emoji.get(pick.recommendation, "⚪")
            odds_str = f"+{pick.odds_american}" if pick.odds_american > 0 else str(pick.odds_american)
            lines.append(
                f"{emoji} **{pick.pick_team}** {odds_str}"
            )
            lines.append(
                f"   {pick.matchup} | {pick.confidence_score:.0f}% | {pick.stars}"
            )
            lines.append(f"   Edge: {pick.edge:+.1f}%")
            lines.append("")
    
    # Summary
    strong = len([p for p in picks if p.recommendation == "STRONG BET"])
    bets = len([p for p in picks if p.recommendation == "BET"])
    leans = len([p for p in picks if p.recommendation == "LEAN"])
    
    lines.append("━" * 24)
    lines.append(f"📊 {strong}🔥 {bets}✅ {leans}👀 from {len(picks)} games")
    
    return "\n".join(lines)


def main():
    """Generate daily picks report."""
    scorer = ConfidenceScorer()
    api = PickwatchAPI()
    today = date.today().isoformat()
    
    # Current sports year
    year = "2024" if datetime.now().month >= 9 else "2024"
    
    sports = get_active_sports()
    all_reports = []
    history = PickHistory()
    total_saved = 0
    
    for sport in sports:
        try:
            games = api.get_games_with_cpu(sport, year, today)
            if games:
                picks = score_games(games, scorer)
                
                # Save all actionable picks to history DB
                saved = 0
                for pick in picks:
                    if pick.recommendation not in ("PASS",):
                        try:
                            tracked = history.add_pick(pick)
                            if tracked.id:
                                saved += 1
                        except Exception:
                            pass
                total_saved += saved
                
                report = format_telegram(picks, sport)
                all_reports.append(report)
        except Exception as e:
            all_reports.append(f"⚠️ {sport.upper()}: Error fetching ({e})")
    
    if all_reports:
        print("\n\n".join(all_reports))
        if total_saved:
            print(f"\n📝 {total_saved} picks saved to history")
    else:
        print("No games today across all sports")


if __name__ == "__main__":
    main()
