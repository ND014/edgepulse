"""
EdgePulse Telegram Bot Dispatcher Module
Sends real-time high +EV anomalies and surebets to Telegram channels and direct chats.
"""

import json
import urllib.error
import urllib.request
from typing import Any, Dict, Tuple


def send_telegram_alert(
    bot_token: str,
    chat_id: str,
    alert: Dict[str, Any],
) -> bool:
    """Post an EdgePulse anomaly alert to a Telegram channel or chat."""
    if not bot_token or not chat_id:
        return False

    token_clean = bot_token.strip()
    chat_clean = chat_id.strip()

    edge = alert.get("expected_value", 0.0)
    edge_pct = f"+{edge * 100:.1f}%" if edge >= 0 else f"{edge * 100:.1f}%"
    event_name = f"{alert.get('side_a', 'Side A')} vs {alert.get('side_b', 'Side B')}"
    target_book = alert.get("target_book", "Sportsbook").upper()
    pick = alert.get("target_side", "Pick")
    soft_dec = alert.get("soft_decimal", 0.0)
    soft_am = alert.get("soft_american")
    am_str = f" ({soft_am:+d})" if soft_am is not None else ""
    fair_dec = alert.get("sharp_fair_decimal", 0.0)
    true_prob = alert.get("sharp_true_prob", 0.0) * 100
    stake = alert.get("kelly_stake", 0.0)
    stake_pct = alert.get("kelly_pct", 0.0)
    profit = alert.get("kelly_profit", 0.0)

    text = (
        f"🚨 *EDGEPULSE +EV ALERT: {edge_pct} EDGE*\n\n"
        f"🏆 *Event:* {event_name}\n"
        f"🎯 *Target Pick:* `{pick}`\n"
        f"🏢 *Sportsbook:* *{target_book}*\n"
        f"💰 *Offered Odds:* `{soft_dec:.2f}`{am_str}\n"
        f"📐 *Sharp Fair Odds:* `{fair_dec:.2f}` ({true_prob:.1f}% Win Probability)\n\n"
        f"💵 *Recommended Kelly Stake:* `${stake:.2f}` ({stake_pct:.1f}% bankroll)\n"
        f"📈 *Expected Profit:* `+${profit:.2f}`\n\n"
        f"⚡ _EdgePulse Real-Time Odds Anomaly Engine_"
    )

    url = f"https://api.telegram.org/bot{token_clean}/sendMessage"
    payload = json.dumps({
        "chat_id": chat_clean,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True,
    }).encode("utf-8")

    try:
        req = urllib.request.Request(
            url,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "EdgePulse-Bot/1.0",
            },
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            return resp.status == 200
    except Exception as e:
        print(f"Telegram alert error: {e}")
        return False


def send_telegram_test(bot_token: str, chat_id: str) -> Tuple[bool, str]:
    """Verify Telegram bot credentials by dispatching a test ping."""
    if not bot_token or not bot_token.strip():
        return False, "Bot token is required."
    if not chat_id or not chat_id.strip():
        return False, "Chat ID is required."

    token_clean = bot_token.strip()
    chat_clean = chat_id.strip()

    url = f"https://api.telegram.org/bot{token_clean}/sendMessage"
    payload = json.dumps({
        "chat_id": chat_clean,
        "text": (
            "⚡ *EdgePulse Telegram Dispatcher Connected!*\n\n"
            "Your Telegram channel is now paired with EdgePulse. Real-time +EV betting opportunities will be posted here automatically."
        ),
        "parse_mode": "Markdown",
    }).encode("utf-8")

    try:
        req = urllib.request.Request(
            url,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "EdgePulse-Bot/1.0",
            },
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if data.get("ok"):
                return True, "Test alert sent to Telegram successfully!"
            return False, data.get("description", "Failed to dispatch test message.")
    except urllib.error.HTTPError as he:
        try:
            err_data = json.loads(he.read().decode("utf-8"))
            return False, err_data.get("description", f"Telegram API Error ({he.code})")
        except Exception:
            return False, f"Telegram API Error: HTTP {he.code}"
    except Exception as e:
        return False, f"Connection error: {str(e)}"
