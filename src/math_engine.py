"""
Quantitative math core for sports betting odds conversions, proportional devigging,
and edge/anomaly calculations.
"""

import math
from typing import Tuple


def american_to_decimal(american: float) -> float:
    """Convert American odds to Decimal payout factor."""
    if american == 0:
        raise ValueError("American odds cannot be 0")
    if american > 0:
        return 1.0 + (american / 100.0)
    else:
        return 1.0 + (100.0 / abs(american))


def decimal_to_american(decimal_odds: float) -> int:
    """Convert Decimal odds to standard American odds integer."""
    if decimal_odds <= 1.0:
        raise ValueError(f"Decimal odds must be strictly > 1.0, got {decimal_odds}")
    if decimal_odds >= 2.0:
        return int(round((decimal_odds - 1.0) * 100.0))
    else:
        return int(round(-100.0 / (decimal_odds - 1.0)))


def american_to_implied_prob(american: float) -> float:
    """
    Calculate raw bookmaker implied probability from American odds.
    Negative (-odds): |odds| / (|odds| + 100)
    Positive (+odds): 100 / (odds + 100)
    """
    if american == 0:
        raise ValueError("American odds cannot be 0")
    if american < 0:
        return abs(american) / (abs(american) + 100.0)
    else:
        return 100.0 / (american + 100.0)


def decimal_to_implied_prob(decimal_odds: float) -> float:
    """Calculate implied probability from decimal odds."""
    if decimal_odds <= 1.0:
        raise ValueError(f"Decimal odds must be strictly > 1.0, got {decimal_odds}")
    return 1.0 / decimal_odds


def implied_prob_to_american(prob: float) -> int:
    """Convert a probability (0.0 < prob < 1.0) to fair American odds."""
    if not (0.0 < prob < 1.0):
        raise ValueError(f"Probability must be between 0 and 1, got {prob}")
    if prob >= 0.5:
        # Favorite
        return int(round(-(prob / (1.0 - prob)) * 100.0))
    else:
        # Underdog
        return int(round(((1.0 - prob) / prob) * 100.0))


def proportional_devig(p_raw_a: float, p_raw_b: float) -> Tuple[float, float, float]:
    """
    Strip the house overround (vig) using the standard Proportional / Multiplicative model:
    S = P_raw,A + P_raw,B
    P_true,A = P_raw,A / S
    P_true,B = P_raw,B / S
    
    Returns:
        (p_true_a, p_true_b, total_overround_sum)
    """
    if p_raw_a <= 0 or p_raw_b <= 0:
        raise ValueError(f"Raw probabilities must be positive: got {p_raw_a}, {p_raw_b}")
    
    overround_sum = p_raw_a + p_raw_b
    p_true_a = p_raw_a / overround_sum
    p_true_b = p_raw_b / overround_sum
    return p_true_a, p_true_b, overround_sum


def calculate_discrepancy(p_true_sharp: float, p_implied_soft: float) -> float:
    """
    Difference between sharp consensus true probability and soft book implied probability:
    Delta = P_true,sharp - P_implied,soft
    A positive Delta means the soft book is underestimating the side's likelihood
    (i.e., paying out more than it should).
    """
    return p_true_sharp - p_implied_soft


def calculate_ev(p_true_sharp: float, soft_decimal_odds: float) -> float:
    """
    Calculate Expected Value (+EV edge):
    EV = (P_true,sharp * soft_decimal_odds) - 1.0
    An EV > 0 represents a mathematically profitable long-term wager.
    """
    return (p_true_sharp * soft_decimal_odds) - 1.0


def calculate_kelly_stake(
    p_true: float,
    decimal_odds: float,
    bankroll: float,
    fraction_multiplier: float = 0.25,
) -> Tuple[float, float, float]:
    """
    Calculate optimal bankroll stake size using the Kelly Criterion for 2-way betting:
    
    Formula:
        b = decimal_odds - 1.0 (net odds payout factor)
        p = p_true
        q = 1.0 - p_true
        f* = (b * p - q) / b = (p * decimal_odds - 1.0) / (decimal_odds - 1.0) = EV / b
        
    Adjusted fraction:
        f_adj = max(0.0, f* * fraction_multiplier)
        
    Returns:
        (recommended_dollar_stake, stake_fraction_percent, expected_dollar_profit)
    """
    if decimal_odds <= 1.0 or bankroll <= 0.0 or p_true <= 0.0 or p_true >= 1.0:
        return 0.0, 0.0, 0.0
    
    b = decimal_odds - 1.0
    ev = (p_true * decimal_odds) - 1.0
    
    if ev <= 0:
        return 0.0, 0.0, 0.0
        
    full_kelly_f = ev / b
    adj_fraction = max(0.0, min(1.0, full_kelly_f * fraction_multiplier))
    stake = round(bankroll * adj_fraction, 2)
    expected_profit = round(stake * ev, 2)
    
    return stake, round(adj_fraction * 100.0, 2), expected_profit

