#!/usr/bin/env python3
"""
Pickwatch Picks CLI

Usage: python picks.py [sport] [date]
  sport: nba, nfl, mlb, nhl (default: nba)
  date: YYYY-MM-DD (default: today)
"""

import os
import sys
import json
from datetime import date

# Load env
env_file = '/data/workspace-cto/config/pickwatch.env'
if os.path.exists(env_file):
    with open(env_file) as f:
        for line in f:
            if '=' in line and not line.startswith('#'):
                key, val = line.strip().split('=', 1)
                os.environ[key] = val

from api_client import PickwatchAPI
from scoring import ConfidenceScorer


def get_picks(sport: str = "nba", game_date: str = None):
    """Get scored picks for a sport/date."""
    if game_date is None:
        game_date = date.today().isoformat()
    
    api = PickwatchAPI()
    scorer = ConfidenceScorer()
    
    games = api.get_games_with_cpu(sport, "2024", game_date)
    
    picks = []
    for game in games:
        if game.is_final:
            continue
        
        # Score both sides
        home_pick = scorer.score_pick(
            game_id=game.id,
            sport=sport.upper(),
            matchup=game.matchup,
            pick_team=game.home_team,
            pick_type="ML",
            odds_american=game.home_odds,
            cpu_confidence=game.cpu_home_confidence,
            expert_pct=game.expert_home_pct,
            fan_pct=game.fan_home_pct,
        )
        
        away_pick = scorer.score_pick(
            game_id=game.id,
            sport=sport.upper(),
            matchup=game.matchup,
            pick_team=game.away_team,
            pick_type="ML",
            odds_american=game.away_odds,
            cpu_confidence=game.cpu_away_confidence,
            expert_pct=game.expert_away_pct,
            fan_pct=game.fan_away_pct,
        )
        
        best = home_pick if home_pick.confidence_score >= away_pick.confidence_score else away_pick
        
        picks.append({
            "matchup": game.matchup,
            "pick": best.pick_team,
            "odds": best.odds_american,
            "confidence": best.confidence_score,
            "edge": best.edge,
            "value_rating": best.value_rating,
            "stars": best.stars,
            "recommendation": best.recommendation,
            "reasons": best.reasons,
            "expert_pct": max(game.expert_home_pct, game.expert_away_pct),
            "fan_pct": max(game.fan_home_pct, game.fan_away_pct),
        })
    
    # Sort by confidence
    picks.sort(key=lambda x: x["confidence"], reverse=True)
    return picks


def format_telegram(sport: str, game_date: str, picks: list) -> str:
    """Format picks for Telegram."""
    icons = {
        "STRONG BET": "🔥",
        "BET": "✅",
        "LEAN": "👀",
        "PASS": "❌",
    }
    
    # Summary
    strong = sum(1 for p in picks if p["recommendation"] == "STRONG BET")
    bets = sum(1 for p in picks if p["recommendation"] == "BET")
    leans = sum(1 for p in picks if p["recommendation"] == "LEAN")
    
    lines = [
        f"🎰 **{sport.upper()} PICKS** — {game_date}",
        f"━━━━━━━━━━━━━━━━━━━",
        f"🔥 Strong: {strong}  ✅ Bet: {bets}  👀 Lean: {leans}",
        "",
    ]
    
    for p in picks:
        if p["recommendation"] == "PASS":
            continue
        
        icon = icons.get(p["recommendation"], "")
        odds_str = f"{p['odds']:+d}" if p['odds'] else "N/A"
        
        lines.append(f"{icon} **{p['matchup']}**")
        lines.append(f"   {p['pick']} ({odds_str})")
        lines.append(f"   Edge: {p['edge']:+.1f}% | Conf: {p['confidence']:.0f}%")
        lines.append(f"   Expert: {p['expert_pct']:.0f}% | Fan: {p['fan_pct']:.0f}%")
        lines.append(f"   {p['stars']} {p['recommendation']}")
        lines.append("")
    
    if not any(p["recommendation"] != "PASS" for p in picks):
        lines.append("No actionable picks today.")
    
    return "\n".join(lines)


def main():
    sport = sys.argv[1] if len(sys.argv) > 1 else "nba"
    game_date = sys.argv[2] if len(sys.argv) > 2 else date.today().isoformat()
    
    output_format = "telegram"
    if "--json" in sys.argv:
        output_format = "json"
    
    picks = get_picks(sport, game_date)
    
    if output_format == "json":
        print(json.dumps({"sport": sport, "date": game_date, "picks": picks}, indent=2))
    else:
        print(format_telegram(sport, game_date, picks))


if __name__ == "__main__":
    main()
