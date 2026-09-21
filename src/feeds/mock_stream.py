"""
High-throughput asynchronous mock stream generator.
Simulates realistic multi-book market micro-dynamics across all target sports.
"""

import asyncio
import random
import time
from typing import AsyncIterator, List, Tuple
from ..models import OddsQuote, Sport, MarketType, OddsFormat
from ..math_engine import implied_prob_to_american


class MockStreamFeed:
    """
    Generates real-time synthetic odds feeds simulating Pinnacle price leadership,
    variable soft-book latency lag, and retail mispricings across all supported sports.
    """

    SAMPLE_EVENTS: List[Tuple[Sport, MarketType, str, str, float]] = [
        # UFC / MMA
        (Sport.UFC, MarketType.HEAD_TO_HEAD, "Jon Jones", "Alex Pereira", 0.58),
        (Sport.UFC, MarketType.HEAD_TO_HEAD, "Arman Tsarukyan", "Mauricio Ruffy", 0.73),
        # Boxing
        (Sport.BOXING, MarketType.HEAD_TO_HEAD, "Canelo Alvarez", "Terence Crawford", 0.54),
        (Sport.BOXING, MarketType.HEAD_TO_HEAD, "Tyson Fury", "Oleksandr Usyk", 0.48),
        # Baseball (MLB)
        (Sport.BASEBALL, MarketType.MONEYLINE, "New York Yankees", "Boston Red Sox", 0.56),
        (Sport.BASEBALL, MarketType.MONEYLINE, "Los Angeles Dodgers", "San Francisco Giants", 0.62),
        # Tennis
        (Sport.TENNIS, MarketType.HEAD_TO_HEAD, "Carlos Alcaraz", "Jannik Sinner", 0.52),
        (Sport.TENNIS, MarketType.HEAD_TO_HEAD, "Novak Djokovic", "Daniil Medvedev", 0.57),
        # Basketball (NBA)
        (Sport.BASKETBALL_NBA, MarketType.MONEYLINE, "LA Lakers", "Boston Celtics", 0.44),
        (Sport.BASKETBALL_NBA, MarketType.MONEYLINE, "Golden State Warriors", "Denver Nuggets", 0.48),
        # Cricket (T20)
        (Sport.CRICKET_T20, MarketType.HEAD_TO_HEAD, "Chennai Super Kings", "Mumbai Indians", 0.53),
        (Sport.CRICKET_T20, MarketType.HEAD_TO_HEAD, "England", "Sri Lanka", 0.65),
        # Soccer (Draw No Bet)
        (Sport.SOCCER_DNB, MarketType.DRAW_NO_BET, "Manchester City", "Arsenal", 0.61),
        (Sport.SOCCER_DNB, MarketType.DRAW_NO_BET, "Real Madrid", "Barcelona", 0.55),
    ]

    BOOKMAKERS = ["pinnacle", "draftkings", "fanduel", "betmgm", "bovada"]

    def __init__(
        self,
        tick_delay_sec: float = 0.2,
        anomaly_chance: float = 0.35,
        total_ticks: int = 0,
    ):
        self.tick_delay_sec = tick_delay_sec
        self.anomaly_chance = anomaly_chance
        self.total_ticks = total_ticks
        self._current_probs = {f"{e[0].value}:{e[2]}_vs_{e[3]}": e[4] for e in self.SAMPLE_EVENTS}

    async def stream_quotes(self) -> AsyncIterator[OddsQuote]:
        """Yield realistic multi-book odds updates."""
        ticks_emitted = 0

        while self.total_ticks == 0 or ticks_emitted < self.total_ticks:
            sport, market_type, side_a, side_b, _ = random.choice(self.SAMPLE_EVENTS)
            event_key = f"{sport.value}:{side_a}_vs_{side_b}"

            drift = random.uniform(-0.02, 0.02)
            new_p_a = max(0.20, min(0.80, self._current_probs[event_key] + drift))
            self._current_probs[event_key] = new_p_a
            p_b = 1.0 - new_p_a

            # Emit Pinnacle line (low margin ~2.5%)
            pin_vig = 0.025
            pin_p_a = new_p_a * (1.0 + pin_vig / 2)
            pin_p_b = p_b * (1.0 + pin_vig / 2)
            pin_odds_a = implied_prob_to_american(pin_p_a)
            pin_odds_b = implied_prob_to_american(pin_p_b)

            yield OddsQuote(
                event_id=event_key,
                sport=sport,
                market_type=market_type,
                bookmaker="pinnacle",
                side_a=side_a,
                side_b=side_b,
                side_a_odds=float(pin_odds_a),
                side_b_odds=float(pin_odds_b),
                odds_format=OddsFormat.AMERICAN,
                timestamp=time.time(),
            )
            ticks_emitted += 1
            if self.tick_delay_sec > 0:
                await asyncio.sleep(self.tick_delay_sec)

            # Emit soft retail books
            soft_books = [b for b in self.BOOKMAKERS if b != "pinnacle"]
            for book in soft_books:
                retail_vig = 0.055

                is_anomaly = random.random() < self.anomaly_chance
                if is_anomaly:
                    error = random.uniform(0.04, 0.08)
                    soft_p_a = max(0.10, new_p_a - error) * (1.0 + retail_vig / 2)
                    soft_p_b = p_b * (1.0 + retail_vig / 2)
                else:
                    soft_p_a = new_p_a * (1.0 + retail_vig / 2)
                    soft_p_b = p_b * (1.0 + retail_vig / 2)

                soft_odds_a = implied_prob_to_american(soft_p_a)
                soft_odds_b = implied_prob_to_american(soft_p_b)

                yield OddsQuote(
                    event_id=event_key,
                    sport=sport,
                    market_type=market_type,
                    bookmaker=book,
                    side_a=side_a,
                    side_b=side_b,
                    side_a_odds=float(soft_odds_a),
                    side_b_odds=float(soft_odds_b),
                    odds_format=OddsFormat.AMERICAN,
                    timestamp=time.time(),
                )
                ticks_emitted += 1
                if self.tick_delay_sec > 0:
                    await asyncio.sleep(self.tick_delay_sec)
