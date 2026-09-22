"""
Entity resolution, participant alias matching, and 2-way market normalization.
"""

import re
from typing import Dict, Tuple
from .models import OddsQuote, NormalizedQuote, Sport, MarketType, OddsFormat
from .math_engine import (
    american_to_decimal,
    decimal_to_american,
    american_to_implied_prob,
    decimal_to_implied_prob,
)

# Common entity aliases across books
ENTITY_ALIASES: Dict[str, str] = {
    # UFC / MMA
    "alexander volkanovski": "Alex Volkanovski",
    "a. volkanovski": "Alex Volkanovski",
    "alex volkanovski": "Alex Volkanovski",
    "jon jones": "Jon Jones",
    "j. jones": "Jon Jones",
    "islam makhachev": "Islam Makhachev",
    "i. makhachev": "Islam Makhachev",
    "alex pereira": "Alex Pereira",
    "a. pereira": "Alex Pereira",
    "max holloway": "Max Holloway",
    "m. holloway": "Max Holloway",
    "arman tsarukyan": "Arman Tsarukyan",
    "a. tsarukyan": "Arman Tsarukyan",
    "mauricio ruffy": "Mauricio Ruffy",
    "m. ruffy": "Mauricio Ruffy",

    # Boxing
    "canelo alvarez": "Canelo Alvarez",
    "saul alvarez": "Canelo Alvarez",
    "saul canelo alvarez": "Canelo Alvarez",
    "canelo": "Canelo Alvarez",
    "terence crawford": "Terence Crawford",
    "t. crawford": "Terence Crawford",
    "crawford": "Terence Crawford",
    "tyson fury": "Tyson Fury",
    "t. fury": "Tyson Fury",
    "oleksandr usyk": "Oleksandr Usyk",
    "o. usyk": "Oleksandr Usyk",
    "anthony joshua": "Anthony Joshua",
    "a. joshua": "Anthony Joshua",
    "gervonta davis": "Gervonta Davis",
    "tank davis": "Gervonta Davis",

    # Baseball (MLB, NPB, KBO)
    "new york yankees": "New York Yankees",
    "ny yankees": "New York Yankees",
    "yankees": "New York Yankees",
    "boston red sox": "Boston Red Sox",
    "red sox": "Boston Red Sox",
    "los angeles dodgers": "Los Angeles Dodgers",
    "la dodgers": "Los Angeles Dodgers",
    "dodgers": "Los Angeles Dodgers",
    "san francisco giants": "San Francisco Giants",
    "sf giants": "San Francisco Giants",
    "giants": "San Francisco Giants",
    "houston astros": "Houston Astros",
    "astros": "Houston Astros",
    "atlanta braves": "Atlanta Braves",
    "braves": "Atlanta Braves",
    "philadelphia phillies": "Philadelphia Phillies",
    "phillies": "Philadelphia Phillies",
    "chicago cubs": "Chicago Cubs",
    "cubs": "Chicago Cubs",
    "yomiuri giants": "Yomiuri Giants",
    "hanshin tigers": "Hanshin Tigers",
    "kia tigers": "Kia Tigers",
    "lg twins": "LG Twins",

    # Tennis
    "carlos alcaraz": "Carlos Alcaraz",
    "c. alcaraz": "Carlos Alcaraz",
    "jannik sinner": "Jannik Sinner",
    "j. sinner": "Jannik Sinner",
    "novak djokovic": "Novak Djokovic",
    "n. djokovic": "Novak Djokovic",
    "daniil medvedev": "Daniil Medvedev",
    "d. medvedev": "Daniil Medvedev",
    "alexander zverev": "Alexander Zverev",
    "a. zverev": "Alexander Zverev",
    "iga swiatek": "Iga Swiatek",
    "i. swiatek": "Iga Swiatek",
    "aryna sabalenka": "Aryna Sabalenka",
    "a. sabalenka": "Aryna Sabalenka",
    "coco gauff": "Coco Gauff",
    "c. gauff": "Coco Gauff",

    # Basketball (NBA, EuroLeague, WNBA)
    "los angeles lakers": "LA Lakers",
    "l.a. lakers": "LA Lakers",
    "la lakers": "LA Lakers",
    "lakers": "LA Lakers",
    "golden state warriors": "Golden State Warriors",
    "warriors": "Golden State Warriors",
    "gsw": "Golden State Warriors",
    "boston celtics": "Boston Celtics",
    "celtics": "Boston Celtics",
    "bos": "Boston Celtics",
    "denver nuggets": "Denver Nuggets",
    "nuggets": "Denver Nuggets",
    "den": "Denver Nuggets",
    "real madrid baloncesto": "Real Madrid Basket",
    "fc barcelona basquet": "Barcelona Basket",
    "new york liberty": "New York Liberty",
    "las vegas aces": "Las Vegas Aces",

    # Cricket (T20 / CPL / ODI)
    "mumbai indians": "Mumbai Indians",
    "mi": "Mumbai Indians",
    "chennai super kings": "Chennai Super Kings",
    "csk": "Chennai Super Kings",
    "royal challengers bengaluru": "Royal Challengers Bengaluru",
    "royal challengers bangalore": "Royal Challengers Bengaluru",
    "rcb": "Royal Challengers Bengaluru",
    "kolkata knight riders": "Kolkata Knight Riders",
    "kkr": "Kolkata Knight Riders",
    "gujarat titans": "Gujarat Titans",
    "gt": "Gujarat Titans",
    "barbados royals": "Barbados Royals",
    "guyana amazon warriors": "Guyana Amazon Warriors",
    "trinbago knight riders": "Trinbago Knight Riders",
    "england": "England",
    "sri lanka": "Sri Lanka",
    "australia": "Australia",
    "india": "India",

    # Soccer (Draw No Bet)
    "manchester city": "Manchester City",
    "man city": "Manchester City",
    "arsenal": "Arsenal",
    "arsenal fc": "Arsenal",
    "real madrid": "Real Madrid",
    "real madrid cf": "Real Madrid",
    "barcelona": "Barcelona",
    "fc barcelona": "Barcelona",
    "liverpool": "Liverpool",
    "liverpool fc": "Liverpool",
    "bayern munich": "Bayern Munich",
    "fc bayern munchen": "Bayern Munich",
    "inter milan": "Inter Milan",
    "internazionale": "Inter Milan",
    "paris saint germain": "Paris Saint-Germain",
    "psg": "Paris Saint-Germain",
    "inter miami cf": "Inter Miami",
    "inter miami": "Inter Miami",
}


def clean_name(name: str) -> str:
    """Strip whitespace and punctuation for lookup."""
    return re.sub(r"[^\w\s\.]", "", name.strip().lower())


def resolve_entity(name: str) -> str:
    """Resolve raw bookmaker entity name to standard canonical string."""
    cleaned = clean_name(name)
    if cleaned in ENTITY_ALIASES:
        return ENTITY_ALIASES[cleaned]
    # Return Title Cased string if not explicitly in alias dictionary
    return name.strip()


def generate_canonical_event_id(sport: Sport, side_a: str, side_b: str, format_title: str = "") -> str:
    """Generate a deterministic, order-independent event identifier."""
    norm_a = resolve_entity(side_a)
    norm_b = resolve_entity(side_b)
    # Sort lexicographically to guarantee same ID regardless of home/away flipping
    sides = sorted([norm_a, norm_b])
    if format_title:
        fmt_slug = format_title.lower().replace(" ", "_").replace("/", "_").replace("-", "_")
        return f"{sport.value}:{fmt_slug}:{sides[0]}_vs_{sides[1]}"
    return f"{sport.value}:{sides[0]}_vs_{sides[1]}"


def normalize_quote(quote: OddsQuote) -> NormalizedQuote:
    """
    Validate market and convert odds into uniform decimal, American,
    and implied probability representations.
    """
    # 1. Resolve canonical names
    canonical_a = resolve_entity(quote.side_a)
    canonical_b = resolve_entity(quote.side_b)
    canonical_id = quote.event_id or generate_canonical_event_id(quote.sport, canonical_a, canonical_b, quote.format_title)

    # 2. Convert odds
    if quote.odds_format == OddsFormat.AMERICAN:
        am_a = int(round(quote.side_a_odds))
        am_b = int(round(quote.side_b_odds))
        dec_a = american_to_decimal(am_a)
        dec_b = american_to_decimal(am_b)
        p_raw_a = american_to_implied_prob(am_a)
        p_raw_b = american_to_implied_prob(am_b)
    elif quote.odds_format == OddsFormat.DECIMAL:
        dec_a = float(quote.side_a_odds)
        dec_b = float(quote.side_b_odds)
        am_a = decimal_to_american(dec_a)
        am_b = decimal_to_american(dec_b)
        p_raw_a = decimal_to_implied_prob(dec_a)
        p_raw_b = decimal_to_implied_prob(dec_b)
    else:
        raise ValueError(f"Unsupported odds format: {quote.odds_format}")

    overround = p_raw_a + p_raw_b

    return NormalizedQuote(
        event_id=canonical_id,
        sport=quote.sport,
        market_type=quote.market_type,
        bookmaker=quote.bookmaker.lower(),
        side_a=canonical_a,
        side_b=canonical_b,
        american_a=am_a,
        american_b=am_b,
        decimal_a=round(dec_a, 4),
        decimal_b=round(dec_b, 4),
        p_raw_a=round(p_raw_a, 5),
        p_raw_b=round(p_raw_b, 5),
        overround=round(overround, 5),
        timestamp=quote.timestamp,
        commence_time=quote.commence_time,
        format_title=quote.format_title,
    )
