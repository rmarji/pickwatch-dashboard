"""
Pickwatch API Client - Unified interface for all endpoints.

Uses stdlib urllib (no external dependencies).
"""

import os
import json
import ssl
from urllib.request import urlopen, Request
from urllib.error import HTTPError
from datetime import datetime, date
from dataclasses import dataclass
from typing import Optional


@dataclass
class GameData:
    """Unified game data from Pickwatch."""
    id: int
    sport: str
    date: str
    home_team: str
    away_team: str
    kickoff: Optional[datetime]
    game_state: str
    
    # Scores
    home_score: Optional[int] = None
    away_score: Optional[int] = None
    
    # Odds (American)
    home_odds: int = 0
    away_odds: int = 0
    home_spread: float = 0
    over_under: float = 0
    
    # Expert consensus (SU)
    expert_home_pct: float = 0
    expert_away_pct: float = 0
    expert_picks: int = 0
    
    # Fan consensus (SU)
    fan_home_pct: float = 0
    fan_away_pct: float = 0
    fan_picks: int = 0
    
    # CPU Premium picks (added from premium endpoint)
    cpu_home_confidence: float = 0
    cpu_away_confidence: float = 0
    cpu_pick: str = ""
    
    @property
    def matchup(self) -> str:
        return f"{self.away_team} @ {self.home_team}"
    
    @property
    def is_final(self) -> bool:
        return self.game_state in ("Final", "F/OT", "F")
    
    @property
    def winner(self) -> Optional[str]:
        if not self.is_final or self.home_score is None:
            return None
        if self.home_score > self.away_score:
            return self.home_team
        elif self.away_score > self.home_score:
            return self.away_team
        return "TIE"


class PickwatchAPI:
    """Unified Pickwatch API client using stdlib."""
    
    BASE_URL = "https://api.pickwatch.com/v1"
    
    def __init__(self, token: Optional[str] = None):
        self.token = token or os.getenv("PICKWATCH_TOKEN")
        if not self.token:
            raise ValueError("PICKWATCH_TOKEN required")
        # SSL context
        self._ssl_ctx = ssl.create_default_context()
    
    def _get(self, path: str, origin: str = "https://nflpickwatch.com") -> dict | list:
        url = f"{self.BASE_URL}{path}"
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Origin": origin,
            "Referer": f"{origin}/",
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0",
        }
        
        req = Request(url, headers=headers)
        try:
            with urlopen(req, context=self._ssl_ctx, timeout=30) as resp:
                return json.loads(resp.read().decode())
        except HTTPError as e:
            if e.code in (404, 500):
                return []
            raise
    
    def _sport_origin(self, sport: str) -> str:
        """Get correct origin for sport."""
        origins = {
            "nfl": "https://nflpickwatch.com",
            "nba": "https://nbapickwatch.com", 
            "mlb": "https://mlbpickwatch.com",
            "nhl": "https://nhlpickwatch.com",
        }
        return origins.get(sport.lower(), "https://nflpickwatch.com")
    
    def get_games(
        self,
        sport: str = "nba",
        year: str = "2024",
        day: str = None,
    ) -> list[GameData]:
        """Fetch games with consensus data."""
        if day is None:
            day = date.today().isoformat()
        
        origin = self._sport_origin(sport)
        path = f"/general/games/{year}/{day}/{sport}/REGULAR"
        
        data = self._get(path, origin)
        if not data:
            return []
        
        games = []
        for g in data:
            kickoff = None
            if g.get("kickoff"):
                try:
                    kickoff = datetime.fromisoformat(
                        g["kickoff"].replace("Z", "+00:00")
                    )
                except:
                    pass
            
            game = GameData(
                id=g["id"],
                sport=sport.upper(),
                date=day,
                home_team=g.get("home_team_id", ""),
                away_team=g.get("road_team_id", ""),
                kickoff=kickoff,
                game_state=g.get("game_state", "Scheduled"),
                home_score=g.get("home_team_score"),
                away_score=g.get("road_team_score"),
                home_odds=g.get("home_team_odds_ame", 0) or 0,
                away_odds=g.get("road_team_odds_ame", 0) or 0,
                home_spread=g.get("home_team_spread", 0) or 0,
                over_under=g.get("over_under", 0) or 0,
                expert_home_pct=g.get("ht_pct_su_experts", 0) or 0,
                expert_away_pct=g.get("rt_pct_su_experts", 0) or 0,
                expert_picks=g.get("picks_su_experts", 0) or 0,
                fan_home_pct=g.get("ht_pct_su_fans", 0) or 0,
                fan_away_pct=g.get("rt_pct_su_fans", 0) or 0,
                fan_picks=g.get("picks_su_fans", 0) or 0,
            )
            games.append(game)
        
        return games
    
    def get_premium_picks(
        self,
        sport: str = "nba",
        year: str = "2024",
        day: str = None,
        pick_type: str = "su",
    ) -> dict[int, dict]:
        """Fetch CPU premium picks with confidence scores."""
        if day is None:
            day = date.today().isoformat()
        
        origin = self._sport_origin(sport)
        path = f"/general/marketplace/premium-picks/{sport}/{year}/{day}/{pick_type}/"
        
        data = self._get(path, origin)
        if not data:
            return {}
        
        picks = {}
        if isinstance(data, dict) and data.get("experts"):
            for expert in data["experts"]:
                expert_picks = expert.get("picks", {})
                for game_id, pick in expert_picks.items():
                    if pick.get("team_id"):
                        picks[int(game_id)] = {
                            "team": pick["team_id"],
                            "confidence": pick.get("confidence", 0),
                        }
        
        return picks
    
    def get_games_with_cpu(
        self,
        sport: str = "nba",
        year: str = "2024",
        day: str = None,
    ) -> list[GameData]:
        """Get games with CPU confidence merged in."""
        games = self.get_games(sport, year, day)
        cpu_picks = self.get_premium_picks(sport, year, day, "su")
        
        for game in games:
            if game.id in cpu_picks:
                pick = cpu_picks[game.id]
                if pick["team"] == game.home_team:
                    game.cpu_home_confidence = pick["confidence"]
                    game.cpu_away_confidence = 1 - pick["confidence"]
                    game.cpu_pick = game.home_team
                else:
                    game.cpu_away_confidence = pick["confidence"]
                    game.cpu_home_confidence = 1 - pick["confidence"]
                    game.cpu_pick = game.away_team
        
        return games
    
    def close(self):
        pass  # No cleanup needed for urllib
    
    def __enter__(self):
        return self
    
    def __exit__(self, *args):
        self.close()


if __name__ == "__main__":
    # Quick test
    import os
    with open('/data/workspace-cto/config/pickwatch.env') as f:
        for line in f:
            if line.startswith('PICKWATCH_TOKEN='):
                os.environ['PICKWATCH_TOKEN'] = line.split('=', 1)[1].strip()
    
    api = PickwatchAPI()
    games = api.get_games("nba", "2024", date.today().isoformat())
    print(f"Found {len(games)} NBA games")
    for g in games[:3]:
        print(f"  {g.matchup}")
