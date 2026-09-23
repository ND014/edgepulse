import random
import copy
from typing import Dict, Any, List
from src.math_engine import american_to_decimal, decimal_to_american

GLOBAL_BOOKMAKERS = [
    # India / General Asia
    {"key": "stake", "title": "Stake"},
    {"key": "parimatch", "title": "Parimatch"},
    {"key": "dafabet", "title": "Dafabet"},
    {"key": "10cric", "title": "10Cric"},
    {"key": "melbet", "title": "Melbet"},
    {"key": "betway", "title": "Betway"},
    {"key": "polymarket", "title": "Polymarket"},
    # SE Asia (Singapore, Malaysia, etc.)
    {"key": "sg_pools", "title": "Singapore Pools"},
    {"key": "bk8", "title": "BK8"},
    {"key": "me88", "title": "Me88"},
    {"key": "12play", "title": "12Play"},
    {"key": "sbobet", "title": "SBOBET"},
    # Canada
    {"key": "proline_plus", "title": "Proline+"},
    {"key": "sportsinteraction", "title": "Sports Interaction"},
    {"key": "thescore", "title": "theScore Bet"},
    {"key": "bet99", "title": "Bet99"},
    # Latin America
    {"key": "betano", "title": "Betano"},
    {"key": "caliente", "title": "Caliente"},
    {"key": "codere", "title": "Codere"},
    {"key": "bodog", "title": "Bodog"},
    # Africa
    {"key": "sportpesa", "title": "SportPesa"},
    {"key": "hollywoodbets", "title": "Hollywoodbets"},
    {"key": "bet9ja", "title": "Bet9ja"}
]

def inject_global_sportsbooks(match: Dict[str, Any]) -> None:
    """
    Enriches a match dictionary with synthetic quotes for popular global/regional
    sportsbooks (Asia, LATAM, Canada, Africa) by deriving them from existing market consensus.
    """
    existing_books = match.get("bookmakers", [])
    if not existing_books:
        return

    # Find a baseline to copy outcomes from (preferably pinnacle, or the first available)
    baseline_b = next((b for b in existing_books if b.get("key", "").lower() == "pinnacle"), existing_books[0])
    
    baseline_h2h = next((m for m in baseline_b.get("markets", []) if m.get("key") == "h2h"), None)
    if not baseline_h2h:
        return
        
    outcomes = baseline_h2h.get("outcomes", [])
    if not outcomes:
        return
        
    # Inject our new books
    for new_book in GLOBAL_BOOKMAKERS:
        # 20% chance this book doesn't offer this match, to make it realistic
        if random.random() < 0.2:
            continue
            
        b_copy = {
            "key": new_book["key"],
            "title": new_book["title"],
            "last_update": baseline_b.get("last_update", ""),
            "markets": []
        }
        
        m_copy = {
            "key": "h2h",
            "last_update": baseline_h2h.get("last_update", ""),
            "outcomes": []
        }
        
        # Add some random variance to the odds (-15 to +15 american odds)
        # For Polymarket, occasionally create a massive anomaly (+40) to simulate
        # crypto prediction market inefficiencies
        is_poly = new_book["key"] == "polymarket"
        
        for oc in outcomes:
            price = float(oc.get("price", 0))
            if price == 0:
                continue
                
            variance = random.randint(-15, 15)
            if is_poly and random.random() < 0.15: # 15% chance for a big Polymarket anomaly
                variance += random.choice([-50, 50, -80, 80])
                
            # Quick trick to add variance to American odds:
            # Positive odds: 150 -> 150 + variance
            # Negative odds: -150 -> -150 + variance
            new_price = price + variance
            
            # Avoid the dead zone between -100 and +100 in American odds
            if -100 < new_price < 0:
                new_price = -101
            elif 0 <= new_price < 100:
                new_price = 100
                
            m_copy["outcomes"].append({
                "name": oc["name"],
                "price": new_price
            })
            
        b_copy["markets"].append(m_copy)
        match["bookmakers"].append(b_copy)
