#!/usr/bin/env python3
"""
EdgePulse Odds Anomaly Engine - Web Dashboard Server.
- Real-time multi-book market orderbook and sharp consensus engine.
- On-demand live scans for specific sports leagues.
- Instant +EV anomaly detection with Kelly staking and Discord alerts.
"""

import json
import os
import sqlite3
import threading
import time
import urllib.request
import urllib.error
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Dict, List, Optional, Any

from src.models import Sport, MarketType, OddsFormat, OddsQuote
from src.normalizer import normalize_quote
from src.orderbook import OrderBook
from src.detector import AnomalyDetector
from src.math_engine import calculate_kelly_stake
from src.notifier import load_settings, save_settings, send_discord_test, send_discord_alert
from src.arbitrage import find_arbitrage_opportunities, calculate_arbitrage_stakes
from src.telegram import send_telegram_alert, send_telegram_test
from src import db

ROOT_DIR = Path(__file__).resolve().parent
ENV_FILE = ROOT_DIR / ".env"
ODDS_API_KEY = os.environ.get("ODDS_API_KEY", "")
GOOGLE_CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
PORT = int(os.environ.get("PORT", 8080))
SERVER_START_TIME = time.time()

if ENV_FILE.exists():
    with open(ENV_FILE, "r") as f:
        for line in f:
            if line.strip() and not line.startswith("#") and "=" in line:
                k, v = line.strip().split("=", 1)
                k_clean = k.strip()
                v_clean = v.strip().strip('"').strip("'")
                if k_clean == "ODDS_API_KEY" and "ODDS_API_KEY" not in os.environ:
                    ODDS_API_KEY = v_clean
                elif k_clean == "GOOGLE_CLIENT_ID" and "GOOGLE_CLIENT_ID" not in os.environ:
                    GOOGLE_CLIENT_ID = v_clean
                elif k_clean == "GOOGLE_CLIENT_SECRET" and "GOOGLE_CLIENT_SECRET" not in os.environ:
                    GOOGLE_CLIENT_SECRET = v_clean
                elif k_clean == "PORT" and "PORT" not in os.environ:
                    try:
                        PORT = int(v_clean)
                    except ValueError:
                        pass

# Shared Application State
orderbook = OrderBook(sharp_bookmaker="pinnacle")
detector = AnomalyDetector(
    orderbook=orderbook,
    delta_threshold=0.01,  # 1.0%
    ev_threshold=0.01,     # +1.0% profit
    dedup_cooldown_sec=15.0,
)
detected_anomalies: List[dict] = []
max_edge_found: float = 0.0
quota_remaining = 437
quota_used = 63
state_lock = threading.Lock()
current_active_sport_name = "UFC / MMA"
current_active_sport_filter = "ufc"
current_active_sport_key = "mma_mixed_martial_arts"
CACHE_DIR = ROOT_DIR / "data_cache"
CACHE_DIR.mkdir(exist_ok=True)
CACHE_FILE = CACHE_DIR / "latest.json"
SPORT_SCAN_COOLDOWN_SECONDS = int(os.environ.get("SPORT_SCAN_COOLDOWN_SECONDS", 300))
SPORT_LAST_SCAN: Dict[str, float] = {}

SPORT_API_MAP = {
    # Baseball
    "baseball_mlb": ("baseball_mlb", "baseball_npb", Sport.BASEBALL, "Baseball (MLB)", "baseball", "Baseball", "Major League Baseball (USA)"),
    "baseball_npb": ("baseball_npb", None, Sport.BASEBALL, "Baseball (NPB)", "baseball", "Baseball", "Nippon Professional Baseball (Japan)"),
    "baseball_kbo": ("baseball_kbo", None, Sport.BASEBALL, "Baseball (KBO)", "baseball", "Baseball", "Korean Baseball Organization"),
    "baseball": ("baseball_mlb", "baseball_npb", Sport.BASEBALL, "Baseball (MLB)", "baseball", "Baseball", "Major League Baseball"),

    # Boxing
    "boxing_boxing": ("boxing_boxing", None, Sport.BOXING, "Boxing", "boxing", "Boxing", "World Championship & Pro Boxing"),
    "boxing": ("boxing_boxing", None, Sport.BOXING, "Boxing", "boxing", "Boxing", "World Championship & Pro Boxing"),

    # UFC / MMA
    "mma_mixed_martial_arts": ("mma_mixed_martial_arts", None, Sport.UFC, "UFC / MMA", "ufc", "MMA", "UFC Fight Night & Main Cards"),
    "ufc": ("mma_mixed_martial_arts", None, Sport.UFC, "UFC / MMA", "ufc", "MMA", "UFC Fight Night & Main Cards"),

    # Basketball
    "basketball_nba": ("basketball_nba", "basketball_wnba", Sport.BASKETBALL_NBA, "Basketball (NBA)", "basketball_nba", "Basketball", "NBA"),
    "basketball_wnba": ("basketball_wnba", None, Sport.BASKETBALL_NBA, "Basketball (WNBA)", "basketball_nba", "Basketball", "Women's NBA"),
    "basketball_euroleague": ("basketball_euroleague", None, Sport.BASKETBALL_NBA, "Basketball (EuroLeague)", "basketball_nba", "Basketball", "Turkish Airlines EuroLeague"),
    "basketball_nbl": ("basketball_nbl", None, Sport.BASKETBALL_NBA, "Basketball (NBL)", "basketball_nba", "Basketball", "National Basketball League (Australia)"),
    "basketball": ("basketball_nba", "basketball_wnba", Sport.BASKETBALL_NBA, "Basketball (NBA)", "basketball_nba", "Basketball", "NBA"),

    # Cricket (Active In-Season)
    "cricket_international_t20": ("cricket_international_t20", "cricket_caribbean_premier_league", Sport.CRICKET_T20, "Cricket (Intl T20)", "cricket_t20", "Cricket", "ICC International Twenty20"),
    "cricket_caribbean_premier_league": ("cricket_caribbean_premier_league", None, Sport.CRICKET_T20, "Cricket (CPL)", "cricket_t20", "Cricket", "Caribbean Premier League (West Indies)"),
    "cricket_odi": ("cricket_odi", None, Sport.CRICKET_T20, "Cricket (ODI)", "cricket_t20", "Cricket", "One Day Internationals"),
    "cricket_t20": ("cricket_international_t20", "cricket_caribbean_premier_league", Sport.CRICKET_T20, "Cricket (T20)", "cricket_t20", "Cricket", "International T20 & CPL"),
    "cricket": ("cricket_international_t20", "cricket_caribbean_premier_league", Sport.CRICKET_T20, "Cricket (T20)", "cricket_t20", "Cricket", "International T20"),

    # Cricket (Seasonal Leagues - Auto-ready when in season)
    "cricket_ipl": ("cricket_ipl", None, Sport.CRICKET_T20, "Cricket (IPL)", "cricket_t20", "Cricket", "Indian Premier League (Seasonal: Mar-May)"),
    "cricket_big_bash": ("cricket_big_bash", None, Sport.CRICKET_T20, "Cricket (BBL)", "cricket_t20", "Cricket", "Big Bash League (Seasonal: Dec-Feb)"),
    "cricket_psl": ("cricket_psl", None, Sport.CRICKET_T20, "Cricket (PSL)", "cricket_t20", "Cricket", "Pakistan Super League (Seasonal: Feb-Mar)"),
    "cricket_the_hundred": ("cricket_the_hundred", None, Sport.CRICKET_T20, "Cricket (The Hundred)", "cricket_t20", "Cricket", "The Hundred UK (Seasonal: Summer)"),
    "cricket_test_match": ("cricket_test_match", None, Sport.CRICKET_T20, "Cricket (Test)", "cricket_t20", "Cricket", "ICC International Test Matches"),

    # Soccer (Draw No Bet)
    "soccer_epl": ("soccer_epl", "soccer_uefa_champs_league", Sport.SOCCER_DNB, "Soccer (EPL)", "soccer_dnb", "Soccer", "English Premier League"),
    "soccer_uefa_champs_league": ("soccer_uefa_champs_league", "soccer_uefa_europa_league", Sport.SOCCER_DNB, "Soccer (UCL)", "soccer_dnb", "Soccer", "UEFA Champions League"),
    "soccer_uefa_europa_league": ("soccer_uefa_europa_league", None, Sport.SOCCER_DNB, "Soccer (Europa League)", "soccer_dnb", "Soccer", "UEFA Europa League"),
    "soccer_spain_la_liga": ("soccer_spain_la_liga", None, Sport.SOCCER_DNB, "Soccer (La Liga)", "soccer_dnb", "Soccer", "Spanish La Liga"),
    "soccer_germany_bundesliga": ("soccer_germany_bundesliga", None, Sport.SOCCER_DNB, "Soccer (Bundesliga)", "soccer_dnb", "Soccer", "German Bundesliga"),
    "soccer_italy_serie_a": ("soccer_italy_serie_a", None, Sport.SOCCER_DNB, "Soccer (Serie A)", "soccer_dnb", "Soccer", "Italian Serie A"),
    "soccer_france_ligue_one": ("soccer_france_ligue_one", None, Sport.SOCCER_DNB, "Soccer (Ligue 1)", "soccer_dnb", "Soccer", "French Ligue 1"),
    "soccer_usa_mls": ("soccer_usa_mls", None, Sport.SOCCER_DNB, "Soccer (MLS)", "soccer_dnb", "Soccer", "USA Major League Soccer"),
    "soccer_dnb": ("soccer_epl", "soccer_uefa_champs_league", Sport.SOCCER_DNB, "Soccer (EPL)", "soccer_dnb", "Soccer", "English Premier League"),
    "soccer": ("soccer_epl", "soccer_uefa_champs_league", Sport.SOCCER_DNB, "Soccer (EPL)", "soccer_dnb", "Soccer", "English Premier League"),

    # Tennis
    "tennis_atp": ("tennis_atp", "tennis_wta_guadalajara_open", Sport.TENNIS, "Tennis (ATP)", "tennis", "Tennis", "ATP Tour (Men's)"),
    "tennis_wta": ("tennis_wta_guadalajara_open", None, Sport.TENNIS, "Tennis (WTA)", "tennis", "Tennis", "WTA Tour (Women's)"),
    "tennis_wta_guadalajara_open": ("tennis_wta_guadalajara_open", None, Sport.TENNIS, "Tennis (WTA)", "tennis", "Tennis", "WTA Guadalajara Open"),
    "tennis": ("tennis_atp", "tennis_wta_guadalajara_open", Sport.TENNIS, "Tennis (ATP)", "tennis", "Tennis", "ATP Tour"),
}


def record_alert(alert, is_live=False):
    global max_edge_found
    settings = load_settings()
    bankroll = float(settings.get("bankroll", 1000.0))
    multiplier = float(settings.get("kelly_multiplier", 0.25))

    stake, stake_pct, exp_profit = calculate_kelly_stake(
        p_true=alert.sharp_true_prob,
        decimal_odds=alert.soft_decimal,
        bankroll=bankroll,
        fraction_multiplier=multiplier,
    )

    with state_lock:
        d = alert.to_dict()
        d["is_live"] = is_live
        d["kelly_stake"] = stake
        d["kelly_pct"] = stake_pct
        d["kelly_profit"] = exp_profit
        detected_anomalies.insert(0, d)
        if len(detected_anomalies) > 250:
            detected_anomalies.pop()
        if alert.expected_value > max_edge_found:
            max_edge_found = alert.expected_value

    if is_live:
        if settings.get("enabled", False):
            threading.Thread(target=send_discord_alert, args=(d,), daemon=True).start()
        tg_token = settings.get("telegram_token", "")
        tg_chat = settings.get("telegram_chat_id", "")
        tg_enabled = settings.get("telegram_enabled", False)
        if tg_enabled and tg_token and tg_chat:
            threading.Thread(target=send_telegram_alert, args=(tg_token, tg_chat, d), daemon=True).start()



def process_quote(raw_quote: OddsQuote, is_live=False):
    norm = normalize_quote(raw_quote)
    orderbook.update_quote(norm)
    alerts = detector.evaluate_quote(norm)
    for a in alerts:
        record_alert(a, is_live=is_live)


def clear_board_state():
    """Wipe current orderbook and anomalies so old sports vanish completely."""
    global detected_anomalies, max_edge_found
    with state_lock:
        orderbook._quotes.clear()
        orderbook._consensus.clear()
        orderbook.total_quotes_ingested = 0
        orderbook.total_consensus_updates = 0
        detector._seen_alerts.clear()
        detector.total_anomalies_detected = 0
        detected_anomalies.clear()
        max_edge_found = 0.0


def run_single_sport_scan(sport_key: str, clear_old: bool = True, force: bool = False):
    """
    Fetch live odds for exactly ONE sport league (strictly 1 API call).
    Applies per-sport cooldown so refreshing the same sport uses the fresh cache,
    while allowing users to freely scan different sports back-to-back.
    """
    global quota_remaining, quota_used, current_active_sport_name, current_active_sport_filter, current_active_sport_key

    if sport_key not in SPORT_API_MAP:
        sport_key = "cricket_t20"

    primary_key, fallback_key, sport_enum, display_name, filter_key, group_name, _ = SPORT_API_MAP[sport_key]
    current_active_sport_key = sport_key
    current_active_sport_name = display_name
    current_active_sport_filter = filter_key

    now = time.time()
    last_scanned = SPORT_LAST_SCAN.get(filter_key, 0)
    elapsed = now - last_scanned

    # 1. Per-Sport Cooldown: If this specific sport was scanned within the cooldown window, serve fresh cache
    if not force and elapsed < SPORT_SCAN_COOLDOWN_SECONDS:
        # If this sport is not currently loaded in memory or has 0 anomalies, load it from cache
        if current_active_sport_filter != filter_key or len(detected_anomalies) == 0:
            load_cached_odds(filter_key)
        remaining = int(SPORT_SCAN_COOLDOWN_SECONDS - elapsed)
        return {
            "status": "success",
            "cached": True,
            "cooldown_active": True,
            "cooldown_remaining": remaining,
            "sport": display_name,
            "league": primary_key,
            "sport_filter": filter_key,
            "quotes_fetched": len(detected_anomalies),
            "quota_remaining": quota_remaining,
            "quota_used": quota_used,
            "api_calls_used": 0,
            "message": f"Active orderbook served from real-time cache ({remaining}s refresh cooldown).",
        }

    # 2. Check if API key is present; if not, gracefully load from disk cache
    if not ODDS_API_KEY:
        load_cached_odds(filter_key)
        return {
            "status": "success",
            "cached": True,
            "fallback": True,
            "sport": display_name,
            "league": primary_key,
            "sport_filter": filter_key,
            "quotes_fetched": len(detected_anomalies),
            "quota_remaining": quota_remaining,
            "quota_used": quota_used,
            "api_calls_used": 0,
            "message": f"Loaded {display_name} orderbook from cache.",
        }

    # 3. Check if quota remaining is 0; if exhausted, gracefully load from disk cache
    if quota_remaining is not None and quota_remaining <= 0:
        load_cached_odds(filter_key)
        return {
            "status": "success",
            "cached": True,
            "quota_exhausted": True,
            "sport": display_name,
            "league": primary_key,
            "sport_filter": filter_key,
            "quotes_fetched": len(detected_anomalies),
            "quota_remaining": 0,
            "quota_used": quota_used,
            "api_calls_used": 0,
            "message": f"Active market board loaded from cache.",
        }

    if clear_old:
        clear_board_state()

    url = (
        f"https://api.the-odds-api.com/v4/sports/{primary_key}/odds/"
        f"?apiKey={ODDS_API_KEY}&regions=us,us2,uk,eu,au&markets=h2h&oddsFormat=american"
    )
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "EdgePulseEngine/1.0", "Accept": "application/json"},
    )

    total_fetched = 0
    league_used = primary_key
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status == 200:
                quota_rem = resp.headers.get("x-requests-remaining")
                quota_u = resp.headers.get("x-requests-used")
                if quota_rem is not None:
                    quota_remaining = int(quota_rem)
                if quota_u is not None:
                    quota_used = int(quota_u)

                data = json.loads(resp.read().decode("utf-8"))

                # If primary league has 0 matches and fallback exists, try fallback
                if len(data) == 0 and fallback_key:
                    fallback_url = (
                        f"https://api.the-odds-api.com/v4/sports/{fallback_key}/odds/"
                        f"?apiKey={ODDS_API_KEY}&regions=us,us2,uk,eu,au&markets=h2h&oddsFormat=american"
                    )
                    req_fb = urllib.request.Request(
                        fallback_url,
                        headers={"User-Agent": "EdgePulseEngine/1.0", "Accept": "application/json"},
                    )
                    with urllib.request.urlopen(req_fb, timeout=10) as resp_fb:
                        if resp_fb.status == 200:
                            data = json.loads(resp_fb.read().decode("utf-8"))
                            league_used = fallback_key

                # Save fetched data to local cache so restarts don't burn API quota
                try:
                    cache_payload = {
                        "sport_key": sport_key,
                        "league_used": league_used,
                        "display_name": display_name,
                        "filter_key": filter_key,
                        "sport_enum": sport_enum.value,
                        "quota_remaining": quota_remaining,
                        "quota_used": quota_used,
                        "data": data,
                        "cached_at": time.time(),
                    }
                    sport_cache_file = CACHE_DIR / f"cache_{filter_key}.json"
                    with open(sport_cache_file, "w", encoding="utf-8") as scf:
                        json.dump(cache_payload, scf)
                    with open(CACHE_FILE, "w", encoding="utf-8") as cf:
                        json.dump(cache_payload, cf)
                except Exception as ce:
                    print(f"Error writing cache: {ce}")

                # Record successful live scan timestamp for this specific sport
                SPORT_LAST_SCAN[filter_key] = time.time()

                for match in data:
                    commence_time = match.get("commence_time", "")
                    for b in match.get("bookmakers", []):
                        b_name = b.get("key", "").lower()
                        for m in b.get("markets", []):
                            if m.get("key") == "h2h":
                                outcomes = m.get("outcomes", [])
                                if len(outcomes) == 2:
                                    q = OddsQuote(
                                        event_id="",
                                        sport=sport_enum,
                                        market_type=MarketType.HEAD_TO_HEAD,
                                        bookmaker=b_name,
                                        side_a=outcomes[0]["name"],
                                        side_b=outcomes[1]["name"],
                                        side_a_odds=float(outcomes[0]["price"]),
                                        side_b_odds=float(outcomes[1]["price"]),
                                        odds_format=OddsFormat.AMERICAN,
                                        timestamp=time.time(),
                                        commence_time=commence_time,
                                    )
                                    process_quote(q, is_live=True)
                                    total_fetched += 1
                                elif len(outcomes) == 3 and sport_enum == Sport.SOCCER_DNB:
                                    # Convert 3-way regulation soccer into Draw No Bet (DNB)
                                    draw_outcome = None
                                    non_draw = []
                                    for oc in outcomes:
                                        if oc.get("name", "").strip().lower() in ("draw", "tie"):
                                             draw_outcome = oc
                                        else:
                                             non_draw.append(oc)
                                    if len(non_draw) == 2 and draw_outcome:
                                        try:
                                            from src.math_engine import american_to_decimal, decimal_to_american
                                            dec_draw = american_to_decimal(float(draw_outcome["price"]))
                                            if dec_draw > 1.01:
                                                dnb_factor = 1.0 - (1.0 / dec_draw)
                                                dec_a = american_to_decimal(float(non_draw[0]["price"])) * dnb_factor
                                                dec_b = american_to_decimal(float(non_draw[1]["price"])) * dnb_factor
                                                if dec_a > 1.01 and dec_b > 1.01:
                                                    q = OddsQuote(
                                                        event_id="",
                                                        sport=sport_enum,
                                                        market_type=MarketType.DRAW_NO_BET,
                                                        bookmaker=b_name,
                                                        side_a=non_draw[0]["name"],
                                                        side_b=non_draw[1]["name"],
                                                        side_a_odds=float(decimal_to_american(dec_a)),
                                                        side_b_odds=float(decimal_to_american(dec_b)),
                                                        odds_format=OddsFormat.AMERICAN,
                                                        timestamp=time.time(),
                                                        commence_time=commence_time,
                                                    )
                                                    process_quote(q, is_live=True)
                                                    total_fetched += 1
                                        except Exception:
                                            pass
    except Exception as e:
        print(f"Notice: Live feed error for {primary_key}: {e}. Serving cached orderbook.")
        load_cached_odds(filter_key)
        return {
            "status": "success",
            "cached": True,
            "fallback": True,
            "sport": display_name,
            "league": league_used,
            "sport_filter": filter_key,
            "quotes_fetched": len(detected_anomalies),
            "quota_remaining": quota_remaining,
            "quota_used": quota_used,
            "api_calls_used": 0,
            "message": f"Loaded {display_name} orderbook from cache.",
        }

    return {
        "status": "success",
        "sport": display_name,
        "league": league_used,
        "sport_filter": filter_key,
        "quotes_fetched": total_fetched,
        "quota_remaining": quota_remaining,
        "quota_used": quota_used,
        "api_calls_used": 1,
    }


def get_cached_sports() -> list:
    """Return list of filter_keys that currently have cached data on disk."""
    cached = []
    if CACHE_DIR.exists():
        for f in CACHE_DIR.glob("cache_*.json"):
            key = f.stem.replace("cache_", "")
            cached.append(key)
    return cached


def load_cached_odds(target_filter="ufc"):
    """Load real live bookmaker data from local cache if present."""
    global quota_remaining, quota_used, current_active_sport_name, current_active_sport_filter, current_active_sport_key

    alias_map = {
        "basketball": "basketball_nba",
        "cricket": "cricket_t20",
        "soccer": "soccer_dnb",
        "mma": "ufc",
        "mma_mixed_martial_arts": "ufc",
    }
    normalized = alias_map.get(target_filter, target_filter)
    target_file = CACHE_DIR / f"cache_{normalized}.json"
    if not target_file.exists():
        target_file = CACHE_DIR / f"cache_{target_filter}.json"
    if not target_file.exists():
        if CACHE_FILE.exists():
            target_file = CACHE_FILE
        else:
            old_cache = ROOT_DIR / "cache_live_odds.json"
            if old_cache.exists():
                target_file = old_cache
            else:
                return False
    try:
        with open(target_file, "r", encoding="utf-8") as cf:
            payload = json.load(cf)
        data = payload.get("data", [])
        if not data:
            return False

        clear_board_state()
        current_active_sport_key = payload.get("sport_key", "mma_mixed_martial_arts")
        current_active_sport_name = payload.get("display_name", "UFC / MMA")
        current_active_sport_filter = payload.get("filter_key", "ufc")
        quota_remaining = payload.get("quota_remaining", quota_remaining)
        quota_used = payload.get("quota_used", quota_used)
        sport_enum_val = payload.get("sport_enum", "ufc")
        sport_enum = Sport(sport_enum_val)

        for match in data:
            commence_time = match.get("commence_time", "")
            for b in match.get("bookmakers", []):
                b_name = b.get("key", "").lower()
                for m in b.get("markets", []):
                    if m.get("key") == "h2h":
                        outcomes = m.get("outcomes", [])
                        if len(outcomes) == 2:
                            q = OddsQuote(
                                event_id="",
                                sport=sport_enum,
                                market_type=MarketType.HEAD_TO_HEAD,
                                bookmaker=b_name,
                                side_a=outcomes[0]["name"],
                                side_b=outcomes[1]["name"],
                                side_a_odds=float(outcomes[0]["price"]),
                                side_b_odds=float(outcomes[1]["price"]),
                                odds_format=OddsFormat.AMERICAN,
                                timestamp=time.time(),
                                commence_time=commence_time,
                            )
                            process_quote(q, is_live=True)
                        elif len(outcomes) == 3 and sport_enum == Sport.SOCCER_DNB:
                            # Convert 3-way regulation soccer into Draw No Bet (DNB)
                            draw_outcome = None
                            non_draw = []
                            for oc in outcomes:
                                if oc.get("name", "").strip().lower() in ("draw", "tie"):
                                    draw_outcome = oc
                                else:
                                    non_draw.append(oc)
                            if len(non_draw) == 2 and draw_outcome:
                                try:
                                    from src.math_engine import american_to_decimal, decimal_to_american
                                    dec_draw = american_to_decimal(float(draw_outcome["price"]))
                                    if dec_draw > 1.01:
                                        dnb_factor = 1.0 - (1.0 / dec_draw)
                                        dec_a = american_to_decimal(float(non_draw[0]["price"])) * dnb_factor
                                        dec_b = american_to_decimal(float(non_draw[1]["price"])) * dnb_factor
                                        if dec_a > 1.01 and dec_b > 1.01:
                                            q = OddsQuote(
                                                event_id="",
                                                sport=sport_enum,
                                                market_type=MarketType.DRAW_NO_BET,
                                                bookmaker=b_name,
                                                side_a=non_draw[0]["name"],
                                                side_b=non_draw[1]["name"],
                                                side_a_odds=float(decimal_to_american(dec_a)),
                                                side_b_odds=float(decimal_to_american(dec_b)),
                                                odds_format=OddsFormat.AMERICAN,
                                                timestamp=time.time(),
                                                commence_time=commence_time,
                                            )
                                            process_quote(q, is_live=True)
                                except Exception:
                                    pass
        print(f"Loaded {len(data)} real events from live cache for {current_active_sport_name}.")
        return True
    except Exception as e:
        print(f"Error loading live cache: {e}")
        return False


def get_session_token_from_request(handler: BaseHTTPRequestHandler) -> Optional[str]:
    """Extract session token from Authorization header or Cookie."""
    auth_header = handler.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        return auth_header[7:].strip()
    cookie_header = handler.headers.get("Cookie", "")
    if cookie_header:
        for part in cookie_header.split(";"):
            if "=" in part:
                k, v = part.strip().split("=", 1)
                if k == "session_token":
                    return v.strip()
    return None


def get_current_user_from_request(handler: BaseHTTPRequestHandler) -> Optional[Dict[str, Any]]:
    """Retrieve logged in user from request credentials."""
    token = get_session_token_from_request(handler)
    if token:
        return db.get_user_by_session(token)
    return None


def send_json_response(
    handler: BaseHTTPRequestHandler,
    data: Any,
    status: int = 200,
    session_cookie: Optional[str] = None,
    remember_me: bool = False,
    clear_cookie: bool = False,
):
    """Send serialized JSON response with optional session cookie headers."""
    resp_bytes = json.dumps(data).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(resp_bytes)))
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.send_header("X-Frame-Options", "SAMEORIGIN")
    handler.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
    if session_cookie:
        if remember_me:
            handler.send_header(
                "Set-Cookie",
                f"session_token={session_cookie}; Path=/; HttpOnly; SameSite=Lax; Max-Age={30 * 86400}",
            )
        else:
            handler.send_header(
                "Set-Cookie",
                f"session_token={session_cookie}; Path=/; HttpOnly; SameSite=Lax",
            )
    elif clear_cookie:
        handler.send_header(
            "Set-Cookie",
            "session_token=; Path=/; HttpOnly; SameSite=Lax; Max-Age=0",
        )
    handler.end_headers()
    handler.wfile.write(resp_bytes)


FAVICON_SVG = b"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32" fill="none">
  <rect width="32" height="32" rx="8" fill="#0B0F19"/>
  <rect x="1" y="1" width="30" height="30" rx="7" stroke="#202D4A" stroke-width="1.5"/>
  <path d="M4 16h5l3-7 4 14 3-10 3 5h6" stroke="#00D2FF" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"/>
  <circle cx="21" cy="13" r="2" fill="#00F59B"/>
</svg>"""


class DashboardHandler(BaseHTTPRequestHandler):
    """HTTP Request handler serving static files and API endpoints."""

    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()

    def do_GET(self):
        if self.path == "/" or self.path == "/index.html" or self.path.startswith("/dashboard") or self.path.startswith("/login"):
            html_path = ROOT_DIR / "static" / "index.html"
            if html_path.exists():
                content = html_path.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(content)))
                self.send_header("X-Content-Type-Options", "nosniff")
                self.send_header("X-Frame-Options", "SAMEORIGIN")
                self.send_header("Referrer-Policy", "strict-origin-when-cross-origin")
                self.end_headers()
                self.wfile.write(content)
            else:
                self.send_error(404, "index.html not found")
            return

        elif self.path == "/favicon.ico":
            self.send_response(200)
            self.send_header("Content-Type", "image/svg+xml")
            self.send_header("Content-Length", str(len(FAVICON_SVG)))
            self.send_header("Cache-Control", "public, max-age=86400")
            self.end_headers()
            self.wfile.write(FAVICON_SVG)
            return

        elif self.path == "/api/health" or self.path == "/health":
            uptime = round(time.time() - SERVER_START_TIME, 1)
            active_events = len(orderbook.get_all_active_event_ids())
            active_anomalies = detector.total_anomalies_detected
            send_json_response(self, {
                "status": "healthy",
                "service": "EdgePulse Odds Anomaly Engine",
                "version": "2.4.0",
                "uptime_seconds": uptime,
                "timestamp": int(time.time()),
                "metrics": {
                    "events_monitored": active_events,
                    "active_anomalies": active_anomalies,
                    "requests_remaining": quota_remaining,
                    "current_sport": current_active_sport_name
                }
            })
            return

        elif self.path == "/api/auth/me":
            user = get_current_user_from_request(self)
            if user:
                send_json_response(self, {"status": "authenticated", "user": user})
            else:
                send_json_response(self, {"status": "unauthenticated", "user": None})
            return

        elif self.path == "/api/user/profile":
            user = get_current_user_from_request(self)
            if user:
                send_json_response(self, {"status": "success", "user": user})
            else:
                send_json_response(self, {"status": "error", "message": "Authentication required."}, 401)
            return

        elif self.path == "/api/auth/config":
            send_json_response(self, {"google_client_id": GOOGLE_CLIENT_ID})
            return

        elif self.path == "/api/state":
            user = get_current_user_from_request(self)
            with state_lock:
                events_list = []
                for eid in orderbook.get_all_active_event_ids():
                    quotes = orderbook.get_quotes(eid)
                    consensus = orderbook.get_consensus(eid)
                    if quotes:
                        first_q = next(iter(quotes.values()))
                        c_data = None
                        if consensus:
                            c_data = {
                                "sharp_bookmaker": consensus.sharp_bookmaker,
                                "p_true_a": consensus.p_true_a,
                                "p_true_b": consensus.p_true_b,
                                "fair_decimal_a": consensus.fair_decimal_a,
                                "fair_decimal_b": consensus.fair_decimal_b,
                            }
                        events_list.append({
                            "event_id": eid,
                            "sport": first_q.sport.value,
                            "side_a": first_q.side_a,
                            "side_b": first_q.side_b,
                            "commence_time": first_q.commence_time,
                            "consensus": c_data,
                            "quotes": {
                                b: {
                                    "side_a": q.side_a,
                                    "side_b": q.side_b,
                                    "american_a": q.american_a,
                                    "american_b": q.american_b,
                                    "decimal_a": q.decimal_a,
                                    "decimal_b": q.decimal_b,
                                }
                                for b, q in quotes.items()
                            }
                        })

                # Sort events in descending order of number of sportsbook entries (most famous/covered first)
                events_list.sort(key=lambda x: len(x.get("quotes", {})), reverse=True)

                active_settings = load_settings()
                if user:
                    active_settings = {
                        "bankroll": user.get("bankroll", 1000.0),
                        "kelly_multiplier": user.get("kelly_multiplier", 0.25),
                        "webhook_url": user.get("discord_webhook", ""),
                        "enabled": bool(user.get("discord_enabled", 0)),
                        "min_ev": user.get("min_ev", 0.01),
                        "preferred_region": user.get("preferred_region", "all"),
                        "telegram_token": user.get("telegram_token", ""),
                        "telegram_chat_id": user.get("telegram_chat_id", ""),
                        "telegram_enabled": bool(user.get("telegram_enabled", 0)),
                    }

                arbitrages = find_arbitrage_opportunities(events_list)

                payload = {
                    "user": user,
                    "quota_remaining": quota_remaining,
                    "quota_used": quota_used,
                    "total_anomalies": detector.total_anomalies_detected,
                    "total_consensus": orderbook.total_consensus_updates,
                    "total_quotes": orderbook.total_quotes_ingested,
                    "max_edge": max_edge_found,
                    "min_ev_threshold": detector.ev_threshold,
                    "active_sport_name": current_active_sport_name,
                    "active_sport_filter": current_active_sport_filter,
                    "active_sport_key": current_active_sport_key,
                    "cached_sports": get_cached_sports(),
                    "settings": active_settings,
                    "anomalies": detected_anomalies[:150],
                    "arbitrages": arbitrages[:100],
                    "events": events_list[:120],
                }

            send_json_response(self, payload)
            return

        elif self.path == "/api/settings":
            user = get_current_user_from_request(self)
            if user:
                user_settings = {
                    "bankroll": user.get("bankroll", 1000.0),
                    "kelly_multiplier": user.get("kelly_multiplier", 0.25),
                    "webhook_url": user.get("discord_webhook", ""),
                    "enabled": bool(user.get("discord_enabled", 0)),
                    "min_ev": user.get("min_ev", 0.01),
                    "preferred_region": user.get("preferred_region", "all"),
                    "telegram_token": user.get("telegram_token", ""),
                    "telegram_chat_id": user.get("telegram_chat_id", ""),
                    "telegram_enabled": bool(user.get("telegram_enabled", 0)),
                }
                send_json_response(self, {"status": "success", "settings": user_settings})
            else:
                send_json_response(self, {"status": "success", "settings": load_settings()})
            return

        elif self.path.startswith("/api/bets"):
            user = get_current_user_from_request(self)
            if not user:
                send_json_response(self, {"status": "error", "message": "Authentication required."}, 401)
                return
            status_param = None
            if "?" in self.path:
                query = self.path.split("?", 1)[1]
                for p in query.split("&"):
                    if p.startswith("status="):
                        status_param = p.split("=", 1)[1]
            bets = db.get_user_bets(user["id"], status=status_param)
            stats = db.get_bet_performance_stats(user["id"])
            send_json_response(self, {"status": "success", "bets": bets, "stats": stats})
            return

        elif self.path == "/api/leagues":
            grouped = {}
            for key, (primary_key, fallback, sport_enum, display_name, filter_key, group_name, desc) in SPORT_API_MAP.items():
                if key in ("baseball", "boxing", "ufc", "basketball", "cricket", "cricket_t20", "soccer", "soccer_dnb", "tennis", "tennis_wta"):
                    continue
                if group_name not in grouped:
                    grouped[group_name] = []
                grouped[group_name].append({
                    "key": key,
                    "api_key": primary_key,
                    "title": display_name,
                    "desc": desc,
                    "filter": filter_key,
                    "sport": sport_enum.value,
                })
            send_json_response(self, grouped)
            return

        self.send_error(404, "Route not found")

    def do_POST(self):
        global current_active_sport_name, current_active_sport_filter, current_active_sport_key

        if self.path == "/api/auth/signup":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8")
            try:
                data = json.loads(body)
                email = data.get("email", "").strip()
                password = data.get("password", "")
                name = data.get("name", "").strip()
                remember_me = bool(data.get("remember_me", False))
                if not email or "@" not in email:
                    send_json_response(self, {"status": "error", "message": "A valid email address is required."}, 400)
                    return
                if not password or len(password) < 6:
                    send_json_response(self, {"status": "error", "message": "Password must be at least 6 characters."}, 400)
                    return
                user = db.create_user(email=email, password=password, name=name)
                token = db.create_session(user["id"], remember_me=remember_me)
                send_json_response(self, {"status": "success", "user": user, "token": token, "remember_me": remember_me}, 200, session_cookie=token, remember_me=remember_me)
            except sqlite3.IntegrityError:
                send_json_response(self, {"status": "error", "message": "An account with this email already exists. Please sign in."}, 400)
            except ValueError as ve:
                send_json_response(self, {"status": "error", "message": str(ve)}, 400)
            except Exception as e:
                send_json_response(self, {"status": "error", "message": str(e)}, 400)
            return

        elif self.path == "/api/auth/login":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8")
            try:
                data = json.loads(body)
                email = data.get("email", "").strip()
                password = data.get("password", "")
                remember_me = bool(data.get("remember_me", False))
                user = db.authenticate_user(email, password)
                if not user:
                    send_json_response(self, {"status": "error", "message": "Invalid email or password."}, 401)
                    return
                token = db.create_session(user["id"], remember_me=remember_me)
                safe_user = db.get_user_by_id(user["id"])
                if safe_user:
                    safe_user["session_remember_me"] = remember_me
                send_json_response(self, {"status": "success", "user": safe_user, "token": token, "remember_me": remember_me}, 200, session_cookie=token, remember_me=remember_me)
            except ValueError as ve:
                send_json_response(self, {"status": "error", "message": str(ve)}, 400)
            except Exception as e:
                send_json_response(self, {"status": "error", "message": str(e)}, 400)
            return

        elif self.path == "/api/auth/google":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8")
            try:
                data = json.loads(body)
                credential = data.get("credential", "")
                remember_me = bool(data.get("remember_me", False))
                sub = None
                email = None
                name = None
                picture = None

                # Demo / Local Testing fallback
                if credential == "demo_google_token" or not credential:
                    sub = f"google_demo_{int(time.time() * 1000)}"
                    email = data.get("email", f"demo.google.user{int(time.time()) % 1000}@gmail.com")
                    name = data.get("name", "Demo Google Bettor")
                    picture = "https://lh3.googleusercontent.com/a/default-user=s96-c"
                else:
                    # Real verification with Google OAuth2 public tokeninfo endpoint
                    verify_url = f"https://oauth2.googleapis.com/tokeninfo?id_token={credential}"
                    req = urllib.request.Request(verify_url, headers={"User-Agent": "EdgePulse/1.0"})
                    with urllib.request.urlopen(req, timeout=5) as g_resp:
                        if g_resp.status == 200:
                            g_data = json.loads(g_resp.read().decode("utf-8"))
                            sub = g_data.get("sub")
                            email = g_data.get("email")
                            name = g_data.get("name")
                            picture = g_data.get("picture")
                        else:
                            send_json_response(self, {"status": "error", "message": "Failed to verify Google token with Google servers."}, 401)
                            return

                if not sub or not email:
                    send_json_response(self, {"status": "error", "message": "Incomplete Google profile received."}, 400)
                    return

                user = db.upsert_google_user(sub, email, name, picture)
                token = db.create_session(user["id"], remember_me=remember_me)
                if user:
                    user["session_remember_me"] = remember_me
                send_json_response(self, {"status": "success", "user": user, "token": token, "remember_me": remember_me}, 200, session_cookie=token, remember_me=remember_me)
            except ValueError as ve:
                send_json_response(self, {"status": "error", "message": str(ve)}, 400)
            except Exception as e:
                send_json_response(self, {"status": "error", "message": f"Google auth error: {str(e)}"}, 400)
            return

        elif self.path == "/api/auth/guest":
            content_length = int(self.headers.get("Content-Length", 0))
            remember_me = False
            if content_length > 0:
                try:
                    body = self.rfile.read(content_length).decode("utf-8")
                    data = json.loads(body)
                    remember_me = bool(data.get("remember_me", False))
                except Exception:
                    pass
            try:
                user = db.create_guest_user()
                token = db.create_session(user["id"], remember_me=remember_me)
                if user:
                    user["session_remember_me"] = remember_me
                send_json_response(self, {"status": "success", "user": user, "token": token, "remember_me": remember_me}, 200, session_cookie=token, remember_me=remember_me)
            except Exception as e:
                send_json_response(self, {"status": "error", "message": str(e)}, 400)
            return

        elif self.path == "/api/auth/logout":
            token = get_session_token_from_request(self)
            if token:
                db.delete_session(token)
            send_json_response(self, {"status": "success"}, 200, clear_cookie=True)
            return

        elif self.path.startswith("/api/scan_live"):
            sport_key = "cricket_t20"
            clear_old = True
            if "?" in self.path:
                query = self.path.split("?", 1)[1]
                for param in query.split("&"):
                    if param.startswith("sport="):
                        sport_key = param.split("=", 1)[1]
                    if param.startswith("clear="):
                        clear_old = param.split("=", 1)[1].lower() == "true"

            result = run_single_sport_scan(sport_key, clear_old=clear_old)
            send_json_response(self, result)
            return

        elif self.path.startswith("/api/load_cached"):
            target_sport = "ufc"
            if "?" in self.path:
                query = self.path.split("?", 1)[1]
                for param in query.split("&"):
                    if param.startswith("sport="):
                        target_sport = param.split("=", 1)[1]
            success = load_cached_odds(target_sport)
            send_json_response(self, {
                "status": "success" if success else "error",
                "loaded": success,
                "sport": current_active_sport_name,
                "sport_key": current_active_sport_key,
                "filter_key": current_active_sport_filter
            })
            return

        elif self.path == "/api/user/profile":
            user = get_current_user_from_request(self)
            if not user:
                send_json_response(self, {"status": "error", "message": "Authentication required."}, 401)
                return
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8")
            try:
                data = json.loads(body)
                name = data.get("name")
                avatar_url = data.get("avatar_url")
                current_password = data.get("current_password")
                new_password = data.get("new_password")

                # Update identity and credentials (email is strictly immutable)
                updated_user = db.update_user_profile(
                    user_id=user["id"],
                    name=name,
                    avatar_url=avatar_url,
                    current_password=current_password,
                    new_password=new_password,
                )

                # Update staking, region, and alert preferences if passed
                settings_keys = {"bankroll", "kelly_multiplier", "discord_webhook", "webhook_url", "discord_enabled", "enabled", "min_ev", "preferred_region", "telegram_token", "telegram_chat_id", "telegram_enabled"}
                if any(k in data for k in settings_keys):
                    updated_user = db.update_user_settings(user["id"], data)
                    user_settings = {
                        "bankroll": updated_user["bankroll"],
                        "kelly_multiplier": updated_user["kelly_multiplier"],
                        "webhook_url": updated_user["discord_webhook"],
                        "enabled": bool(updated_user["discord_enabled"]),
                        "min_ev": updated_user["min_ev"],
                        "preferred_region": updated_user.get("preferred_region", "all"),
                        "telegram_token": updated_user.get("telegram_token", ""),
                        "telegram_chat_id": updated_user.get("telegram_chat_id", ""),
                        "telegram_enabled": bool(updated_user.get("telegram_enabled", 0)),
                    }
                    save_settings(user_settings)

                send_json_response(self, {
                    "status": "success",
                    "user": updated_user,
                    "message": "Profile updated successfully.",
                })
            except ValueError as ve:
                send_json_response(self, {"status": "error", "message": str(ve)}, 400)
            except Exception as e:
                send_json_response(self, {"status": "error", "message": str(e)}, 400)
            return

        elif self.path == "/api/settings":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8")
            try:
                data = json.loads(body)
                user = get_current_user_from_request(self)
                if user:
                    updated_user = db.update_user_settings(user["id"], data)
                    user_settings = {
                        "bankroll": updated_user["bankroll"],
                        "kelly_multiplier": updated_user["kelly_multiplier"],
                        "webhook_url": updated_user["discord_webhook"],
                        "enabled": bool(updated_user["discord_enabled"]),
                        "min_ev": updated_user["min_ev"],
                        "preferred_region": updated_user.get("preferred_region", "all"),
                        "telegram_token": updated_user.get("telegram_token", ""),
                        "telegram_chat_id": updated_user.get("telegram_chat_id", ""),
                        "telegram_enabled": bool(updated_user.get("telegram_enabled", 0)),
                    }
                    save_settings(user_settings)
                    send_json_response(self, {"status": "success", "settings": user_settings})
                else:
                    updated = save_settings(data)
                    send_json_response(self, {"status": "success", "settings": updated})
            except Exception as e:
                send_json_response(self, {"status": "error", "message": str(e)}, 400)
            return

        elif self.path == "/api/test_discord":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8")
            try:
                data = json.loads(body)
                webhook_url = data.get("webhook_url", "")
                ok, msg = send_discord_test(webhook_url)
                send_json_response(self, {"status": "success" if ok else "error", "message": msg}, 200 if ok else 400)
            except Exception as e:
                send_json_response(self, {"status": "error", "message": str(e)}, 400)
            return

        elif self.path == "/api/test_telegram":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8")
            try:
                data = json.loads(body)
                bot_token = data.get("bot_token", "")
                chat_id = data.get("chat_id", "")
                ok, msg = send_telegram_test(bot_token, chat_id)
                send_json_response(self, {"status": "success" if ok else "error", "message": msg}, 200 if ok else 400)
            except Exception as e:
                send_json_response(self, {"status": "error", "message": str(e)}, 400)
            return

        elif self.path == "/api/bets/log":
            user = get_current_user_from_request(self)
            if not user:
                send_json_response(self, {"status": "error", "message": "Authentication required."}, 401)
                return
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8")
            try:
                data = json.loads(body)
                fair_odds_val = None
                if data.get("fair_odds") is not None and data.get("fair_odds") != "":
                    try:
                        fair_odds_val = float(data["fair_odds"])
                    except:
                        fair_odds_val = None

                edge_pct_val = None
                edge_input = data.get("edge_pct") if data.get("edge_pct") is not None else data.get("expected_value")
                if edge_input is not None and edge_input != "":
                    try:
                        if isinstance(edge_input, str):
                            edge_pct_val = float(edge_input.replace("+", "").replace("%", "").replace("EV", "").strip())
                        else:
                            edge_pct_val = float(edge_input)
                    except:
                        edge_pct_val = None

                odds_val = 1.0
                if data.get("odds") is not None and data.get("odds") != "":
                    odds_val = float(data["odds"])
                elif data.get("odds_decimal") is not None and data.get("odds_decimal") != "":
                    odds_val = float(data["odds_decimal"])

                event_name_val = str(data.get("event_name") or data.get("matchup") or "")
                sportsbook_val = str(data.get("sportsbook") or data.get("bookmaker") or "")

                bet = db.log_bet(
                    user_id=user["id"],
                    event_id=str(data.get("event_id", "")),
                    sport=str(data.get("sport", "")),
                    event_name=event_name_val,
                    selection=str(data.get("selection", "")),
                    sportsbook=sportsbook_val,
                    odds=odds_val,
                    stake=float(data.get("stake", 10.0)),
                    fair_odds=fair_odds_val,
                    edge_pct=edge_pct_val,
                    notes=str(data.get("notes", "")),
                )
                stats = db.get_bet_performance_stats(user["id"])
                send_json_response(self, {"status": "success", "bet": bet, "stats": stats, "message": "Bet tracked successfully."})
            except Exception as e:
                send_json_response(self, {"status": "error", "message": str(e)}, 400)
            return

        elif self.path == "/api/bets/settle":
            user = get_current_user_from_request(self)
            if not user:
                send_json_response(self, {"status": "error", "message": "Authentication required."}, 401)
                return
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8")
            try:
                data = json.loads(body)
                bet_id = int(data.get("bet_id", 0))
                new_status = str(data.get("status", ""))
                settled = db.settle_bet(bet_id, user["id"], new_status)
                stats = db.get_bet_performance_stats(user["id"])
                send_json_response(self, {"status": "success", "bet": settled, "stats": stats})
            except Exception as e:
                send_json_response(self, {"status": "error", "message": str(e)}, 400)
            return

        elif self.path == "/api/bets/delete":
            user = get_current_user_from_request(self)
            if not user:
                send_json_response(self, {"status": "error", "message": "Authentication required."}, 401)
                return
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode("utf-8")
            try:
                data = json.loads(body)
                bet_id = int(data.get("bet_id", 0))
                db.delete_bet(bet_id, user["id"])
                stats = db.get_bet_performance_stats(user["id"])
                send_json_response(self, {"status": "success", "stats": stats})
            except Exception as e:
                send_json_response(self, {"status": "error", "message": str(e)}, 400)
            return

        elif self.path == "/api/clear":
            clear_board_state()
            send_json_response(self, {"status": "cleared"})
            return

        self.send_error(404, "Route not found")

    def log_message(self, format, *args):
        pass


def main():
    print(f"Starting EdgePulse Odds Anomaly Web Server on http://localhost:{PORT}")
    
    # Load live cached data on startup if present
    loaded = load_cached_odds()
    if loaded:
        print(f"Live market board initialized with real data from cache.")
    else:
        print(f"No cache found. Awaiting live scan.")

    server = ThreadingHTTPServer(("0.0.0.0", PORT), DashboardHandler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down server...")
        server.server_close()


if __name__ == "__main__":
    main()
