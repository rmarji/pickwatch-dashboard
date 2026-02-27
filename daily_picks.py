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


def get_active_sports() -> list[str]:
    """Return sports in season based on current month."""
    month = datetime.now().month
    
    # Approximate seasons (US leagues)
    if month in [9, 10, 11, 12, 1]:  # Sep-Jan: NFL, NHL, NBA
        return ["nba", "nhl"]
    elif month in [2, 3]:  # Feb-Mar: NHL, NBA
        return ["nba", "nhl"]
    elif month in [4, 5, 6]:  # Apr-Jun: NHL playoffs, NBA playoffs, MLB
        return ["nba", "nhl", "mlb"]
    elif month in [7, 8]:  # Jul-Aug: MLB only
        return ["mlb"]
    return ["nba"]


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
    
    for sport in sports:
        try:
            games = api.get_games_with_cpu(sport, year, today)
            if games:
                picks = score_games(games, scorer)
                report = format_telegram(picks, sport)
                all_reports.append(report)
        except Exception as e:
            all_reports.append(f"⚠️ {sport.upper()}: Error fetching ({e})")
    
    if all_reports:
        print("\n\n".join(all_reports))
    else:
        print("No games today across all sports")


if __name__ == "__main__":
    main()
