"""
Pickwatch Dashboard - Web interface for pick analysis.

Run: python app.py
Open: http://localhost:5050
"""

import os
import json
from datetime import date, datetime, timedelta
from flask import Flask, render_template, request, jsonify

# Load env
from dotenv import load_dotenv
load_dotenv("/data/workspace-cto/config/pickwatch.env")

from api_client import PickwatchAPI, GameData
from scoring import ConfidenceScorer, ScoredPick

app = Flask(__name__)
scorer = ConfidenceScorer()


def get_picks_for_date(sport: str, game_date: str) -> list[dict]:
    """Fetch and score all picks for a date."""
    api = PickwatchAPI()
    
    try:
        games = api.get_games_with_cpu(sport, "2024", game_date)
    finally:
        api.close()
    
    picks = []
    for game in games:
        if game.is_final:
            continue  # Skip finished games
        
        # Score home team pick
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
        
        # Score away team pick
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
        
        # Take the better pick
        best = home_pick if home_pick.confidence_score >= away_pick.confidence_score else away_pick
        
        picks.append({
            "game_id": game.id,
            "matchup": game.matchup,
            "kickoff": game.kickoff.strftime("%I:%M %p") if game.kickoff else "TBD",
            "pick": best.pick_team,
            "odds": f"{best.odds_american:+d}" if best.odds_american else "N/A",
            "confidence": best.confidence_score,
            "edge": best.edge,
            "value_rating": best.value_rating,
            "stars": best.stars,
            "recommendation": best.recommendation,
            "reasons": best.reasons,
            "cpu_confidence": f"{max(game.cpu_home_confidence, game.cpu_away_confidence):.0%}",
            "expert_pct": f"{max(game.expert_home_pct, game.expert_away_pct):.0f}%",
            "fan_pct": f"{max(game.fan_home_pct, game.fan_away_pct):.0f}%",
            "expert_vs_fan": abs(game.expert_home_pct - game.fan_home_pct),
        })
    
    # Sort by confidence
    picks.sort(key=lambda x: x["confidence"], reverse=True)
    return picks


@app.route("/")
def index():
    """Main dashboard page."""
    return render_template("index.html")


@app.route("/api/picks")
def api_picks():
    """API endpoint for picks."""
    sport = request.args.get("sport", "nba").lower()
    game_date = request.args.get("date", date.today().isoformat())
    
    try:
        picks = get_picks_for_date(sport, game_date)
        
        # Summary stats
        strong_bets = [p for p in picks if p["recommendation"] == "STRONG BET"]
        bets = [p for p in picks if p["recommendation"] == "BET"]
        leans = [p for p in picks if p["recommendation"] == "LEAN"]
        
        return jsonify({
            "success": True,
            "sport": sport.upper(),
            "date": game_date,
            "total_games": len(picks),
            "summary": {
                "strong_bets": len(strong_bets),
                "bets": len(bets),
                "leans": len(leans),
                "passes": len(picks) - len(strong_bets) - len(bets) - len(leans),
            },
            "picks": picks,
        })
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e),
        }), 500


@app.route("/api/health")
def health():
    """Health check."""
    return jsonify({"status": "ok", "timestamp": datetime.now().isoformat()})


# HTML Template
HTML_TEMPLATE = '''
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Pickwatch Dashboard</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #0d1117;
            color: #c9d1d9;
            line-height: 1.5;
        }
        
        .container {
            max-width: 1200px;
            margin: 0 auto;
            padding: 20px;
        }
        
        header {
            text-align: center;
            padding: 30px 0;
            border-bottom: 1px solid #21262d;
            margin-bottom: 30px;
        }
        
        h1 {
            font-size: 2.5em;
            color: #58a6ff;
            margin-bottom: 10px;
        }
        
        .subtitle {
            color: #8b949e;
            font-size: 1.1em;
        }
        
        .controls {
            display: flex;
            gap: 20px;
            justify-content: center;
            margin-bottom: 30px;
            flex-wrap: wrap;
        }
        
        .control-group {
            display: flex;
            align-items: center;
            gap: 10px;
        }
        
        label {
            font-weight: 600;
            color: #8b949e;
        }
        
        select, input[type="date"] {
            padding: 10px 15px;
            border: 1px solid #30363d;
            border-radius: 6px;
            background: #161b22;
            color: #c9d1d9;
            font-size: 1em;
            cursor: pointer;
        }
        
        select:hover, input[type="date"]:hover {
            border-color: #58a6ff;
        }
        
        .summary {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 15px;
            margin-bottom: 30px;
        }
        
        .summary-card {
            background: #161b22;
            border: 1px solid #30363d;
            border-radius: 8px;
            padding: 20px;
            text-align: center;
        }
        
        .summary-card.strong { border-color: #238636; background: rgba(35, 134, 54, 0.1); }
        .summary-card.bet { border-color: #58a6ff; background: rgba(88, 166, 255, 0.1); }
        .summary-card.lean { border-color: #d29922; background: rgba(210, 153, 34, 0.1); }
        .summary-card.pass { border-color: #484f58; }
        
        .summary-value {
            font-size: 2.5em;
            font-weight: bold;
        }
        
        .summary-label {
            color: #8b949e;
            font-size: 0.9em;
            margin-top: 5px;
        }
        
        .picks-grid {
            display: grid;
            gap: 15px;
        }
        
        .pick-card {
            background: #161b22;
            border: 1px solid #30363d;
            border-radius: 8px;
            padding: 20px;
            display: grid;
            grid-template-columns: 1fr auto;
            gap: 15px;
            align-items: center;
        }
        
        .pick-card.strong-bet { border-left: 4px solid #238636; }
        .pick-card.bet { border-left: 4px solid #58a6ff; }
        .pick-card.lean { border-left: 4px solid #d29922; }
        .pick-card.pass { border-left: 4px solid #484f58; opacity: 0.7; }
        
        .pick-main {
            display: flex;
            flex-direction: column;
            gap: 8px;
        }
        
        .pick-matchup {
            font-size: 1.2em;
            font-weight: 600;
            color: #f0f6fc;
        }
        
        .pick-team {
            display: inline-flex;
            align-items: center;
            gap: 8px;
            font-size: 1.1em;
        }
        
        .pick-team-name {
            font-weight: bold;
            color: #58a6ff;
        }
        
        .pick-odds {
            color: #7ee787;
            font-family: monospace;
        }
        
        .pick-meta {
            display: flex;
            gap: 20px;
            flex-wrap: wrap;
            font-size: 0.9em;
            color: #8b949e;
        }
        
        .pick-meta span {
            display: flex;
            align-items: center;
            gap: 5px;
        }
        
        .pick-reasons {
            font-size: 0.85em;
            color: #8b949e;
            margin-top: 5px;
        }
        
        .pick-stats {
            text-align: right;
            min-width: 150px;
        }
        
        .confidence-score {
            font-size: 2em;
            font-weight: bold;
        }
        
        .confidence-score.high { color: #238636; }
        .confidence-score.medium { color: #d29922; }
        .confidence-score.low { color: #da3633; }
        
        .edge-value {
            font-size: 1.1em;
            font-family: monospace;
        }
        
        .edge-value.positive { color: #7ee787; }
        .edge-value.negative { color: #f85149; }
        
        .stars {
            font-size: 1.2em;
            letter-spacing: 2px;
        }
        
        .recommendation {
            display: inline-block;
            padding: 4px 12px;
            border-radius: 20px;
            font-size: 0.8em;
            font-weight: 600;
            text-transform: uppercase;
            margin-top: 5px;
        }
        
        .recommendation.strong-bet { background: #238636; color: #fff; }
        .recommendation.bet { background: #58a6ff; color: #fff; }
        .recommendation.lean { background: #d29922; color: #000; }
        .recommendation.pass { background: #484f58; color: #8b949e; }
        
        .loading {
            text-align: center;
            padding: 50px;
            color: #8b949e;
        }
        
        .spinner {
            display: inline-block;
            width: 40px;
            height: 40px;
            border: 3px solid #30363d;
            border-top-color: #58a6ff;
            border-radius: 50%;
            animation: spin 1s linear infinite;
        }
        
        @keyframes spin {
            to { transform: rotate(360deg); }
        }
        
        .error {
            background: rgba(248, 81, 73, 0.1);
            border: 1px solid #f85149;
            color: #f85149;
            padding: 20px;
            border-radius: 8px;
            text-align: center;
        }
        
        .no-picks {
            text-align: center;
            padding: 50px;
            color: #8b949e;
        }
        
        @media (max-width: 768px) {
            .pick-card {
                grid-template-columns: 1fr;
            }
            .pick-stats {
                text-align: left;
                display: flex;
                gap: 20px;
                align-items: center;
            }
        }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>🎰 Pickwatch Dashboard</h1>
            <p class="subtitle">AI-Powered Sports Betting Analysis</p>
        </header>
        
        <div class="controls">
            <div class="control-group">
                <label for="sport">Sport:</label>
                <select id="sport">
                    <option value="nba">NBA</option>
                    <option value="nfl">NFL</option>
                    <option value="mlb">MLB</option>
                    <option value="nhl">NHL</option>
                </select>
            </div>
            <div class="control-group">
                <label for="date">Date:</label>
                <input type="date" id="date" value="">
            </div>
        </div>
        
        <div id="summary" class="summary"></div>
        <div id="picks" class="picks-grid"></div>
    </div>
    
    <script>
        const sportSelect = document.getElementById('sport');
        const dateInput = document.getElementById('date');
        const summaryDiv = document.getElementById('summary');
        const picksDiv = document.getElementById('picks');
        
        // Set default date to today
        dateInput.value = new Date().toISOString().split('T')[0];
        
        async function loadPicks() {
            const sport = sportSelect.value;
            const date = dateInput.value;
            
            summaryDiv.innerHTML = '';
            picksDiv.innerHTML = '<div class="loading"><div class="spinner"></div><p>Loading picks...</p></div>';
            
            try {
                const resp = await fetch(`/api/picks?sport=${sport}&date=${date}`);
                const data = await resp.json();
                
                if (!data.success) {
                    picksDiv.innerHTML = `<div class="error">Error: ${data.error}</div>`;
                    return;
                }
                
                renderSummary(data.summary);
                renderPicks(data.picks);
            } catch (err) {
                picksDiv.innerHTML = `<div class="error">Failed to load picks: ${err.message}</div>`;
            }
        }
        
        function renderSummary(summary) {
            summaryDiv.innerHTML = `
                <div class="summary-card strong">
                    <div class="summary-value">${summary.strong_bets}</div>
                    <div class="summary-label">Strong Bets</div>
                </div>
                <div class="summary-card bet">
                    <div class="summary-value">${summary.bets}</div>
                    <div class="summary-label">Bets</div>
                </div>
                <div class="summary-card lean">
                    <div class="summary-value">${summary.leans}</div>
                    <div class="summary-label">Leans</div>
                </div>
                <div class="summary-card pass">
                    <div class="summary-value">${summary.passes}</div>
                    <div class="summary-label">Passes</div>
                </div>
            `;
        }
        
        function renderPicks(picks) {
            if (picks.length === 0) {
                picksDiv.innerHTML = '<div class="no-picks">No games found for this date</div>';
                return;
            }
            
            picksDiv.innerHTML = picks.map(pick => {
                const recClass = pick.recommendation.toLowerCase().replace(' ', '-');
                const confClass = pick.confidence >= 75 ? 'high' : pick.confidence >= 60 ? 'medium' : 'low';
                const edgeClass = pick.edge > 0 ? 'positive' : 'negative';
                
                return `
                    <div class="pick-card ${recClass}">
                        <div class="pick-main">
                            <div class="pick-matchup">${pick.matchup}</div>
                            <div class="pick-team">
                                <span class="pick-team-name">${pick.pick}</span>
                                <span class="pick-odds">${pick.odds}</span>
                            </div>
                            <div class="pick-meta">
                                <span>🤖 CPU: ${pick.cpu_confidence}</span>
                                <span>👔 Expert: ${pick.expert_pct}</span>
                                <span>👥 Fan: ${pick.fan_pct}</span>
                                <span>⏰ ${pick.kickoff}</span>
                            </div>
                            <div class="pick-reasons">${pick.reasons.join(' • ')}</div>
                        </div>
                        <div class="pick-stats">
                            <div class="confidence-score ${confClass}">${pick.confidence.toFixed(0)}%</div>
                            <div class="edge-value ${edgeClass}">Edge: ${pick.edge > 0 ? '+' : ''}${pick.edge.toFixed(1)}%</div>
                            <div class="stars">${pick.stars}</div>
                            <div class="recommendation ${recClass}">${pick.recommendation}</div>
                        </div>
                    </div>
                `;
            }).join('');
        }
        
        // Event listeners
        sportSelect.addEventListener('change', loadPicks);
        dateInput.addEventListener('change', loadPicks);
        
        // Initial load
        loadPicks();
    </script>
</body>
</html>
'''

# Create templates folder and save template
import os
os.makedirs("templates", exist_ok=True)
with open("templates/index.html", "w") as f:
    f.write(HTML_TEMPLATE)


if __name__ == "__main__":
    print("Starting Pickwatch Dashboard...")
    print("Open http://localhost:5050")
    app.run(host="0.0.0.0", port=5050, debug=True)
