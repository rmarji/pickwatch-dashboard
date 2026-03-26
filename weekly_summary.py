#!/usr/bin/env python3
"""
Weekly Summary — Performance report for Notion and Telegram.

Generates a weekly performance summary:
- Picks by sport
- W/L record
- Profit/Loss (if bet tracking enabled)
- Notion page update (optional)

Usage:
    python3 weekly_summary.py              # Print summary to stdout
    python3 weekly_summary.py --notion     # Update Notion page
    python3 weekly_summary.py --telegram   # Send to Telegram
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

# Adjust path for imports
sys.path.insert(0, str(Path(__file__).parent))

from history import PickHistory, calculate_performance, format_stats_telegram


# ─── Notion Integration ────────────────────────────────────────────────────────

NOTION_API = "https://api.notion.com/v1"
NOTION_VERSION = "2022-06-28"


def get_notion_token() -> str:
    """Get Notion token from Infisical or env."""
    # Try Infisical first
    try:
        import subprocess
        result = subprocess.run(
            ["/data/.openclaw/skills/infisical/get-secret.sh", 
             "NOTION_INTERNAL_KEY_LIFE", "/integrations/notion"],
            capture_output=True, text=True, timeout=30,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()
    except Exception:
        pass
    
    # Fallback to env
    return os.getenv("NOTION_INTERNAL_KEY_LIFE", "")


def update_notion_page(page_id: str, content: str, token: str) -> bool:
    """Update a Notion page with new content."""
    # Notion API requires blocks, not raw text
    # We'll create a simple callout block for the summary
    
    # First, clear existing content (append mode, not replace)
    # For simplicity, we'll just append a new section
    
    url = f"{NOTION_API}/blocks/{page_id}/children"
    
    # Split content into paragraph blocks
    lines = content.strip().split("\n")
    blocks = []
    
    for line in lines:
        if not line.strip():
            continue
        # Bold lines become headings
        if line.startswith("**") and line.endswith("**"):
            blocks.append({
                "object": "block",
                "type": "heading_2",
                "heading_2": {
                    "rich_text": [{"type": "text", "text": {"content": line.strip("*")}}]
                }
            })
        else:
            blocks.append({
                "object": "block",
                "type": "paragraph",
                "paragraph": {
                    "rich_text": [{"type": "text", "text": {"content": line}}]
                }
            })
    
    # Limit to 100 blocks (Notion limit)
    blocks = blocks[:100]
    
    payload = {"children": blocks}
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Notion-Version": NOTION_VERSION,
    }
    
    ctx = ssl.create_default_context()
    req = Request(url, data=json.dumps(payload).encode(), headers=headers, method='PATCH')
    
    try:
        with urlopen(req, context=ctx, timeout=30) as resp:
            result = json.loads(resp.read())
            return True
    except HTTPError as e:
        body = e.read().decode()
        print(f"[notion] HTTP {e.code}: {body}", file=sys.stderr)
        return False
    except Exception as e:
        print(f"[notion] Error: {e}", file=sys.stderr)
        return False


def find_notion_page(title: str, token: str) -> Optional[str]:
    """Search for a Notion page by title."""
    url = f"{NOTION_API}/search"
    payload = {
        "query": title,
        "filter": {"property": "object", "value": "page"},
        "page_size": 10,
    }
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Notion-Version": NOTION_VERSION,
    }
    
    ctx = ssl.create_default_context()
    req = Request(url, data=json.dumps(payload).encode(), headers=headers)
    
    try:
        with urlopen(req, context=ctx, timeout=30) as resp:
            result = json.loads(resp.read())
            for item in result.get("results", []):
                if title.lower() in item.get("properties", {}).get("title", {}).get("plain_text", "").lower():
                    return item["id"]
    except Exception as e:
        print(f"[notion] Search error: {e}", file=sys.stderr)
    
    return None


# ─── Telegram Integration ──────────────────────────────────────────────────────

def get_telegram_config() -> tuple[str, str]:
    """Return (bot_token, chat_id) from environment."""
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    return token, chat_id


def send_telegram(text: str) -> bool:
    """Send a message to Telegram."""
    token, chat_id = get_telegram_config()
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


# ─── Core Logic ───────────────────────────────────────────────────────────────

def generate_weekly_summary(history: PickHistory) -> str:
    """Generate the weekly summary text."""
    today = date.today()
    week_ago = today - timedelta(days=7)
    
    # Get overall stats
    overall = calculate_performance(history, start_date=week_ago, end_date=today, bet_only=False)
    
    # Get sport breakdown
    sports = ["NBA", "NHL", "NFL", "MLB", "NCAAB", "NCAAF"]
    sport_stats = {}
    for sport in sports:
        stats = calculate_performance(history, sport=sport, start_date=week_ago, end_date=today, bet_only=False)
        if stats.total_picks > 0:
            sport_stats[sport] = stats
    
    # Format output
    lines = [
        f"📅 **WEEKLY PICKS SUMMARY**",
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"",
        f"**Date Range:** {week_ago.strftime('%b %d')} – {today.strftime('%b %d')}",
        f"",
        f"**Overall Record:** {overall.wins}W – {overall.losses}L – {overall.pushes}P",
    ]
    
    if overall.wins + overall.losses > 0:
        lines.append(f"**Win Rate:** {overall.win_rate:.0f}%")
    
    if overall.pending > 0:
        lines.append(f"**Pending:** {overall.pending}")
    
    lines.append("")
    lines.append("**By Sport:**")
    
    for sport, stats in sport_stats.items():
        decided = stats.wins + stats.losses
        if decided > 0:
            pct = (stats.wins / decided) * 100
            lines.append(f"  {sport}: {stats.wins}W-{stats.losses}L ({pct:.0f}%)")
        elif stats.pending > 0:
            lines.append(f"  {sport}: {stats.pending} pending")
    
    lines.append("")
    lines.append("**By Recommendation:**")
    lines.append(f"  🔥 STRONG BET: {overall.strong_bet_record}")
    lines.append(f"  ✓ BET: {overall.bet_record}")
    lines.append(f"  → LEAN: {overall.lean_record}")
    
    # Betting stats (if applicable)
    if overall.total_wagered > 0:
        lines.append("")
        lines.append("**Betting Performance:**")
        lines.append(f"  Wagered: ${overall.total_wagered:.2f}")
        lines.append(f"  Payout: ${overall.total_payout:.2f}")
        lines.append(f"  Net: ${overall.net_profit:+.2f}")
        lines.append(f"  ROI: {overall.roi:+.1f}%")
    
    lines.append("")
    lines.append(f"_Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}_")
    
    return "\n".join(lines)


# ─── CLI ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Weekly picks summary")
    parser.add_argument("--notion", action="store_true", help="Update Notion page")
    parser.add_argument("--telegram", action="store_true", help="Send to Telegram")
    parser.add_argument("--page-id", default=None, help="Notion page ID (auto-search if not provided)")
    args = parser.parse_args()
    
    # Load env
    _load_env()
    
    # Generate summary
    history = PickHistory()
    summary = generate_weekly_summary(history)
    
    if args.notion:
        token = get_notion_token()
        if not token:
            print("[notion] No token available", file=sys.stderr)
            sys.exit(1)
        
        # Find or use page
        page_id = args.page_id
        if not page_id:
            page_id = find_notion_page("Sports Prediction Project", token)
        
        if not page_id:
            print("[notion] Could not find Sports Prediction Project page", file=sys.stderr)
            sys.exit(1)
        
        # Update page
        if update_notion_page(page_id, summary, token):
            print(f"[notion] Updated page {page_id}")
        else:
            print("[notion] Failed to update page", file=sys.stderr)
            sys.exit(1)
    
    elif args.telegram:
        if send_telegram(summary):
            print("[telegram] Sent summary")
        else:
            print("[telegram] Failed to send", file=sys.stderr)
            sys.exit(1)
    
    else:
        print(summary)


def _load_env():
    """Load environment from config files."""
    # Pickwatch token
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