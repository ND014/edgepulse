"""
Live API feed adapter for The-Odds-API (https://the-odds-api.com).
Uses pure Python standard library (urllib) with zero external dependencies.
"""

import json
import time
import urllib.request
import urllib.error
from typing import AsyncIterator, Dict, List, Optional
from ..models import OddsQuote, Sport, MarketType, OddsFormat


SPORT_KEY_MAP: Dict[Sport, List[str]] = {
    Sport.UFC: ["mma_mixed_martial_arts"],
    Sport.TENNIS: ["tennis_atp", "tennis_wta"],
    Sport.BASKETBALL_NBA: ["basketball_nba"],
    Sport.CRICKET_T20: ["cricket_ipl", "cricket_t20_blast", "cricket_international_t20"],
    Sport.SOCCER_DNB: ["soccer_epl", "soccer_uefa_champs_league"],
}


class TheOddsAPIFeed:
    """
    Ingests live odds from The-Odds-API endpoint:
    GET https://api.the-odds-api.com/v4/sports/{sport}/odds/?apiKey={key}&regions=us,eu&markets=h2h
    """

    BASE_URL = "https://api.the-odds-api.com/v4/sports"

    def __init__(
        self,
        api_key: str,
        sports: Optional[List[Sport]] = None,
        poll_interval_sec: float = 15.0,
    ):
        if not api_key:
            raise ValueError("An API key is required to connect to The-Odds-API")
        self.api_key = api_key
        self.sports = sports or list(Sport)
        self.poll_interval_sec = poll_interval_sec

    def fetch_sport_odds(self, sport_key: str) -> List[dict]:
        """Synchronously pull JSON from endpoint."""
        url = (
            f"{self.BASE_URL}/{sport_key}/odds/"
            f"?apiKey={self.api_key}&regions=us,us2,uk,eu,au&markets=h2h&oddsFormat=american"
        )
        req = urllib.request.Request(
            url,
            headers={"User-Agent": "OddsAnomalyEngine/1.0", "Accept": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as response:
                if response.status == 200:
                    return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"The-Odds-API returned HTTP {e.code}: {e.read().decode('utf-8')}")
        except Exception as e:
            raise RuntimeError(f"Failed to fetch odds from {url}: {e}")
        return []

    async def stream_quotes(self) -> AsyncIterator[OddsQuote]:
        """Asynchronously polls and yields OddsQuote objects."""
        import asyncio

        while True:
            for sport in self.sports:
                sport_keys = SPORT_KEY_MAP.get(sport, [])
                for key in sport_keys:
                    try:
                        data = await asyncio.to_thread(self.fetch_sport_odds, key)
                        for item in data:
                            event_id = item.get("id")
                            home_team = item.get("home_team")
                            away_team = item.get("away_team")

                            for bookmaker_data in item.get("bookmakers", []):
                                book_name = bookmaker_data.get("key", "").lower()
                                for market in bookmaker_data.get("markets", []):
                                    if market.get("key") == "h2h":
                                        outcomes = market.get("outcomes", [])
                                        # Strict 2-way check: only accept exactly 2 outcomes
                                        if len(outcomes) != 2:
                                            continue

                                        side_a_name = outcomes[0].get("name")
                                        side_a_price = outcomes[0].get("price")
                                        side_b_name = outcomes[1].get("name")
                                        side_b_price = outcomes[1].get("price")

                                        yield OddsQuote(
                                            event_id=event_id,
                                            sport=sport,
                                            market_type=MarketType.HEAD_TO_HEAD,
                                            bookmaker=book_name,
                                            side_a=side_a_name,
                                            side_b=side_b_name,
                                            side_a_odds=float(side_a_price),
                                            side_b_odds=float(side_b_price),
                                            odds_format=OddsFormat.AMERICAN,
                                            timestamp=time.time(),
                                        )
                    except Exception as e:
                        # Log error and continue to next sport
                        pass
            await asyncio.sleep(self.poll_interval_sec)
