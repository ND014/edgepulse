"""
EdgePulse Arbitrage (Surebet) Detection Module
Mathematical scanner for negative-margin two-way betting mispricings.
"""

from typing import Any, Callable, Dict, List, Optional


def calculate_arbitrage_stakes(
    total_investment: float,
    odds_a: float,
    odds_b: float,
) -> Dict[str, float]:
    """Calculate exact hedge stakes and guaranteed profit for an arbitrage pair."""
    if odds_a <= 1.0 or odds_b <= 1.0 or total_investment <= 0:
        return {
            "stake_a": 0.0,
            "stake_b": 0.0,
            "payout_a": 0.0,
            "payout_b": 0.0,
            "guaranteed_profit": 0.0,
            "profit_pct": 0.0,
        }

    implied_a = 1.0 / odds_a
    implied_b = 1.0 / odds_b
    implied_sum = implied_a + implied_b

    stake_a = round((total_investment * implied_a) / implied_sum, 2)
    stake_b = round(total_investment - stake_a, 2)

    payout_a = round(stake_a * odds_a, 2)
    payout_b = round(stake_b * odds_b, 2)
    guaranteed_payout = min(payout_a, payout_b)
    guaranteed_profit = round(guaranteed_payout - total_investment, 2)
    profit_pct = round(((1.0 / implied_sum) - 1.0) * 100, 2)

    return {
        "stake_a": stake_a,
        "stake_b": stake_b,
        "payout_a": payout_a,
        "payout_b": payout_b,
        "guaranteed_profit": guaranteed_profit,
        "profit_pct": profit_pct,
    }


def find_arbitrage_opportunities(
    events: List[Dict[str, Any]],
    region: str = "all",
    is_book_in_region: Optional[Callable[[str, str], bool]] = None,
    min_profit_pct: float = 0.1,
) -> List[Dict[str, Any]]:
    """Scan active events and quotes to identify guaranteed risk-free arbitrage opportunities."""
    opportunities = []

    for event in events:
        quotes = event.get("quotes", {})
        if not quotes or len(quotes) < 2:
            continue

        side_a_name = event.get("side_a", "Side A")
        side_b_name = event.get("side_b", "Side B")
        event_id = event.get("event_id", "")
        sport = event.get("sport", "")
        commence_time = event.get("commence_time", "")
        format_title = event.get("format_title", "")

        # Find best decimal odds for Side A and Side B within regional filter
        best_a_book = None
        best_a_odds = 0.0
        best_a_american = None

        best_b_book = None
        best_b_odds = 0.0
        best_b_american = None

        for book_name, quote in quotes.items():
            # Check regional filtering if provided
            if is_book_in_region and region != "all":
                if not is_book_in_region(book_name, region):
                    continue

            dec_a = float(quote.get("decimal_a") or 0.0)
            dec_b = float(quote.get("decimal_b") or 0.0)

            if dec_a > best_a_odds:
                best_a_odds = dec_a
                best_a_book = book_name
                best_a_american = quote.get("american_a")

            if dec_b > best_b_odds:
                best_b_odds = dec_b
                best_b_book = book_name
                best_b_american = quote.get("american_b")

        if not best_a_book or not best_b_book or best_a_odds <= 1.0 or best_b_odds <= 1.0:
            continue

        # In an arbitrage, best_a_book and best_b_book can be different books
        implied_sum = (1.0 / best_a_odds) + (1.0 / best_b_odds)

        # Arbitrage exists if implied_sum < 1.0
        if implied_sum < 1.0:
            profit_pct = round(((1.0 / implied_sum) - 1.0) * 100, 2)
            if profit_pct >= min_profit_pct:
                sample_stakes = calculate_arbitrage_stakes(1000.0, best_a_odds, best_b_odds)
                opportunities.append({
                    "event_id": event_id,
                    "sport": sport,
                    "format_title": format_title,
                    "event_name": f"{side_a_name} vs {side_b_name}",
                    "commence_time": commence_time,
                    "side_a": side_a_name,
                    "side_b": side_b_name,
                    "book_a": best_a_book,
                    "odds_a": best_a_odds,
                    "american_a": best_a_american,
                    "book_b": best_b_book,
                    "odds_b": best_b_odds,
                    "american_b": best_b_american,
                    "implied_sum": round(implied_sum, 4),
                    "profit_pct": profit_pct,
                    "stake_a_pct": round(((1.0 / best_a_odds) / implied_sum) * 100, 1),
                    "stake_b_pct": round(((1.0 / best_b_odds) / implied_sum) * 100, 1),
                    "sample_stakes": sample_stakes,
                })

    # Sort opportunities by highest guaranteed profit margin first
    opportunities.sort(key=lambda x: x["profit_pct"], reverse=True)
    return opportunities
