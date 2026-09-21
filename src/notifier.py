"""
Discord Webhook notification service for the Odds Anomaly Engine.
Provides zero-dependency webhook dispatching with rich embeds, cooldowns, and configuration persistence.
"""

import json
import time
import urllib.request
import urllib.error
from pathlib import Path
from typing import Dict, Any, Tuple, Optional
from .math_engine import calculate_kelly_stake

CONFIG_PATH = Path(__file__).resolve().parent.parent / "discord_config.json"

DEFAULT_SETTINGS = {
    "webhook_url": "",
    "enabled": False,
    "min_ev": 0.05,            # Alert only if EV >= 5%
    "bankroll": 1000.0,        # Default bankroll $1,000
    "kelly_multiplier": 0.25,  # Quarter Kelly
    "preferred_region": "all", # Default global region
}

# In-memory cooldown tracking: (event_id, selection, bookmaker) -> last_sent_timestamp
_cooldown_cache: Dict[str, float] = {}
COOLDOWN_SECONDS = 900.0  # 15 minutes


def load_settings() -> Dict[str, Any]:
    """Load settings from persistent JSON file."""
    if CONFIG_PATH.exists():
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                saved = json.load(f)
                res = DEFAULT_SETTINGS.copy()
                res.update(saved)
                return res
        except Exception:
            pass
    return DEFAULT_SETTINGS.copy()


def save_settings(new_settings: Dict[str, Any]) -> Dict[str, Any]:
    """Save settings to persistent JSON file."""
    curr = load_settings()
    curr.update(new_settings)
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(curr, f, indent=2)
    except Exception as e:
        print(f"Error saving discord_config.json: {e}")
    return curr


def _ev_to_color(ev_val: float) -> int:
    """Choose rich embed border color based on EV magnitude."""
    if ev_val >= 0.15:
        return 0xff0055  # Neon Magenta (Massive edge)
    elif ev_val >= 0.10:
        return 0xffbe0b  # Neon Yellow/Gold
    elif ev_val >= 0.05:
        return 0x00f59b  # Neon Green
    return 0x00d2ff      # Neon Cyan


def send_discord_test(webhook_url: str) -> Tuple[bool, str]:
    """Send a test embed to verify user's Discord webhook URL."""
    if not webhook_url or not webhook_url.startswith("https://discord.com/api/webhooks/"):
        return False, "Invalid Discord webhook URL. It must start with https://discord.com/api/webhooks/"

    embed = {
        "title": "⚡ EdgePulse Discord Integration Connected!",
        "description": "Your Discord webhook is configured and ready to receive real-time **+EV betting anomalies**.",
        "color": 0x00f59b,
        "fields": [
            {"name": "Status", "value": "🟢 Active & Monitoring", "inline": True},
            {"name": "Sharp Benchmark", "value": "Pinnacle Devigged", "inline": True},
            {"name": "Mode", "value": "Real-World Live Scans", "inline": True},
        ],
        "footer": {
            "text": "EdgePulse Odds Anomaly Engine • Automated Alert",
        },
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }

    payload = {
        "username": "EdgePulse Anomaly Engine",
        "avatar_url": "https://img.icons8.com/neon/96/bullish.png",
        "embeds": [embed],
    }

    try:
        req = urllib.request.Request(
            webhook_url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "User-Agent": "EdgePulseWebhook/1.0",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            if resp.status in (200, 204):
                return True, "Test alert sent successfully to Discord!"
            return False, f"Discord responded with HTTP status {resp.status}"
    except urllib.error.HTTPError as he:
        return False, f"Discord HTTP Error {he.code}: {he.reason}"
    except Exception as e:
        return False, f"Connection error: {str(e)}"


def send_discord_alert(alert_dict: dict, webhook_url: Optional[str] = None) -> bool:
    """
    Send an anomaly alert embed to Discord with Kelly stake recommendations.
    Respects minimum EV threshold and 15-minute deduplication cooldown.
    """
    settings = load_settings()
    url = webhook_url or settings.get("webhook_url", "")
    if not url or not settings.get("enabled", False):
        return False

    # Extract numerical EV
    ev_str = str(alert_dict.get("expected_value", "0%")).replace("%", "").replace("+", "").strip()
    try:
        ev_val = float(ev_str) / 100.0
    except ValueError:
        ev_val = 0.0

    min_ev = float(settings.get("min_ev", 0.05))
    if ev_val < min_ev:
        return False

    # Cooldown check
    dedup_key = f"{alert_dict.get('event_id')}:{alert_dict.get('selection')}:{alert_dict.get('target_book')}"
    now = time.time()
    if dedup_key in _cooldown_cache and (now - _cooldown_cache[dedup_key]) < COOLDOWN_SECONDS:
        return False
    _cooldown_cache[dedup_key] = now

    # Kelly stake calculation
    bankroll = float(settings.get("bankroll", 1000.0))
    kelly_mult = float(settings.get("kelly_multiplier", 0.25))
    soft_dec = float(alert_dict.get("soft_decimal", 2.0))
    sharp_prob_str = str(alert_dict.get("sharp_true_prob", "50%")).replace("%", "").strip()
    try:
        sharp_prob = float(sharp_prob_str) / 100.0
    except ValueError:
        sharp_prob = 0.50

    stake, stake_pct, exp_profit = calculate_kelly_stake(
        p_true=sharp_prob,
        decimal_odds=soft_dec,
        bankroll=bankroll,
        fraction_multiplier=kelly_mult,
    )

    color = _ev_to_color(ev_val)
    sport_name = str(alert_dict.get("sport", "Sports")).upper()
    book = str(alert_dict.get("target_book", "Retail")).upper()
    selection = alert_dict.get("selection", "Selection")
    odds_str = alert_dict.get("soft_american", "+100")
    delta_str = alert_dict.get("delta", "+0.0%")
    event_str = alert_dict.get("event_id", "").replace("_vs_", " vs ").replace("baseball:", "").replace("boxing:", "").replace("soccer_dnb:", "").replace("basketball_nba:", "")

    embed = {
        "title": f"🚨 +{round(ev_val * 100, 2)}% EV Alert: {selection} ({book})",
        "description": f"**Event:** `{event_str}`\n**Sport:** {sport_name} • **Sharp Reference:** Pinnacle",
        "color": color,
        "fields": [
            {
                "name": "🎯 Bet Action",
                "value": f"**{selection}** on **{book}** @ **`{odds_str}`** (Dec `{soft_dec}`)",
                "inline": False,
            },
            {
                "name": "💰 Recommended Stake",
                "value": f"**${stake:,.2f}** ({stake_pct}% of ${bankroll:,.0f})\nExpected Profit: **+${exp_profit:,.2f}**",
                "inline": True,
            },
            {
                "name": "📊 Edge & Probabilities",
                "value": f"Expected Value: **+{round(ev_val * 100, 2)}%**\nPinnacle True: **{sharp_prob_str}%**\nSoft Implied: `{alert_dict.get('soft_implied_prob', '')}`\nDiscrepancy (Δ): `{delta_str}`",
                "inline": True,
            },
        ],
        "footer": {
            "text": f"EdgePulse Odds Engine • Kelly {kelly_mult}x • Staked on ${bankroll:,.0f} Bankroll",
        },
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }

    payload = {
        "username": "EdgePulse Odds Anomaly Engine",
        "avatar_url": "https://img.icons8.com/neon/96/bullish.png",
        "embeds": [embed],
    }

    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "User-Agent": "EdgePulseWebhook/1.0",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            return resp.status in (200, 204)
    except Exception as e:
        print(f"Error sending Discord alert: {e}")
        return False
