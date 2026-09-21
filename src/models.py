"""
Data models and domain schemas for the Odds Normalization & Anomaly Engine.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class Sport(str, Enum):
    UFC = "ufc"
    BOXING = "boxing"
    BASEBALL = "baseball"
    TENNIS = "tennis"
    BASKETBALL_NBA = "basketball_nba"
    CRICKET_T20 = "cricket_t20"
    SOCCER_DNB = "soccer_dnb"  # Draw No Bet / Asian Handicap 0.0


class MarketType(str, Enum):
    HEAD_TO_HEAD = "head_to_head"
    MONEYLINE = "moneyline"
    DRAW_NO_BET = "draw_no_bet"


class OddsFormat(str, Enum):
    AMERICAN = "american"
    DECIMAL = "decimal"


@dataclass(frozen=True)
class OddsQuote:
    """Raw incoming quote from a sportsbook for a 2-way event."""
    event_id: str
    sport: Sport
    market_type: MarketType
    bookmaker: str
    side_a: str
    side_b: str
    side_a_odds: float
    side_b_odds: float
    odds_format: OddsFormat = OddsFormat.AMERICAN
    timestamp: float = 0.0
    commence_time: str = ""


@dataclass(frozen=True)
class NormalizedQuote:
    """Normalized 2-way odds with standardized probability & decimal representations."""
    event_id: str
    sport: Sport
    market_type: MarketType
    bookmaker: str
    side_a: str
    side_b: str
    american_a: int
    american_b: int
    decimal_a: float
    decimal_b: float
    p_raw_a: float
    p_raw_b: float
    overround: float
    timestamp: float
    commence_time: str = ""


@dataclass(frozen=True)
class DeviggedConsensus:
    """True market probability stripped of sharp bookmaker vig."""
    event_id: str
    sport: Sport
    sharp_bookmaker: str
    side_a: str
    side_b: str
    p_true_a: float
    p_true_b: float
    sharp_overround: float
    fair_decimal_a: float
    fair_decimal_b: float
    timestamp: float
    commence_time: str = ""


@dataclass(frozen=True)
class AnomalyAlert:
    """Alert triggered when a soft retail book misprices relative to sharp consensus."""
    event_id: str
    sport: Sport
    target_book: str
    sharp_book: str
    selection_name: str
    soft_american: int
    soft_decimal: float
    soft_implied_prob: float
    sharp_true_prob: float
    discrepancy_delta: float  # P_true - P_implied
    expected_value: float     # (P_true * soft_decimal) - 1.0
    timestamp: float
    commence_time: str = ""

    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "sport": self.sport.value,
            "target_book": self.target_book,
            "sharp_book": self.sharp_book,
            "selection": self.selection_name,
            "soft_american": f"{self.soft_american:+d}",
            "soft_decimal": round(self.soft_decimal, 3),
            "soft_implied_prob": f"{self.soft_implied_prob * 100:.2f}%",
            "sharp_true_prob": f"{self.sharp_true_prob * 100:.2f}%",
            "delta": f"{self.discrepancy_delta * 100:+.2f}%",
            "expected_value": f"{self.expected_value * 100:+.2f}%",
            "timestamp": self.timestamp,
            "commence_time": self.commence_time,
        }
