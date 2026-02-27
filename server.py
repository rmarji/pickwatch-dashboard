#!/usr/bin/env python3
"""
Pickwatch Dashboard Server

Simple HTTP server with API endpoints for picks.
No external dependencies - uses stdlib only.
"""

import os
import json
from http.server import HTTPServer, BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs
from datetime import date, datetime

# Load env from file if exists, otherwise use env vars directly
env_file = '/data/workspace-cto/config/pickwatch.env'
if os.path.exists(env_file):
    with open(env_file) as f:
        for line in f:
            if '=' in line and not line.startswith('#'):
                key, val = line.strip().split('=', 1)
                if key not in os.environ:  # Don't override existing env vars
                    os.environ[key] = val

from api_client import PickwatchAPI
from scoring import ConfidenceScorer


class DashboardHandler(BaseHTTPRequestHandler):
    """HTTP request handler for the dashboard."""
    
    def log_message(self, format, *args):
        """Suppress logging."""
        pass
    
    def send_json(self, data, status=200):
        """Send JSON response."""
        body = json.dumps(data).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', len(body))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(body)
    
    def send_html(self, html):
        """Send HTML response."""
        body = html.encode()
        self.send_response(200)
        self.send_header('Content-Type', 'text/html')
        self.send_header('Content-Length', len(body))
        self.end_headers()
        self.wfile.write(body)
    
    def do_GET(self):
        """Handle GET requests."""
        parsed = urlparse(self.path)
        path = parsed.path
        params = parse_qs(parsed.query)
        
        if path == '/':
            self.send_html(DASHBOARD_HTML)
        elif path == '/api/picks':
            self.handle_picks(params)
        elif path == '/api/health':
            self.send_json({'status': 'ok', 'time': datetime.now().isoformat()})
        else:
            self.send_response(404)
            self.end_headers()
    
    def handle_picks(self, params):
        """Handle /api/picks endpoint."""
        sport = params.get('sport', ['nba'])[0].lower()
        game_date = params.get('date', [date.today().isoformat()])[0]
        
        try:
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
                    "expert_pct": f"{max(game.expert_home_pct, game.expert_away_pct):.0f}%",
                    "fan_pct": f"{max(game.fan_home_pct, game.fan_away_pct):.0f}%",
                    "expert_vs_fan": abs(game.expert_home_pct - game.fan_home_pct),
                })
            
            # Sort by confidence
            picks.sort(key=lambda x: x["confidence"], reverse=True)
            
            # Summary
            strong = len([p for p in picks if p["recommendation"] == "STRONG BET"])
            bets = len([p for p in picks if p["recommendation"] == "BET"])
            leans = len([p for p in picks if p["recommendation"] == "LEAN"])
            
            self.send_json({
                "success": True,
                "sport": sport.upper(),
                "date": game_date,
                "total_games": len(picks),
                "summary": {
                    "strong_bets": strong,
                    "bets": bets,
                    "leans": leans,
                    "passes": len(picks) - strong - bets - leans,
                },
                "picks": picks,
            })
        except Exception as e:
            self.send_json({"success": False, "error": str(e)}, 500)


DASHBOARD_HTML = '''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>🎰 Pickwatch Dashboard</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #0d1117 0%, #161b22 100%);
            color: #c9d1d9;
            min-height: 100vh;
            line-height: 1.6;
        }
        .container { max-width: 1000px; margin: 0 auto; padding: 20px; }
        
        header {
            text-align: center;
            padding: 40px 0 30px;
            border-bottom: 1px solid #30363d;
            margin-bottom: 30px;
        }
        h1 { font-size: 2.5em; color: #58a6ff; margin-bottom: 8px; }
        .subtitle { color: #8b949e; }
        
        .controls {
            display: flex; gap: 20px; justify-content: center;
            flex-wrap: wrap; margin-bottom: 30px;
        }
        .control-group { display: flex; align-items: center; gap: 10px; }
        label { font-weight: 600; color: #8b949e; }
        select, input[type="date"] {
            padding: 12px 16px; border: 1px solid #30363d;
            border-radius: 8px; background: #21262d; color: #c9d1d9;
            font-size: 1em; cursor: pointer;
        }
        select:hover, input:hover { border-color: #58a6ff; }
        
        .summary {
            display: grid;
            grid-template-columns: repeat(4, 1fr);
            gap: 15px; margin-bottom: 30px;
        }
        @media (max-width: 600px) { .summary { grid-template-columns: repeat(2, 1fr); } }
        
        .summary-card {
            background: #21262d; border: 1px solid #30363d;
            border-radius: 12px; padding: 20px; text-align: center;
        }
        .summary-card.strong { border-color: #238636; background: rgba(35, 134, 54, 0.15); }
        .summary-card.bet { border-color: #58a6ff; background: rgba(88, 166, 255, 0.15); }
        .summary-card.lean { border-color: #d29922; background: rgba(210, 153, 34, 0.15); }
        .summary-card.pass { border-color: #484f58; }
        
        .summary-value { font-size: 3em; font-weight: bold; }
        .summary-card.strong .summary-value { color: #3fb950; }
        .summary-card.bet .summary-value { color: #58a6ff; }
        .summary-card.lean .summary-value { color: #d29922; }
        .summary-label { color: #8b949e; margin-top: 5px; }
        
        .picks-grid { display: flex; flex-direction: column; gap: 15px; }
        
        .pick-card {
            background: #21262d; border: 1px solid #30363d;
            border-radius: 12px; padding: 20px;
            display: grid; grid-template-columns: 1fr auto;
            gap: 20px; align-items: center;
            transition: transform 0.2s, box-shadow 0.2s;
        }
        .pick-card:hover { transform: translateY(-2px); box-shadow: 0 4px 20px rgba(0,0,0,0.3); }
        
        .pick-card.strong-bet { border-left: 5px solid #238636; }
        .pick-card.bet { border-left: 5px solid #58a6ff; }
        .pick-card.lean { border-left: 5px solid #d29922; }
        .pick-card.pass { border-left: 5px solid #484f58; opacity: 0.6; }
        
        .pick-matchup { font-size: 1.3em; font-weight: 600; color: #f0f6fc; margin-bottom: 8px; }
        .pick-team { display: flex; align-items: center; gap: 10px; margin-bottom: 10px; }
        .pick-team-name { font-weight: bold; color: #58a6ff; font-size: 1.2em; }
        .pick-odds { color: #7ee787; font-family: monospace; font-size: 1.1em; }
        
        .pick-meta { display: flex; gap: 20px; flex-wrap: wrap; font-size: 0.9em; color: #8b949e; }
        .pick-meta span { display: flex; align-items: center; gap: 5px; }
        .pick-reasons { font-size: 0.85em; color: #8b949e; margin-top: 10px; }
        
        .pick-stats { text-align: right; min-width: 140px; }
        .confidence-score { font-size: 2.5em; font-weight: bold; }
        .confidence-score.high { color: #3fb950; }
        .confidence-score.medium { color: #d29922; }
        .confidence-score.low { color: #f85149; }
        
        .edge-value { font-size: 1.2em; font-family: monospace; margin: 5px 0; }
        .edge-value.positive { color: #7ee787; }
        .edge-value.negative { color: #f85149; }
        
        .stars { font-size: 1.3em; letter-spacing: 2px; margin: 5px 0; }
        
        .recommendation {
            display: inline-block; padding: 6px 14px;
            border-radius: 20px; font-size: 0.8em;
            font-weight: 700; text-transform: uppercase;
        }
        .recommendation.strong-bet { background: #238636; color: #fff; }
        .recommendation.bet { background: #58a6ff; color: #fff; }
        .recommendation.lean { background: #d29922; color: #000; }
        .recommendation.pass { background: #484f58; color: #8b949e; }
        
        .loading { text-align: center; padding: 60px; color: #8b949e; }
        .spinner {
            display: inline-block; width: 50px; height: 50px;
            border: 4px solid #30363d; border-top-color: #58a6ff;
            border-radius: 50%; animation: spin 1s linear infinite;
        }
        @keyframes spin { to { transform: rotate(360deg); } }
        
        .error { background: rgba(248, 81, 73, 0.1); border: 1px solid #f85149;
            color: #f85149; padding: 20px; border-radius: 8px; text-align: center; }
        .no-picks { text-align: center; padding: 60px; color: #8b949e; font-size: 1.2em; }
        
        @media (max-width: 768px) {
            .pick-card { grid-template-columns: 1fr; }
            .pick-stats { text-align: left; display: flex; gap: 15px; align-items: center; flex-wrap: wrap; }
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
                    <option value="nba">🏀 NBA</option>
                    <option value="nfl">🏈 NFL</option>
                    <option value="mlb">⚾ MLB</option>
                    <option value="nhl">🏒 NHL</option>
                </select>
            </div>
            <div class="control-group">
                <label for="date">Date:</label>
                <input type="date" id="date">
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
                picksDiv.innerHTML = `<div class="error">Failed to load: ${err.message}</div>`;
            }
        }
        
        function renderSummary(s) {
            summaryDiv.innerHTML = `
                <div class="summary-card strong"><div class="summary-value">${s.strong_bets}</div><div class="summary-label">🔥 Strong Bets</div></div>
                <div class="summary-card bet"><div class="summary-value">${s.bets}</div><div class="summary-label">✅ Bets</div></div>
                <div class="summary-card lean"><div class="summary-value">${s.leans}</div><div class="summary-label">👀 Leans</div></div>
                <div class="summary-card pass"><div class="summary-value">${s.passes}</div><div class="summary-label">❌ Passes</div></div>
            `;
        }
        
        function renderPicks(picks) {
            if (!picks.length) {
                picksDiv.innerHTML = '<div class="no-picks">No games found for this date</div>';
                return;
            }
            
            picksDiv.innerHTML = picks.map(p => {
                const rc = p.recommendation.toLowerCase().replace(' ', '-');
                const cc = p.confidence >= 75 ? 'high' : p.confidence >= 55 ? 'medium' : 'low';
                const ec = p.edge > 0 ? 'positive' : 'negative';
                
                return `
                    <div class="pick-card ${rc}">
                        <div>
                            <div class="pick-matchup">${p.matchup}</div>
                            <div class="pick-team">
                                <span class="pick-team-name">${p.pick}</span>
                                <span class="pick-odds">${p.odds}</span>
                            </div>
                            <div class="pick-meta">
                                <span>👔 Expert: ${p.expert_pct}</span>
                                <span>👥 Public: ${p.fan_pct}</span>
                                <span>⏰ ${p.kickoff}</span>
                            </div>
                            <div class="pick-reasons">${p.reasons.join(' • ')}</div>
                        </div>
                        <div class="pick-stats">
                            <div class="confidence-score ${cc}">${p.confidence.toFixed(0)}%</div>
                            <div class="edge-value ${ec}">Edge: ${p.edge > 0 ? '+' : ''}${p.edge.toFixed(1)}%</div>
                            <div class="stars">${p.stars}</div>
                            <div class="recommendation ${rc}">${p.recommendation}</div>
                        </div>
                    </div>
                `;
            }).join('');
        }
        
        sportSelect.addEventListener('change', loadPicks);
        dateInput.addEventListener('change', loadPicks);
        loadPicks();
    </script>
</body>
</html>
'''


def main():
    port = int(os.environ.get('PORT', 5050))
    server = HTTPServer(('0.0.0.0', port), DashboardHandler)
    print(f"🎰 Pickwatch Dashboard running on http://localhost:{port}")
    print("Press Ctrl+C to stop")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.shutdown()


if __name__ == "__main__":
    main()
