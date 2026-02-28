#!/usr/bin/env python3
"""
NEXUS — The War Room
A command center that actually feels like one.
"""

import json
import sqlite3
import subprocess
import sys
import urllib.request
import random
from datetime import datetime, timezone
from http.server import HTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse

CRYPTO_DB = Path("/data/workspace-cto/crypto-automation/crypto.db")
WORKSPACE = Path("/data/workspace-cto")


def get_crypto_positions():
    if not CRYPTO_DB.exists():
        return {"positions": [], "balance": 0, "error": "DB not found"}
    try:
        conn = sqlite3.connect(CRYPTO_DB)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT * FROM paper_account WHERE id = 1")
        account = cur.fetchone()
        balance = float(account["balance_usd"]) if account else 10000
        cur.execute("SELECT product_id, side, size, entry_price, entry_time FROM paper_positions")
        positions = []
        for row in cur.fetchall():
            pos = {
                "product": row["product_id"],
                "side": row["side"],
                "qty": float(row["size"]),
                "entry": float(row["entry_price"]),
                "time": row["entry_time"],
            }
            # Get live price
            try:
                symbol = pos["product"].replace("-USD", "")
                url = f"https://api.coinbase.com/v2/prices/{symbol}-USD/spot"
                req = urllib.request.Request(url, headers={"User-Agent": "Nexus/1.0"})
                with urllib.request.urlopen(req, timeout=5) as resp:
                    data = json.loads(resp.read())
                    current = float(data["data"]["amount"])
                    pos["current_price"] = current
                    if pos["side"] == "long":
                        pos["pnl_pct"] = ((current - pos["entry"]) / pos["entry"]) * 100
                    else:
                        pos["pnl_pct"] = ((pos["entry"] - current) / pos["entry"]) * 100
                    pos["pnl_usd"] = pos["pnl_pct"] / 100 * pos["entry"] * pos["qty"]
            except:
                pos["pnl_pct"] = 0
                pos["pnl_usd"] = 0
            positions.append(pos)
        
        cur.execute("""
            SELECT COALESCE(SUM(CAST(pnl AS REAL)), 0) as total_pnl,
                   COUNT(*) as trade_count,
                   SUM(CASE WHEN CAST(pnl AS REAL) > 0 THEN 1 ELSE 0 END) as wins
            FROM paper_trades WHERE pnl IS NOT NULL
        """)
        stats = cur.fetchone()
        conn.close()
        
        total_equity = balance + sum(p.get("pnl_usd", 0) for p in positions)
        
        return {
            "positions": positions,
            "balance": balance,
            "equity": total_equity,
            "realized_pnl": stats["total_pnl"] or 0,
            "trade_count": stats["trade_count"] or 0,
            "wins": stats["wins"] or 0,
            "error": None
        }
    except Exception as e:
        return {"positions": [], "balance": 0, "error": str(e)}


def get_sports_picks():
    try:
        sys.path.insert(0, str(WORKSPACE / "pickwatch-dashboard"))
        from api_client import PickwatchAPI
        from scoring import ConfidenceScorer
        from datetime import date
        
        api = PickwatchAPI()
        scorer = ConfidenceScorer()
        today = date.today().isoformat()
        
        picks = []
        for sport in ["nba", "nhl"]:
            try:
                games = api.get_games_with_cpu(sport, "2024", today)
                for game in games or []:
                    if game.is_final:
                        continue
                    home = scorer.score_pick(
                        game_id=game.id, sport=sport.upper(),
                        matchup=game.matchup, pick_team=game.home_team,
                        pick_type="ML", odds_american=game.home_odds,
                        cpu_confidence=game.cpu_home_confidence,
                        expert_pct=game.expert_home_pct,
                        fan_pct=game.fan_home_pct,
                    )
                    away = scorer.score_pick(
                        game_id=game.id, sport=sport.upper(),
                        matchup=game.matchup, pick_team=game.away_team,
                        pick_type="ML", odds_american=game.away_odds,
                        cpu_confidence=game.cpu_away_confidence,
                        expert_pct=game.expert_away_pct,
                        fan_pct=game.fan_away_pct,
                    )
                    best = home if home.confidence_score >= away.confidence_score else away
                    if best.recommendation in ("STRONG BET", "BET", "LEAN"):
                        picks.append({
                            "sport": sport.upper(),
                            "matchup": game.matchup,
                            "pick": best.pick_team,
                            "odds": best.odds_american,
                            "confidence": best.confidence_score,
                            "edge": best.edge,
                            "rec": best.recommendation,
                        })
            except:
                pass
        picks.sort(key=lambda x: x["confidence"], reverse=True)
        return {"picks": picks[:10], "error": None}
    except Exception as e:
        return {"picks": [], "error": str(e)}


def get_cron_jobs():
    try:
        result = subprocess.run(
            ["openclaw", "cron", "list", "--json"],
            capture_output=True, text=True, timeout=10
        )
        if result.returncode == 0:
            jobs = json.loads(result.stdout)
            return {"jobs": jobs.get("jobs", [])[:12], "error": None}
    except:
        pass
    return {"jobs": [], "error": "Could not fetch"}


def get_market_pulse():
    """Get quick market data for the ticker."""
    markets = []
    symbols = [("BTC", "Bitcoin"), ("ETH", "Ethereum"), ("SOL", "Solana")]
    for sym, name in symbols:
        try:
            url = f"https://api.coinbase.com/v2/prices/{sym}-USD/spot"
            req = urllib.request.Request(url, headers={"User-Agent": "Nexus/1.0"})
            with urllib.request.urlopen(req, timeout=3) as resp:
                data = json.loads(resp.read())
                markets.append({
                    "symbol": sym,
                    "name": name,
                    "price": float(data["data"]["amount"])
                })
        except:
            pass
    return markets


DASHBOARD_HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>NEXUS</title>
    <style>
        @import url('https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;700&family=Orbitron:wght@400;700;900&display=swap');
        
        * { box-sizing: border-box; margin: 0; padding: 0; }
        
        :root {
            --void: #000000;
            --deep: #0a0a0f;
            --surface: #12121a;
            --border: #1e1e2e;
            --text: #e0e0e0;
            --muted: #666680;
            --cyan: #00fff5;
            --magenta: #ff00ff;
            --green: #00ff88;
            --red: #ff3366;
            --gold: #ffd700;
            --purple: #a855f7;
        }
        
        html, body {
            font-family: 'JetBrains Mono', monospace;
            background: var(--void);
            color: var(--text);
            min-height: 100vh;
            overflow-x: hidden;
        }
        
        /* Animated background grid */
        .grid-bg {
            position: fixed;
            top: 0; left: 0; right: 0; bottom: 0;
            background-image: 
                linear-gradient(rgba(0,255,245,0.03) 1px, transparent 1px),
                linear-gradient(90deg, rgba(0,255,245,0.03) 1px, transparent 1px);
            background-size: 50px 50px;
            animation: gridPulse 4s ease-in-out infinite;
            pointer-events: none;
            z-index: 0;
        }
        
        @keyframes gridPulse {
            0%, 100% { opacity: 0.5; }
            50% { opacity: 1; }
        }
        
        /* Scan line effect */
        .scanline {
            position: fixed;
            top: 0; left: 0; right: 0;
            height: 4px;
            background: linear-gradient(90deg, transparent, var(--cyan), transparent);
            animation: scan 3s linear infinite;
            opacity: 0.3;
            z-index: 100;
            pointer-events: none;
        }
        
        @keyframes scan {
            0% { top: 0; }
            100% { top: 100%; }
        }
        
        .container {
            position: relative;
            z-index: 1;
            max-width: 1600px;
            margin: 0 auto;
            padding: 1rem;
        }
        
        /* Header */
        header {
            text-align: center;
            padding: 2rem 0;
            border-bottom: 1px solid var(--border);
            margin-bottom: 2rem;
            position: relative;
        }
        
        .logo {
            font-family: 'Orbitron', sans-serif;
            font-size: 3rem;
            font-weight: 900;
            letter-spacing: 0.5em;
            background: linear-gradient(135deg, var(--cyan), var(--magenta));
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
            text-shadow: 0 0 60px rgba(0,255,245,0.5);
            animation: glow 2s ease-in-out infinite alternate;
        }
        
        @keyframes glow {
            from { filter: drop-shadow(0 0 20px rgba(0,255,245,0.3)); }
            to { filter: drop-shadow(0 0 40px rgba(255,0,255,0.3)); }
        }
        
        .tagline {
            font-size: 0.75rem;
            color: var(--muted);
            letter-spacing: 0.3em;
            margin-top: 0.5rem;
        }
        
        .status-bar {
            display: flex;
            justify-content: center;
            gap: 2rem;
            margin-top: 1rem;
            font-size: 0.7rem;
        }
        
        .status-item {
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }
        
        .pulse {
            width: 8px;
            height: 8px;
            border-radius: 50%;
            animation: pulse 1.5s ease-in-out infinite;
        }
        
        .pulse-green { background: var(--green); box-shadow: 0 0 10px var(--green); }
        .pulse-red { background: var(--red); box-shadow: 0 0 10px var(--red); }
        .pulse-gold { background: var(--gold); box-shadow: 0 0 10px var(--gold); }
        
        @keyframes pulse {
            0%, 100% { transform: scale(1); opacity: 1; }
            50% { transform: scale(1.3); opacity: 0.7; }
        }
        
        /* Ticker tape */
        .ticker-wrap {
            overflow: hidden;
            background: var(--surface);
            border-top: 1px solid var(--border);
            border-bottom: 1px solid var(--border);
            padding: 0.5rem 0;
            margin-bottom: 2rem;
        }
        
        .ticker {
            display: flex;
            animation: ticker 20s linear infinite;
            white-space: nowrap;
        }
        
        @keyframes ticker {
            0% { transform: translateX(0); }
            100% { transform: translateX(-50%); }
        }
        
        .ticker-item {
            padding: 0 2rem;
            font-size: 0.8rem;
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }
        
        .ticker-symbol { color: var(--cyan); font-weight: 700; }
        .ticker-price { color: var(--text); }
        
        /* Grid layout */
        .dashboard {
            display: grid;
            grid-template-columns: repeat(3, 1fr);
            grid-template-rows: auto auto;
            gap: 1.5rem;
        }
        
        @media (max-width: 1200px) {
            .dashboard { grid-template-columns: repeat(2, 1fr); }
        }
        
        @media (max-width: 768px) {
            .dashboard { grid-template-columns: 1fr; }
        }
        
        /* Cards */
        .card {
            background: linear-gradient(135deg, var(--surface) 0%, var(--deep) 100%);
            border: 1px solid var(--border);
            border-radius: 4px;
            padding: 1.5rem;
            position: relative;
            overflow: hidden;
        }
        
        .card::before {
            content: '';
            position: absolute;
            top: 0;
            left: 0;
            right: 0;
            height: 2px;
            background: linear-gradient(90deg, var(--cyan), var(--magenta));
        }
        
        .card-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 1rem;
            padding-bottom: 0.75rem;
            border-bottom: 1px solid var(--border);
        }
        
        .card-title {
            font-family: 'Orbitron', sans-serif;
            font-size: 0.75rem;
            font-weight: 700;
            letter-spacing: 0.2em;
            color: var(--cyan);
        }
        
        .card-badge {
            font-size: 0.7rem;
            padding: 0.25rem 0.75rem;
            border-radius: 2px;
            font-weight: 700;
        }
        
        .badge-profit { background: rgba(0,255,136,0.1); color: var(--green); border: 1px solid var(--green); }
        .badge-loss { background: rgba(255,51,102,0.1); color: var(--red); border: 1px solid var(--red); }
        .badge-neutral { background: rgba(102,102,128,0.1); color: var(--muted); border: 1px solid var(--muted); }
        
        /* Big number display */
        .big-number {
            font-family: 'Orbitron', sans-serif;
            font-size: 2.5rem;
            font-weight: 900;
            background: linear-gradient(135deg, var(--text), var(--cyan));
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
            line-height: 1;
            margin-bottom: 0.5rem;
        }
        
        .big-label {
            font-size: 0.65rem;
            color: var(--muted);
            letter-spacing: 0.2em;
        }
        
        /* Position rows */
        .position {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 0.75rem 0;
            border-bottom: 1px solid var(--border);
        }
        
        .position:last-child { border-bottom: none; }
        
        .position-left { display: flex; flex-direction: column; gap: 0.25rem; }
        
        .position-symbol {
            font-weight: 700;
            font-size: 0.9rem;
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }
        
        .position-side {
            font-size: 0.6rem;
            padding: 0.15rem 0.4rem;
            border-radius: 2px;
            font-weight: 700;
        }
        
        .side-long { background: rgba(0,255,136,0.2); color: var(--green); }
        .side-short { background: rgba(255,51,102,0.2); color: var(--red); }
        
        .position-entry { font-size: 0.75rem; color: var(--muted); }
        
        .position-pnl {
            font-family: 'Orbitron', sans-serif;
            font-weight: 700;
            font-size: 1.1rem;
        }
        
        .pnl-up { color: var(--green); }
        .pnl-down { color: var(--red); }
        
        /* Mini bar chart */
        .mini-chart {
            display: flex;
            align-items: flex-end;
            gap: 3px;
            height: 40px;
            margin: 1rem 0;
        }
        
        .mini-bar {
            flex: 1;
            background: var(--cyan);
            border-radius: 2px 2px 0 0;
            animation: barGrow 1s ease-out forwards;
            opacity: 0.7;
        }
        
        .mini-bar:hover { opacity: 1; }
        
        @keyframes barGrow {
            from { height: 0; }
        }
        
        /* Pick cards */
        .pick {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 0.6rem 0;
            border-bottom: 1px solid var(--border);
        }
        
        .pick:last-child { border-bottom: none; }
        
        .pick-team {
            font-weight: 700;
            display: flex;
            align-items: center;
            gap: 0.5rem;
        }
        
        .pick-icon {
            font-size: 1.1rem;
        }
        
        .pick-odds {
            font-size: 0.75rem;
            color: var(--muted);
        }
        
        .pick-conf {
            font-family: 'Orbitron', sans-serif;
            font-weight: 700;
        }
        
        .conf-high { color: var(--green); }
        .conf-med { color: var(--gold); }
        .conf-low { color: var(--muted); }
        
        /* Progress ring */
        .ring-container {
            display: flex;
            justify-content: center;
            margin: 1rem 0;
        }
        
        .progress-ring {
            transform: rotate(-90deg);
        }
        
        .progress-ring-circle {
            fill: none;
            stroke: var(--border);
            stroke-width: 8;
        }
        
        .progress-ring-progress {
            fill: none;
            stroke: var(--cyan);
            stroke-width: 8;
            stroke-linecap: round;
            stroke-dasharray: 251.2;
            stroke-dashoffset: 251.2;
            animation: ringFill 1.5s ease-out forwards;
        }
        
        @keyframes ringFill {
            to { stroke-dashoffset: var(--offset); }
        }
        
        /* Cron jobs */
        .cron {
            display: flex;
            align-items: center;
            gap: 0.75rem;
            padding: 0.5rem 0;
            font-size: 0.8rem;
        }
        
        .cron-status {
            width: 6px;
            height: 6px;
            border-radius: 50%;
        }
        
        .cron-ok { background: var(--green); box-shadow: 0 0 6px var(--green); }
        .cron-err { background: var(--red); box-shadow: 0 0 6px var(--red); }
        
        .cron-name { flex: 1; color: var(--text); }
        .cron-agent { color: var(--purple); font-size: 0.7rem; }
        .cron-time { color: var(--muted); font-size: 0.7rem; }
        
        /* Footer */
        footer {
            text-align: center;
            padding: 2rem;
            color: var(--muted);
            font-size: 0.7rem;
        }
        
        .update-time {
            font-family: 'Orbitron', sans-serif;
            color: var(--cyan);
        }
        
        /* Empty state */
        .empty {
            color: var(--muted);
            font-style: italic;
            text-align: center;
            padding: 2rem;
            font-size: 0.85rem;
        }
        
        /* Glitch effect on hover */
        .glitch:hover {
            animation: glitch 0.3s ease;
        }
        
        @keyframes glitch {
            0% { transform: translate(0); }
            20% { transform: translate(-2px, 2px); }
            40% { transform: translate(-2px, -2px); }
            60% { transform: translate(2px, 2px); }
            80% { transform: translate(2px, -2px); }
            100% { transform: translate(0); }
        }
        
        /* Expand card */
        .card.featured {
            grid-column: span 2;
        }
        
        @media (max-width: 768px) {
            .card.featured { grid-column: span 1; }
        }
    </style>
</head>
<body>
    <div class="grid-bg"></div>
    <div class="scanline"></div>
    
    <div class="container">
        <header>
            <div class="logo glitch">NEXUS</div>
            <div class="tagline">UNIFIED COMMAND CENTER</div>
            <div class="status-bar">
                <div class="status-item">
                    <div class="pulse pulse-green"></div>
                    <span>SYSTEMS NOMINAL</span>
                </div>
                <div class="status-item">
                    <div class="pulse pulse-gold"></div>
                    <span id="positions-status">0 POSITIONS</span>
                </div>
                <div class="status-item">
                    <div class="pulse pulse-green"></div>
                    <span id="cron-status">CRON ACTIVE</span>
                </div>
            </div>
        </header>
        
        <div class="ticker-wrap">
            <div class="ticker" id="ticker">
                <div class="ticker-item">
                    <span class="ticker-symbol">BTC</span>
                    <span class="ticker-price">Loading...</span>
                </div>
            </div>
        </div>
        
        <div class="dashboard">
            <!-- Portfolio Card -->
            <div class="card featured">
                <div class="card-header">
                    <span class="card-title">◈ PORTFOLIO</span>
                    <span id="portfolio-badge" class="card-badge badge-neutral">—</span>
                </div>
                <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 2rem;">
                    <div>
                        <div class="big-number" id="equity">$0</div>
                        <div class="big-label">TOTAL EQUITY</div>
                    </div>
                    <div>
                        <div class="big-number" id="pnl">$0</div>
                        <div class="big-label">UNREALIZED P&L</div>
                    </div>
                </div>
                <div id="positions" style="margin-top: 1.5rem;">
                    <p class="empty">Loading positions...</p>
                </div>
            </div>
            
            <!-- Win Rate Ring -->
            <div class="card">
                <div class="card-header">
                    <span class="card-title">◈ PERFORMANCE</span>
                </div>
                <div class="ring-container">
                    <svg class="progress-ring" width="100" height="100">
                        <circle class="progress-ring-circle" cx="50" cy="50" r="40"/>
                        <circle class="progress-ring-progress" id="win-ring" cx="50" cy="50" r="40" style="--offset: 251.2"/>
                    </svg>
                </div>
                <div style="text-align: center;">
                    <div class="big-number" id="win-rate" style="font-size: 1.5rem;">—%</div>
                    <div class="big-label">WIN RATE</div>
                </div>
                <div style="display: flex; justify-content: space-around; margin-top: 1rem;">
                    <div style="text-align: center;">
                        <div id="trades-count" style="font-size: 1.2rem; font-weight: 700; color: var(--cyan);">0</div>
                        <div class="big-label">TRADES</div>
                    </div>
                    <div style="text-align: center;">
                        <div id="wins-count" style="font-size: 1.2rem; font-weight: 700; color: var(--green);">0</div>
                        <div class="big-label">WINS</div>
                    </div>
                </div>
            </div>
            
            <!-- Sports Picks -->
            <div class="card">
                <div class="card-header">
                    <span class="card-title">◈ TODAY'S PICKS</span>
                    <span id="picks-count" class="card-badge badge-neutral">0</span>
                </div>
                <div id="picks">
                    <p class="empty">Loading picks...</p>
                </div>
            </div>
            
            <!-- Cron Jobs -->
            <div class="card">
                <div class="card-header">
                    <span class="card-title">◈ OPERATIONS</span>
                </div>
                <div id="crons">
                    <p class="empty">Loading jobs...</p>
                </div>
            </div>
            
            <!-- System Status -->
            <div class="card">
                <div class="card-header">
                    <span class="card-title">◈ SYSTEMS</span>
                </div>
                <div id="systems">
                    <div class="cron">
                        <div class="cron-status cron-ok"></div>
                        <span class="cron-name">Crypto API</span>
                        <span class="cron-time" id="sys-crypto">checking...</span>
                    </div>
                    <div class="cron">
                        <div class="cron-status cron-ok"></div>
                        <span class="cron-name">Pickwatch</span>
                        <span class="cron-time" id="sys-picks">checking...</span>
                    </div>
                    <div class="cron">
                        <div class="cron-status cron-ok"></div>
                        <span class="cron-name">OpenClaw</span>
                        <span class="cron-time" id="sys-claw">checking...</span>
                    </div>
                </div>
            </div>
        </div>
        
        <footer>
            Last sync: <span class="update-time" id="last-update">—</span>
            <br><br>
            <span style="opacity: 0.5">NEXUS v1.0 — ClawGeeks Command</span>
        </footer>
    </div>
    
    <script>
        // Format currency
        const fmt = (n) => new Intl.NumberFormat('en-US', {
            style: 'currency', currency: 'USD',
            minimumFractionDigits: 2, maximumFractionDigits: 2
        }).format(n);
        
        // Format percent
        const pct = (n) => (n >= 0 ? '+' : '') + n.toFixed(1) + '%';
        
        async function loadCrypto() {
            try {
                const res = await fetch('/api/crypto');
                const data = await res.json();
                
                // Update equity
                document.getElementById('equity').textContent = fmt(data.equity || data.balance);
                
                // Calculate total unrealized PnL
                const totalPnl = data.positions.reduce((sum, p) => sum + (p.pnl_usd || 0), 0);
                const pnlEl = document.getElementById('pnl');
                pnlEl.textContent = (totalPnl >= 0 ? '+' : '') + fmt(totalPnl);
                pnlEl.style.background = totalPnl >= 0 
                    ? 'linear-gradient(135deg, var(--green), var(--cyan))'
                    : 'linear-gradient(135deg, var(--red), var(--magenta))';
                pnlEl.style.webkitBackgroundClip = 'text';
                pnlEl.style.webkitTextFillColor = 'transparent';
                
                // Badge
                const badge = document.getElementById('portfolio-badge');
                if (totalPnl > 0) {
                    badge.className = 'card-badge badge-profit';
                    badge.textContent = '▲ PROFIT';
                } else if (totalPnl < 0) {
                    badge.className = 'card-badge badge-loss';
                    badge.textContent = '▼ LOSS';
                } else {
                    badge.className = 'card-badge badge-neutral';
                    badge.textContent = '— FLAT';
                }
                
                // Status bar
                document.getElementById('positions-status').textContent = 
                    `${data.positions.length} POSITION${data.positions.length !== 1 ? 'S' : ''}`;
                
                // Positions
                const posDiv = document.getElementById('positions');
                if (!data.positions.length) {
                    posDiv.innerHTML = '<p class="empty">No open positions</p>';
                } else {
                    posDiv.innerHTML = data.positions.map(p => {
                        const pnlPct = p.pnl_pct || 0;
                        const pnlClass = pnlPct >= 0 ? 'pnl-up' : 'pnl-down';
                        const sideClass = p.side === 'long' ? 'side-long' : 'side-short';
                        return `
                            <div class="position">
                                <div class="position-left">
                                    <div class="position-symbol">
                                        <span class="position-side ${sideClass}">${p.side.toUpperCase()}</span>
                                        ${p.product}
                                    </div>
                                    <div class="position-entry">Entry: ${fmt(p.entry)}</div>
                                </div>
                                <div class="position-pnl ${pnlClass}">${pct(pnlPct)}</div>
                            </div>
                        `;
                    }).join('');
                }
                
                // Win rate ring
                const winRate = data.trade_count > 0 ? (data.wins / data.trade_count) * 100 : 0;
                const offset = 251.2 - (251.2 * winRate / 100);
                document.getElementById('win-ring').style.setProperty('--offset', offset);
                document.getElementById('win-rate').textContent = winRate.toFixed(0) + '%';
                document.getElementById('trades-count').textContent = data.trade_count;
                document.getElementById('wins-count').textContent = data.wins;
                
                document.getElementById('sys-crypto').textContent = 'online';
            } catch (e) {
                document.getElementById('sys-crypto').textContent = 'error';
            }
        }
        
        async function loadSports() {
            try {
                const res = await fetch('/api/sports');
                const data = await res.json();
                
                document.getElementById('picks-count').textContent = data.picks.length;
                
                const picksDiv = document.getElementById('picks');
                if (!data.picks.length) {
                    picksDiv.innerHTML = '<p class="empty">No live picks</p>';
                } else {
                    picksDiv.innerHTML = data.picks.slice(0, 5).map(p => {
                        const icon = p.rec === 'STRONG BET' ? '🔥' : p.rec === 'BET' ? '✅' : '👀';
                        const confClass = p.confidence >= 80 ? 'conf-high' : p.confidence >= 60 ? 'conf-med' : 'conf-low';
                        return `
                            <div class="pick">
                                <div>
                                    <div class="pick-team">
                                        <span class="pick-icon">${icon}</span>
                                        ${p.pick}
                                    </div>
                                    <div class="pick-odds">${p.sport} · ${p.odds > 0 ? '+' : ''}${p.odds}</div>
                                </div>
                                <div class="pick-conf ${confClass}">${p.confidence}%</div>
                            </div>
                        `;
                    }).join('');
                }
                document.getElementById('sys-picks').textContent = 'online';
            } catch (e) {
                document.getElementById('sys-picks').textContent = 'error';
            }
        }
        
        async function loadCron() {
            try {
                const res = await fetch('/api/cron');
                const data = await res.json();
                
                const errors = data.jobs.filter(j => j.state?.lastStatus === 'error').length;
                document.getElementById('cron-status').textContent = 
                    errors > 0 ? `${errors} ERROR${errors > 1 ? 'S' : ''}` : 'ALL NOMINAL';
                
                const cronDiv = document.getElementById('crons');
                if (!data.jobs?.length) {
                    cronDiv.innerHTML = '<p class="empty">No scheduled jobs</p>';
                } else {
                    cronDiv.innerHTML = data.jobs.slice(0, 6).map(j => {
                        const status = j.state?.lastStatus === 'error' ? 'err' : 'ok';
                        const next = j.state?.nextRunAtMs 
                            ? new Date(j.state.nextRunAtMs).toLocaleTimeString([], {hour: '2-digit', minute:'2-digit'})
                            : '—';
                        return `
                            <div class="cron">
                                <div class="cron-status cron-${status}"></div>
                                <span class="cron-name">${j.name || j.id.slice(0, 8)}</span>
                                <span class="cron-agent">${j.agentId}</span>
                                <span class="cron-time">${next}</span>
                            </div>
                        `;
                    }).join('');
                }
                document.getElementById('sys-claw').textContent = 'online';
            } catch (e) {
                document.getElementById('sys-claw').textContent = 'error';
            }
        }
        
        async function loadTicker() {
            try {
                const res = await fetch('/api/ticker');
                const markets = await res.json();
                
                const tickerEl = document.getElementById('ticker');
                const items = markets.map(m => `
                    <div class="ticker-item">
                        <span class="ticker-symbol">${m.symbol}</span>
                        <span class="ticker-price">${fmt(m.price)}</span>
                    </div>
                `).join('');
                // Duplicate for seamless loop
                tickerEl.innerHTML = items + items;
            } catch (e) {}
        }
        
        function loadAll() {
            loadCrypto();
            loadSports();
            loadCron();
            loadTicker();
            document.getElementById('last-update').textContent = 
                new Date().toLocaleTimeString([], {hour: '2-digit', minute:'2-digit', second:'2-digit'});
        }
        
        loadAll();
        setInterval(loadAll, 30000);
    </script>
</body>
</html>"""


class NexusHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        path = urlparse(self.path).path
        
        if path == "/":
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(DASHBOARD_HTML.encode())
        elif path == "/api/crypto":
            self._json(get_crypto_positions())
        elif path == "/api/sports":
            self._json(get_sports_picks())
        elif path == "/api/cron":
            self._json(get_cron_jobs())
        elif path == "/api/ticker":
            self._json(get_market_pulse())
        elif path == "/api/status":
            self._json({"timestamp": datetime.now(timezone.utc).isoformat()})
        else:
            self.send_error(404)
    
    def _json(self, data):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())
    
    def log_message(self, format, *args):
        pass


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=5001)
    parser.add_argument("--host", default="0.0.0.0")
    args = parser.parse_args()
    
    server = HTTPServer((args.host, args.port), NexusHandler)
    print(f"""
    ╔═══════════════════════════════════════╗
    ║           N E X U S                   ║
    ║      Command Center Online            ║
    ╠═══════════════════════════════════════╣
    ║  http://{args.host}:{args.port:<21} ║
    ╚═══════════════════════════════════════╝
    """)
    server.serve_forever()


if __name__ == "__main__":
    main()
