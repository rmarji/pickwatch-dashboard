#!/usr/bin/env python3
"""
Result Checker — Resolves yesterday's picks and posts W/L report to Telegram.

Flow:
1. Fetch pending picks from DB (picks with outcome=NULL and date < today)
2. Call Pickwatch API to get final scores for those game dates/sports
3. Update outcomes (WIN / LOSS / PUSH)
4. Send Telegram notification with record + details

Usage:
    python3 result_checker.py           # Check and update pending picks
    python3 result_checker.py --dry-run # Show what would be resolved (no DB write)
    python3 result_checker.py --stats   # Show recent stats only
"""

import os
import sys
import json
import argparse
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional
from urllib.request import urlopen, Request
from urllib.error import HTTPError
import ssl
import re

# Adjust path for imports
sys.path.insert(0, str(Path(__file__).parent))

from api_client import PickwatchAPI, GameData
from history import PickHistory, TrackedPick
from history import calculate_performance, format_stats_telegram


# ─── ESPN Scores API ───────────────────────────────────────────────────────────

ESPN_URL = "https://site.api.espn.com/apis/site/v2/sports"

# Team name mappings (Pickwatch → ESPN)
TEAM_MAP = {
    # NHL
    "NYR": "New York Rangers", "NYI": "New York Islanders", "NJ": "New Jersey Devils",
    "BOS": "Boston Bruins", "BUF": "Buffalo Sabres", "MTL": "Montreal Canadiens", "MON": "Montreal Canadiens",
    "TOR": "Toronto Maple Leafs", "OTT": "Ottawa Senators", "DET": "Detroit Red Wings",
    "FLA": "Florida Panthers", "TB": "Tampa Bay Lightning", "CAR": "Carolina Hurricanes",
    "WSH": "Washington Capitals", "PIT": "Pittsburgh Penguins", "PHI": "Philadelphia Flyers",
    "CHI": "Chicago Blackhawks", "DET": "Detroit Red Wings", "NSH": "Nashville Predators", "NAS": "Nashville Predators",
    "WPG": "Winnipeg Jets", "MIN": "Minnesota Wild", "COL": "Colorado Avalanche", "DAL": "Dallas Stars",
    "STL": "St. Louis Blues", "CGY": "Calgary Flames", "EDM": "Edmonton Oilers", "VAN": "Vancouver Canucks",
    "SEA": "Seattle Kraken", "VGK": "Vegas Golden Knights", "VEG": "Vegas Golden Knights",
    "ANA": "Anaheim Ducks", "LAK": "Los Angeles Kings", "LA": "Los Angeles Kings", "SJS": "San Jose Sharks", "SJ": "San Jose Sharks",
    "ARI": "Arizona Coyotes", "UTA": "Utah Hockey Club",
    # NBA
    "ATL": "Atlanta Hawks", "BOS": "Boston Celtics", "BKN": "Brooklyn Nets", "NJN": "Brooklyn Nets",
    "CHA": "Charlotte Hornets", "CHI": "Chicago Bulls", "CLE": "Cleveland Cavaliers",
    "DAL": "Dallas Mavericks", "DEN": "Denver Nuggets", "DET": "Detroit Pistons", "GS": "Golden State Warriors",
    "GSW": "Golden State Warriors", "HOU": "Houston Rockets", "IND": "Indiana Pacers",
    "LAC": "LA Clippers", "LAL": "Los Angeles Lakers", "MEM": "Memphis Grizzlies",
    "MIA": "Miami Heat", "MIL": "Milwaukee Bucks", "MIN": "Minnesota Timberwolves",
    "NOP": "New Orleans Pelicans", "NO": "New Orleans Pelicans", "NY": "New York Knicks", "NYK": "New York Knicks",
    "OKC": "Oklahoma City Thunder", "ORL": "Orlando Magic", "PHI": "Philadelphia 76ers",
    "PHX": "Phoenix Suns", "POR": "Portland Trail Blazers", "SAC": "Sacramento Kings",
    "SAS": "San Antonio Spurs", "TOR": "Toronto Raptors", "UTAH": "Utah Jazz", "UTA": "Utah Jazz",
    "WAS": "Washington Wizards", "WSH": "Washington Wizards",
    # MLB
    "NYY": "New York Yankees", "BOS": "Boston Red Sox", "TB": "Tampa Bay Rays",
    "BAL": "Baltimore Orioles", "TOR": "Toronto Blue Jays",
    "CWS": "Chicago White Sox", "CLE": "Cleveland Guardians", "DET": "Detroit Tigers",
    "KC": "Kansas City Royals", "MIN": "Minnesota Twins",
    "HOU": "Houston Astros", "LAA": "Los Angeles Angels", "OAK": "Oakland Athletics",
    "SEA": "Seattle Mariners", "TEX": "Texas Rangers",
    "ATL": "Atlanta Braves", "MIA": "Miami Marlins", "NYM": "New York Mets",
    "PHI": "Philadelphia Phillies", "WSN": "Washington Nationals",
    "CHC": "Chicago Cubs", "CIN": "Cincinnati Reds", "MIL": "Milwaukee Brewers",
    "PIT": "Pittsburgh Pirates", "STL": "St. Louis Cardinals",
    "ARI": "Arizona Diamondbacks", "COL": "Colorado Rockies", "LAD": "Los Angeles Dodgers",
    "SD": "San Diego Padres", "SF": "San Francisco Giants",
}


def get_espn_scores(sport: str, game_date: str) -> dict[str, tuple[str, str]]:
    """
    Fetch final scores from ESPN API.
    
    Args:
        sport: "nba" or "nhl"
        game_date: "YYYY-MM-DD"
    
    Returns:
        Dict mapping "away @ home" → (winner_team, "away_score-home_score")
    """
    sport_map = {
        "nba": "basketball/nba",
        "nhl": "hockey/nhl",
        "nfl": "football/nfl",
        "mlb": "baseball/mlb",
    }
    espn_sport = sport_map.get(sport.lower())
    if not espn_sport:
        return {}
    
    # Accept both string and date objects
    date_str = game_date.isoformat() if hasattr(game_date, 'isoformat') else str(game_date)
    url = f"{ESPN_URL}/{espn_sport}/scoreboard?dates={date_str.replace('-', '')}"
    
    try:
        ctx = ssl.create_default_context()
        req = Request(url, headers={"User-Agent": "Mozilla/5.0", "Accept": "application/json"})
        with urlopen(req, context=ctx, timeout=30) as resp:
            data = json.loads(resp.read().decode())
    except Exception as e:
        print(f"[espn] Error fetching {sport}/{game_date}: {e}", file=sys.stderr)
        return {}
    
    results = {}
    for event in data.get("events", []):
        status = event.get("status", {}).get("type", {}).get("name", "")
        if status != "STATUS_FINAL":
            continue
        
        competitions = event.get("competitions", [])
        if len(competitions) != 1:
            continue
        
        comp = competitions[0]
        competitors = comp.get("competitors", [])
        if len(competitors) != 2:
            continue
        
        # Find home and away
        home = away = None
        for c in competitors:
            if c.get("homeAway") == "home":
                home = c
            else:
                away = c
        
        if not home or not away:
            continue
        
        home_team = home.get("team", {}).get("displayName", "")
        away_team = away.get("team", {}).get("displayName", "")
        home_score = home.get("score", "0")
        away_score = away.get("score", "0")
        
        winner = home_team if int(home_score) > int(away_score) else away_team
        
        # Store with matchup key
        matchup = f"{away_team} @ {home_team}"
        results[matchup] = (winner, f"{away_score}-{home_score}")
        
        # Also store abbreviated version
        away_abbr = away.get("team", {}).get("abbreviation", "")
        home_abbr = home.get("team", {}).get("abbreviation", "")
        if away_abbr and home_abbr:
            abbr_key = f"{away_abbr} @ {home_abbr}"
            results[abbr_key] = (winner, f"{away_score}-{home_score}")
    
    return results


def resolve_matchup(pick_matchup: str, pick_team: str, espn_results: dict) -> Optional[tuple[str, str]]:
    """
    Resolve a pick matchup against ESPN results.
    Handles abbreviation mapping.
    
    Returns:
        (outcome, score_str) or None if not found
    """
    # Normalize the matchup
    # Format: "AWAY @ HOME"
    parts = pick_matchup.split(" @ ")
    if len(parts) != 2:
        return None
    
    away_abbr, home_abbr = parts[0].strip(), parts[1].strip()
    
    # Try exact abbreviation match first
    key1 = f"{away_abbr} @ {home_abbr}"
    if key1 in espn_results:
        winner, score = espn_results[key1]
        outcome = "WIN" if winner == TEAM_MAP.get(pick_team, pick_team) else "LOSS"
        return (outcome, score)
    
    # Try full name match
    away_full = TEAM_MAP.get(away_abbr, away_abbr)
    home_full = TEAM_MAP.get(home_abbr, home_abbr)
    key2 = f"{away_full} @ {home_full}"
    if key2 in espn_results:
        winner, score = espn_results[key2]
        outcome = "WIN" if winner == TEAM_MAP.get(pick_team, pick_team) else "LOSS"
        return (outcome, score)
    
    # Try reverse lookup: find any result where teams match
    pick_full = TEAM_MAP.get(pick_team, pick_team)
    for matchup, (winner, score) in espn_results.items():
        if pick_full in matchup:
            # Found the game
            outcome = "WIN" if winner == pick_full else "LOSS"
            return (outcome, score)
    
    return None


# ─── Telegram ────────────────────────────────────────────────────────────────

def _get_telegram_config() -> tuple[str, str]:
    """Return (bot_token, chat_id) from environment."""
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    return token, chat_id


def send_telegram(text: str) -> bool:
    """Send a message to Telegram. Returns True on success."""
    token, chat_id = _get_telegram_config()
    if not token or not chat_id:
        print("[telegram] No credentials — printing only", file=sys.stderr)
        print(text)
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = json.dumps({
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    }).encode()

    ctx = ssl.create_default_context()
    req = Request(url, data=payload, headers={"Content-Type": "application/json"})
    try:
        with urlopen(req, context=ctx, timeout=15) as resp:
            result = json.loads(resp.read())
            return result.get("ok", False)
    except Exception as e:
        print(f"[telegram] Send failed: {e}", file=sys.stderr)
        return False


# ─── Core logic ──────────────────────────────────────────────────────────────

def resolve_picks(
    history: PickHistory,
    api: PickwatchAPI,
    dry_run: bool = False,
) -> dict:
    """
    Resolve pending picks by fetching final scores.

    Returns:
        {
          "resolved": [(pick, outcome, game), ...],
          "unresolved": [pick, ...],  # Still no final score
          "errors": [(pick, error_msg), ...],
        }
    """
    pending = history.get_pending_outcomes()
    if not pending:
        return {"resolved": [], "unresolved": [], "errors": []}

    # Group by (date, sport) to minimise API calls
    groups: dict[tuple[str, str], list[TrackedPick]] = {}
    for pick in pending:
        key = (pick.date, pick.sport.lower())
        groups.setdefault(key, []).append(pick)

    resolved = []
    unresolved = []
    errors = []

    for (game_date, sport), picks in groups.items():
        try:
            # Primary: Pickwatch API
            games = api.get_games(sport, "2024", game_date)
            game_map: dict[int, GameData] = {g.id: g for g in games}

            still_pending = []
            for pick in picks:
                game = game_map.get(pick.game_id)
                if game is None or not game.is_final or game.winner is None:
                    still_pending.append(pick)
                    continue

                winner = game.winner
                if winner == "TIE":
                    outcome = "PUSH"
                elif winner == pick.pick_team:
                    outcome = "WIN"
                else:
                    outcome = "LOSS"

                payout = 0.0
                if outcome == "WIN" and pick.bet_placed and pick.bet_amount > 0:
                    odds = pick.odds_american
                    if odds > 0:
                        payout = pick.bet_amount + pick.bet_amount * (odds / 100)
                    else:
                        payout = pick.bet_amount + pick.bet_amount * (100 / abs(odds))

                if not dry_run:
                    history.record_outcome(pick.id, outcome, payout)
                resolved.append((pick, outcome, game))

            # Fallback: ESPN scores for picks Pickwatch couldn't resolve
            if still_pending:
                print(f"[result_checker] Pickwatch had no results for {len(still_pending)} picks, trying ESPN...", file=sys.stderr)
                espn_scores = get_espn_scores(sport, game_date)
                print(f"[espn] Got {len(espn_scores)} games for {sport}/{game_date}", file=sys.stderr)

                for pick in still_pending:
                    result = resolve_matchup(pick.matchup, pick.pick_team, espn_scores)
                    if result is None:
                        unresolved.append(pick)
                        print(f"[espn] No match for: {pick.matchup} (pick={pick.pick_team})", file=sys.stderr)
                        continue

                    outcome, score_str = result
                    payout = 0.0
                    if outcome == "WIN" and pick.bet_placed and pick.bet_amount > 0:
                        odds = pick.odds_american
                        if odds > 0:
                            payout = pick.bet_amount + pick.bet_amount * (odds / 100)
                        else:
                            payout = pick.bet_amount + pick.bet_amount * (100 / abs(odds))

                    if not dry_run:
                        history.record_outcome(pick.id, outcome, payout)

                    # Create a synthetic GameData for the report
                    parts = score_str.split("-")
                    away_score = int(parts[0]) if len(parts) == 2 else None
                    home_score = int(parts[1]) if len(parts) == 2 else None
                    game_parts = pick.matchup.split(" @ ")
                    away_team = game_parts[0] if len(game_parts) == 2 else ""
                    home_team = game_parts[1] if len(game_parts) == 2 else ""
                    synthetic_game = GameData(
                        id=pick.game_id,
                        sport=pick.sport,
                        date=pick.date,
                        home_team=home_team,
                        away_team=away_team,
                        kickoff=None,
                        game_state="Final",
                        home_score=home_score,
                        away_score=away_score,
                    )
                    resolved.append((pick, outcome, synthetic_game))
                    print(f"[espn] Resolved {pick.matchup}: {outcome} ({score_str})", file=sys.stderr)

        except Exception as e:
            for pick in picks:
                errors.append((pick, str(e)))

    return {"resolved": resolved, "unresolved": unresolved, "errors": errors}


def format_results_report(
    resolved: list,
    unresolved: list,
    errors: list,
    history: PickHistory,
    dry_run: bool = False,
) -> str:
    """Format the results for Telegram."""
    if not resolved and not unresolved:
        return "✅ *No pending picks to resolve.*"

    today = date.today()
    yesterday = (today - timedelta(days=1)).strftime("%b %d")

    lines = [
        f"📋 *PICKS RESULTS* — {yesterday}",
        "━━━━━━━━━━━━━━━━━━━━",
    ]
    if dry_run:
        lines[0] += " _(dry-run)_"

    # Wins
    wins = [(p, o, g) for p, o, g in resolved if o == "WIN"]
    losses = [(p, o, g) for p, o, g in resolved if o == "LOSS"]
    pushes = [(p, o, g) for p, o, g in resolved if o == "PUSH"]

    total = len(resolved)
    win_count = len(wins)
    loss_count = len(losses)

    # Headline record
    if total > 0:
        pct = (win_count / total * 100) if total else 0
        lines.append(f"*{win_count}W – {loss_count}L* ({pct:.0f}%)")
        lines.append("")

    # Detail lines
    for pick, outcome, game in sorted(resolved, key=lambda x: (x[0].sport, x[1])):
        icon = "✅" if outcome == "WIN" else ("❌" if outcome == "LOSS" else "↩️")
        score_str = ""
        if game.home_score is not None:
            score_str = f" ({game.away_score}–{game.home_score})"
        lines.append(
            f"{icon} *{pick.sport}* {pick.pick_team}{score_str}"
        )
        lines.append(f"   {game.matchup} | {pick.odds_american:+d} | {pick.recommendation}")

    # Unresolved notice
    if unresolved:
        lines.append("")
        sports = sorted({p.sport for p in unresolved})
        lines.append(f"⏳ {len(unresolved)} picks still pending ({', '.join(sports)})")

    # Errors
    if errors:
        lines.append("")
        lines.append(f"⚠️ {len(errors)} errors fetching results")

    # Recent stats (last 14 days)
    try:
        start = today - timedelta(days=14)
        stats = calculate_performance(history, start_date=start, end_date=today, bet_only=False)
        if stats.wins + stats.losses > 0:
            lines.append("")
            lines.append(
                f"📊 *14-day:* {stats.wins}W-{stats.losses}L "
                f"({stats.win_rate:.0f}%) | 🔥{stats.strong_bet_record}"
            )
    except Exception:
        pass

    return "\n".join(lines)


# ─── CLI ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Pickwatch result checker")
    parser.add_argument("--dry-run", action="store_true", help="Don't write to DB or send Telegram")
    parser.add_argument("--stats", action="store_true", help="Show stats only")
    parser.add_argument("--no-telegram", action="store_true", help="Print to stdout instead of Telegram")
    args = parser.parse_args()

    # Load token
    _load_env()

    history = PickHistory()
    api = PickwatchAPI()

    if args.stats:
        # Just show recent stats
        start = date.today() - timedelta(days=30)
        stats = calculate_performance(history, start_date=start, bet_only=False)
        print(format_stats_telegram(stats, "30-Day Performance"))
        return

    result = resolve_picks(history, api, dry_run=args.dry_run)

    resolved = result["resolved"]
    unresolved = result["unresolved"]
    errors = result["errors"]

    # Expire picks older than 2 days that still haven't resolved (bad game IDs)
    cutoff = date.today() - timedelta(days=2)
    still_unresolved = []
    for pick in unresolved:
        pick_date = date.fromisoformat(pick.date)
        if pick_date <= cutoff:
            print(f"[result_checker] Expiring stale pick {pick.id}: {pick.matchup} ({pick.date})", file=sys.stderr)
            if not args.dry_run:
                history.record_outcome(pick.id, "PUSH", 0.0)  # Mark as push (no data)
        else:
            still_unresolved.append(pick)
    unresolved = still_unresolved

    report = format_results_report(resolved, unresolved, errors, history, dry_run=args.dry_run)

    if args.dry_run or args.no_telegram:
        print(report)
    else:
        if resolved:
            # Only send if there's something to report
            sent = send_telegram(report)
            if not sent:
                print(report)  # Fallback to stdout
        else:
            # Nothing resolved — print quietly
            print(f"[result_checker] {len(unresolved)} pending, nothing resolved yet")

    # Summary to stdout for cron logs
    print(
        f"[result_checker] resolved={len(resolved)} "
        f"unresolved={len(unresolved)} errors={len(errors)}"
    )


def _load_env():
    """Load Pickwatch token from Infisical or env file."""
    import subprocess

    try:
        r = subprocess.run(
            ["/data/.openclaw/skills/infisical/get-secret.sh", "PICKWATCH_API_TOKEN"],
            capture_output=True, text=True, timeout=30,
        )
        if r.returncode == 0 and r.stdout.strip():
            tok = r.stdout.strip()
            if tok.startswith("Bearer "):
                tok = tok[7:]
            os.environ["PICKWATCH_TOKEN"] = tok
    except Exception:
        pass

    env_file = Path(__file__).parent.parent / "config" / "pickwatch.env"
    if env_file.exists():
        with open(env_file) as f:
            for line in f:
                if "=" in line and not line.startswith("#"):
                    k, v = line.strip().split("=", 1)
                    os.environ.setdefault(k, v)

    # Telegram
    tg_env = Path(__file__).parent.parent / "config" / "telegram.env"
    if tg_env.exists():
        with open(tg_env) as f:
            for line in f:
                if "=" in line and not line.startswith("#"):
                    k, v = line.strip().split("=", 1)
                    os.environ.setdefault(k, v)


if __name__ == "__main__":
    main()
