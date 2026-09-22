"""
EdgePulse Database Module
Embedded SQLite storage for user accounts, authentication, sessions, and personalized settings.
"""

import hashlib
import json
import logging
import os
import secrets
import sqlite3
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("edgepulse.db")

ROOT_DIR = Path(__file__).resolve().parent.parent
CUSTOM_DB_PATH = os.environ.get("DATABASE_PATH")
if CUSTOM_DB_PATH:
    DB_PATH = Path(CUSTOM_DB_PATH).resolve()
    DATA_DIR = DB_PATH.parent
else:
    DATA_DIR = ROOT_DIR / "data"
    DB_PATH = DATA_DIR / "edgepulse.db"

GCS_BUCKET = os.environ.get("GCS_DB_BUCKET", "edgepulse-prod-509316_cloudbuild")
GCS_OBJECT = os.environ.get("GCS_DB_OBJECT", "edgepulse_prod.db")
_backup_lock = threading.Lock()


def _get_gcp_access_token() -> Optional[str]:
    """Retrieve OAuth2 access token from Google Cloud metadata server if running in GCP."""
    try:
        url = "http://metadata.google.internal/computeMetadata/v1/instance/service-accounts/default/token"
        req = urllib.request.Request(url, headers={"Metadata-Flavor": "Google"})
        with urllib.request.urlopen(req, timeout=1.5) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8"))
                return data.get("access_token")
    except Exception:
        return None
    return None


def restore_from_gcs() -> bool:
    """Download edgepulse.db from GCS bucket on container startup if it exists."""
    token = _get_gcp_access_token()
    if not token or not GCS_BUCKET:
        return False
    try:
        url = f"https://storage.googleapis.com/storage/v1/b/{GCS_BUCKET}/o/{urllib.parse.quote(GCS_OBJECT, safe='')}?alt=media"
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}", "User-Agent": "EdgePulse/1.0"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            if resp.status == 200:
                DATA_DIR.mkdir(parents=True, exist_ok=True)
                content = resp.read()
                if len(content) > 0:
                    with open(DB_PATH, "wb") as f:
                        f.write(content)
                    print(f"[EdgePulse DB] Successfully restored database from gs://{GCS_BUCKET}/{GCS_OBJECT} ({len(content)} bytes)")
                    return True
    except urllib.error.HTTPError as he:
        if he.code == 404:
            print(f"[EdgePulse DB] No existing database found at gs://{GCS_BUCKET}/{GCS_OBJECT}. Starting fresh.")
        else:
            print(f"[EdgePulse DB] GCS restore HTTP {he.code}: {he.reason}")
    except Exception as e:
        print(f"[EdgePulse DB] Could not restore database from GCS: {e}")
    return False


def _backup_worker():
    token = _get_gcp_access_token()
    if not token or not GCS_BUCKET or not DB_PATH.exists():
        return
    try:
        try:
            conn = sqlite3.connect(DB_PATH, timeout=5.0)
            conn.execute("PRAGMA wal_checkpoint(PASSIVE);")
            conn.close()
        except Exception:
            pass

        with open(DB_PATH, "rb") as f:
            data = f.read()

        if len(data) == 0:
            return

        url = f"https://storage.googleapis.com/upload/storage/v1/b/{GCS_BUCKET}/o?uploadType=media&name={urllib.parse.quote(GCS_OBJECT, safe='')}"
        req = urllib.request.Request(
            url,
            data=data,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/x-sqlite3",
                "User-Agent": "EdgePulse/1.0",
            },
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status in (200, 201):
                print(f"[EdgePulse DB] Successfully backed up database to gs://{GCS_BUCKET}/{GCS_OBJECT} ({len(data)} bytes)")
    except Exception as e:
        print(f"[EdgePulse DB] GCS backup failed: {e}")


def trigger_gcs_backup(delay_seconds: float = 1.0):
    """Trigger an asynchronous, debounced backup of the database to GCS."""
    def run():
        time.sleep(delay_seconds)
        with _backup_lock:
            _backup_worker()
    threading.Thread(target=run, daemon=True).start()


def get_connection() -> sqlite3.Connection:
    """Get a thread-safe connection to the SQLite database with WAL enabled."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10.0, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA foreign_keys=ON;")
    return conn


def init_db():
    """Create database tables and indexes if they do not already exist."""
    restore_from_gcs()
    if os.environ.get("CLEAR_DB_ON_BOOT") == "1":
        print("[EdgePulse DB] CLEAR_DB_ON_BOOT=1 detected. Wiping all user data on boot...")
        clear_all_users()
    conn = get_connection()
    try:
        with conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    email TEXT UNIQUE NOT NULL,
                    password_hash TEXT,
                    salt TEXT,
                    name TEXT,
                    avatar_url TEXT,
                    auth_provider TEXT NOT NULL DEFAULT 'local',
                    google_sub TEXT UNIQUE,
                    bankroll REAL DEFAULT 1000.0,
                    kelly_multiplier REAL DEFAULT 0.25,
                    discord_webhook TEXT DEFAULT '',
                    discord_enabled INTEGER DEFAULT 0,
                    min_ev REAL DEFAULT 0.01,
                    preferred_region TEXT DEFAULT 'all',
                    telegram_token TEXT DEFAULT '',
                    telegram_chat_id TEXT DEFAULT '',
                    telegram_enabled INTEGER DEFAULT 0,
                    created_at REAL NOT NULL,
                    last_login REAL NOT NULL
                );
            """)

            # Migrations for existing databases
            for col, col_def in [
                ("preferred_region", "TEXT DEFAULT 'all'"),
                ("telegram_token", "TEXT DEFAULT ''"),
                ("telegram_chat_id", "TEXT DEFAULT ''"),
                ("telegram_enabled", "INTEGER DEFAULT 0"),
            ]:
                try:
                    conn.execute(f"ALTER TABLE users ADD COLUMN {col} {col_def};")
                except sqlite3.OperationalError:
                    pass

            conn.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    token TEXT PRIMARY KEY,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    remember_me INTEGER DEFAULT 0,
                    created_at REAL NOT NULL,
                    expires_at REAL NOT NULL
                );
            """)

            try:
                conn.execute("ALTER TABLE sessions ADD COLUMN remember_me INTEGER DEFAULT 0;")
            except sqlite3.OperationalError:
                pass

            conn.execute("""
                CREATE TABLE IF NOT EXISTS bets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    event_id TEXT NOT NULL,
                    sport TEXT NOT NULL,
                    event_name TEXT NOT NULL,
                    selection TEXT NOT NULL,
                    sportsbook TEXT NOT NULL,
                    odds REAL NOT NULL,
                    fair_odds REAL,
                    edge_pct REAL,
                    stake REAL NOT NULL,
                    payout REAL DEFAULT 0.0,
                    profit REAL DEFAULT 0.0,
                    status TEXT DEFAULT 'pending',
                    placed_at REAL NOT NULL,
                    settled_at REAL,
                    notes TEXT
                );
            """)

            conn.execute("CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_users_google_sub ON users(google_sub);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions(user_id);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_sessions_expires_at ON sessions(expires_at);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_bets_user_id ON bets(user_id);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_bets_status ON bets(status);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_bets_placed_at ON bets(placed_at);")

            conn.execute("""
                CREATE TABLE IF NOT EXISTS activity_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER,
                    user_email TEXT,
                    user_name TEXT,
                    sport_key TEXT NOT NULL,
                    sport_name TEXT NOT NULL,
                    action TEXT NOT NULL DEFAULT 'view_sport',
                    ip_address TEXT,
                    timestamp REAL NOT NULL
                );
            """)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_activity_logs_timestamp ON activity_logs(timestamp);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_activity_logs_user_id ON activity_logs(user_id);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_activity_logs_sport_key ON activity_logs(sport_key);")
    finally:
        conn.close()


def hash_password(password: str, salt: Optional[str] = None) -> tuple[str, str]:
    """Generate salted PBKDF2-HMAC-SHA256 password hash."""
    if not salt:
        salt = secrets.token_hex(16)
    key = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        iterations=100_000,
    )
    return key.hex(), salt


def verify_password(password: str, password_hash: str, salt: str) -> bool:
    """Verify password against stored hash."""
    computed_hash, _ = hash_password(password, salt)
    return secrets.compare_digest(computed_hash, password_hash)


def create_user(
    email: str,
    password: Optional[str] = None,
    name: Optional[str] = None,
    auth_provider: str = "local",
    google_sub: Optional[str] = None,
    avatar_url: Optional[str] = None,
) -> Dict[str, Any]:
    """Register a new user in SQLite."""
    email_clean = email.strip().lower()
    if not email_clean:
        raise ValueError("Email cannot be empty.")

    now = time.time()
    password_hash = None
    salt = None

    if password:
        password_hash, salt = hash_password(password)

    if not name:
        name = email_clean.split("@")[0].capitalize()

    conn = get_connection()
    try:
        existing = conn.execute("SELECT * FROM users WHERE email = ?", (email_clean,)).fetchone()
        if existing:
            if existing["auth_provider"] == "google":
                raise ValueError("This email is already registered using Google. Please sign in using 'Continue with Google'.")
            else:
                raise ValueError("An account with this email already exists. Please sign in using your password.")

        with conn:
            cursor = conn.execute(
                """
                INSERT INTO users (
                    email, password_hash, salt, name, avatar_url,
                    auth_provider, google_sub, created_at, last_login
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    email_clean,
                    password_hash,
                    salt,
                    name,
                    avatar_url or "",
                    auth_provider,
                    google_sub,
                    now,
                    now,
                ),
            )
            user_id = cursor.lastrowid
        trigger_gcs_backup()
        return get_user_by_id(user_id)
    finally:
        conn.close()


def authenticate_user(email: str, password: str) -> Optional[Dict[str, Any]]:
    """Authenticate email and password credentials."""
    email_clean = email.strip().lower()
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM users WHERE email = ?",
            (email_clean,),
        ).fetchone()

        if not row:
            return None

        # If user registered with Google
        if row["auth_provider"] == "google":
            raise ValueError("This account was created with Google. Please use 'Continue with Google' to sign in.")

        if row["auth_provider"] == "guest":
            raise ValueError("This is a temporary guest account. Please create a new account to continue.")

        if not row["password_hash"] or not row["salt"]:
            return None

        if verify_password(password, row["password_hash"], row["salt"]):
            with conn:
                conn.execute(
                    "UPDATE users SET last_login = ? WHERE id = ?",
                    (time.time(), row["id"]),
                )
            return dict(row)
        return None
    finally:
        conn.close()


def upsert_google_user(
    google_sub: str,
    email: str,
    name: Optional[str] = None,
    avatar_url: Optional[str] = None,
) -> Dict[str, Any]:
    """Find or create user via Google OAuth Identity."""
    email_clean = email.strip().lower()
    now = time.time()
    conn = get_connection()
    try:
        # Check by google_sub first
        row = conn.execute(
            "SELECT * FROM users WHERE google_sub = ?",
            (google_sub,),
        ).fetchone()

        if row:
            with conn:
                conn.execute(
                    """
                    UPDATE users
                    SET last_login = ?, name = COALESCE(?, name), avatar_url = COALESCE(?, avatar_url)
                    WHERE id = ?
                    """,
                    (now, name, avatar_url, row["id"]),
                )
            return get_user_by_id(row["id"])

        # Check by email if user signed up previously with local email
        row_email = conn.execute(
            "SELECT * FROM users WHERE email = ?",
            (email_clean,),
        ).fetchone()

        if row_email:
            # Prevent collision if account was registered with email and password
            if row_email["auth_provider"] == "local" or (row_email["password_hash"] and not row_email["google_sub"]):
                raise ValueError("An account with this email was created with a password. Please sign in using your email and password.")

            with conn:
                conn.execute(
                    """
                    UPDATE users
                    SET google_sub = ?, auth_provider = 'google', last_login = ?,
                        avatar_url = COALESCE(?, avatar_url), name = COALESCE(?, name)
                    WHERE id = ?
                    """,
                    (google_sub, now, avatar_url, name, row_email["id"]),
                )
            trigger_gcs_backup()
            return get_user_by_id(row_email["id"])

        # Insert brand new Google user
        return create_user(
            email=email_clean,
            name=name or email_clean.split("@")[0].capitalize(),
            auth_provider="google",
            google_sub=google_sub,
            avatar_url=avatar_url,
        )
    finally:
        conn.close()


def create_guest_user() -> Dict[str, Any]:
    """Create a lightweight guest user session."""
    guest_id = secrets.token_hex(4)
    email = f"guest_{guest_id}@edgepulse.local"
    name = f"Guest #{guest_id}"
    return create_user(
        email=email,
        name=name,
        auth_provider="guest",
    )


def create_session(
    user_id: int,
    duration_days: Optional[int] = None,
    remember_me: bool = False,
) -> str:
    """Create and persist a new 64-char crypto session token."""
    token = secrets.token_hex(32)
    now = time.time()
    if duration_days is None:
        duration_days = 30 if remember_me else 1
    expires_at = now + (duration_days * 86400)

    conn = get_connection()
    try:
        with conn:
            conn.execute(
                "INSERT INTO sessions (token, user_id, remember_me, created_at, expires_at) VALUES (?, ?, ?, ?, ?)",
                (token, user_id, 1 if remember_me else 0, now, expires_at),
            )
        trigger_gcs_backup()
        return token
    finally:
        conn.close()


def get_user_by_session(token: str) -> Optional[Dict[str, Any]]:
    """Retrieve active user profile and settings from a session token."""
    if not token:
        return None
    now = time.time()
    conn = get_connection()
    try:
        row = conn.execute(
            """
            SELECT u.*, s.remember_me AS session_remember_me
            FROM sessions s
            JOIN users u ON s.user_id = u.id
            WHERE s.token = ? AND s.expires_at > ?
            """,
            (token, now),
        ).fetchone()

        if not row:
            return None

        user_dict = dict(row)
        # Never leak security hashes
        user_dict.pop("password_hash", None)
        user_dict.pop("salt", None)
        user_dict["session_remember_me"] = bool(user_dict.get("session_remember_me", 0))
        return user_dict
    finally:
        conn.close()


def delete_session(token: str) -> bool:
    """Invalidate an active session token upon logout."""
    conn = get_connection()
    try:
        with conn:
            cursor = conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
            if cursor.rowcount > 0:
                trigger_gcs_backup()
            return cursor.rowcount > 0
    finally:
        conn.close()


def get_user_by_id(user_id: int) -> Optional[Dict[str, Any]]:
    """Retrieve safe user dict by user ID."""
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if not row:
            return None
        user_dict = dict(row)
        user_dict.pop("password_hash", None)
        user_dict.pop("salt", None)
        return user_dict
    finally:
        conn.close()


def get_user_by_email(email: str) -> Optional[Dict[str, Any]]:
    """Retrieve user profile by email address."""
    if not email:
        return None
    email_clean = email.strip().lower()
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM users WHERE email = ?", (email_clean,)).fetchone()
        if not row:
            return None
        user_dict = dict(row)
        user_dict.pop("password_hash", None)
        user_dict.pop("salt", None)
        return user_dict
    finally:
        conn.close()


def update_user_settings(user_id: int, settings: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Update personalized staking, bankroll, and Discord webhook configurations."""
    conn = get_connection()
    try:
        fields = []
        values = []

        if "bankroll" in settings:
            fields.append("bankroll = ?")
            values.append(float(settings["bankroll"]))
        if "kelly_multiplier" in settings:
            fields.append("kelly_multiplier = ?")
            values.append(float(settings["kelly_multiplier"]))
        if "discord_webhook" in settings or "webhook_url" in settings:
            url = settings.get("discord_webhook", settings.get("webhook_url", ""))
            fields.append("discord_webhook = ?")
            values.append(str(url))
        if "discord_enabled" in settings or "enabled" in settings:
            val = settings.get("discord_enabled", settings.get("enabled", False))
            fields.append("discord_enabled = ?")
            values.append(1 if val else 0)
        if "min_ev" in settings:
            fields.append("min_ev = ?")
            values.append(float(settings["min_ev"]))
        if "preferred_region" in settings:
            fields.append("preferred_region = ?")
            values.append(str(settings["preferred_region"]).lower().strip())
        if "telegram_token" in settings:
            fields.append("telegram_token = ?")
            values.append(str(settings["telegram_token"]).strip())
        if "telegram_chat_id" in settings:
            fields.append("telegram_chat_id = ?")
            values.append(str(settings["telegram_chat_id"]).strip())
        if "telegram_enabled" in settings:
            val = settings.get("telegram_enabled", False)
            fields.append("telegram_enabled = ?")
            values.append(1 if val else 0)

        if not fields:
            return get_user_by_id(user_id)

        values.append(user_id)
        with conn:
            conn.execute(
                f"UPDATE users SET {', '.join(fields)} WHERE id = ?",
                values,
            )
        trigger_gcs_backup()
        return get_user_by_id(user_id)
    finally:
        conn.close()


def update_user_profile(
    user_id: int,
    name: Optional[str] = None,
    avatar_url: Optional[str] = None,
    current_password: Optional[str] = None,
    new_password: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Update profile identity (display name, avatar) and password.

    Email is permanently immutable and cannot be updated.
    """
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        if not row:
            raise ValueError(f"User with ID {user_id} not found.")

        fields = []
        values = []

        if name is not None:
            name_clean = str(name).strip()
            if name_clean:
                fields.append("name = ?")
                values.append(name_clean)

        if avatar_url is not None:
            fields.append("avatar_url = ?")
            values.append(str(avatar_url).strip())

        if new_password:
            if len(new_password) < 6:
                raise ValueError("New password must be at least 6 characters.")

            if row["password_hash"] and row["salt"]:
                if not current_password:
                    raise ValueError("Current password is required to set a new password.")
                if not verify_password(current_password, row["password_hash"], row["salt"]):
                    raise ValueError("Current password is incorrect.")

            new_hash, new_salt = hash_password(new_password)
            fields.append("password_hash = ?")
            values.append(new_hash)
            fields.append("salt = ?")
            values.append(new_salt)

        if fields:
            values.append(user_id)
            with conn:
                conn.execute(
                    f"UPDATE users SET {', '.join(fields)} WHERE id = ?",
                    values,
                )
            trigger_gcs_backup()

        return get_user_by_id(user_id)
    finally:
        conn.close()


def log_bet(
    user_id: int,
    event_id: str,
    sport: str,
    event_name: str,
    selection: str,
    sportsbook: str,
    odds: float,
    stake: float,
    fair_odds: Optional[float] = None,
    edge_pct: Optional[float] = None,
    notes: Optional[str] = None,
) -> Dict[str, Any]:
    """Record a newly placed or simulated bet in the user's ledger."""
    now = time.time()
    conn = get_connection()
    try:
        with conn:
            cursor = conn.execute(
                """
                INSERT INTO bets (
                    user_id, event_id, sport, event_name, selection,
                    sportsbook, odds, fair_odds, edge_pct, stake,
                    payout, profit, status, placed_at, notes
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0.0, 0.0, 'pending', ?, ?)
                """,
                (
                    user_id,
                    str(event_id),
                    str(sport),
                    str(event_name),
                    str(selection),
                    str(sportsbook),
                    float(odds),
                    float(fair_odds) if fair_odds is not None else None,
                    float(edge_pct) if edge_pct is not None else None,
                    float(stake),
                    now,
                    str(notes or ""),
                ),
            )
            bet_id = cursor.lastrowid

        trigger_gcs_backup()
        row = conn.execute("SELECT * FROM bets WHERE id = ?", (bet_id,)).fetchone()
        return dict(row)
    finally:
        conn.close()


def get_user_bets(
    user_id: int,
    status: Optional[str] = None,
    limit: int = 200,
    offset: int = 0,
) -> list[Dict[str, Any]]:
    """Retrieve all bets logged by a user, optionally filtered by status."""
    conn = get_connection()
    try:
        if status and status.lower() != "all":
            rows = conn.execute(
                "SELECT * FROM bets WHERE user_id = ? AND status = ? ORDER BY placed_at DESC LIMIT ? OFFSET ?",
                (user_id, status.lower().strip(), limit, offset),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM bets WHERE user_id = ? ORDER BY placed_at DESC LIMIT ? OFFSET ?",
                (user_id, limit, offset),
            ).fetchall()
        bets = []
        for r in rows:
            d = dict(r)
            d["matchup"] = d.get("event_name") or ""
            d["bookmaker"] = d.get("sportsbook") or ""
            d["odds_decimal"] = d.get("odds", 1.0)
            d["expected_value"] = f"+{d['edge_pct']}%" if d.get("edge_pct") is not None else ""
            d["pnl"] = d.get("profit", 0.0)
            bets.append(d)
        return bets
    finally:
        conn.close()


def settle_bet(
    bet_id: int,
    user_id: int,
    status: str,
) -> Dict[str, Any]:
    """Update bet outcome: 'won', 'lost', 'push', 'void', or 'pending'."""
    status_clean = status.lower().strip()
    if status_clean not in ("won", "lost", "push", "void", "pending"):
        raise ValueError(f"Invalid bet status '{status}'. Must be one of: won, lost, push, void, pending.")

    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM bets WHERE id = ? AND user_id = ?", (bet_id, user_id)).fetchone()
        if not row:
            raise ValueError(f"Bet with ID {bet_id} not found for this user.")

        stake = float(row["stake"])
        odds = float(row["odds"])
        now = time.time()

        if status_clean == "won":
            payout = round(stake * odds, 2)
            profit = round(payout - stake, 2)
            settled_at = now
        elif status_clean == "lost":
            payout = 0.0
            profit = round(-stake, 2)
            settled_at = now
        elif status_clean in ("push", "void"):
            payout = round(stake, 2)
            profit = 0.0
            settled_at = now
        else:
            payout = 0.0
            profit = 0.0
            settled_at = None

        with conn:
            conn.execute(
                """
                UPDATE bets
                SET status = ?, payout = ?, profit = ?, settled_at = ?
                WHERE id = ? AND user_id = ?
                """,
                (status_clean, payout, profit, settled_at, bet_id, user_id),
            )

        trigger_gcs_backup()
        updated_row = conn.execute("SELECT * FROM bets WHERE id = ?", (bet_id,)).fetchone()
        d = dict(updated_row)
        d["matchup"] = d.get("event_name") or ""
        d["bookmaker"] = d.get("sportsbook") or ""
        d["odds_decimal"] = d.get("odds", 1.0)
        d["expected_value"] = f"+{d['edge_pct']}%" if d.get("edge_pct") is not None else ""
        d["pnl"] = d.get("profit", 0.0)
        return d
    finally:
        conn.close()


def delete_bet(bet_id: int, user_id: int) -> bool:
    """Delete a bet from the user's ledger."""
    conn = get_connection()
    try:
        with conn:
            cursor = conn.execute("DELETE FROM bets WHERE id = ? AND user_id = ?", (bet_id, user_id))
            if cursor.rowcount > 0:
                trigger_gcs_backup()
            return cursor.rowcount > 0
    finally:
        conn.close()


def get_bet_performance_stats(user_id: int) -> Dict[str, Any]:
    """Calculate aggregate performance metrics and equity curve data."""
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT * FROM bets WHERE user_id = ? ORDER BY placed_at ASC",
            (user_id,),
        ).fetchall()

        total_bets = len(rows)
        pending_count = 0
        won_count = 0
        lost_count = 0
        push_count = 0

        total_staked = 0.0
        settled_staked = 0.0
        total_profit = 0.0

        equity_curve = []
        cumulative_profit = 0.0

        for r in rows:
            stk = float(r["stake"])
            total_staked += stk
            st = r["status"]
            odds = float(r["odds"]) if r["odds"] else 1.0

            if st == "pending":
                pending_count += 1
                pot_profit = round((odds - 1.0) * stk, 2)
                equity_curve.append({
                    "time": r["placed_at"],
                    "profit": round(cumulative_profit, 2),
                    "cumulative_pnl": round(cumulative_profit, 2),
                    "delta": 0.0,
                    "event": r["event_name"],
                    "selection": r["selection"],
                    "sportsbook": r["sportsbook"],
                    "stake": stk,
                    "odds": odds,
                    "potential_profit": pot_profit,
                    "result": "pending",
                })
            elif st == "won":
                won_count += 1
                settled_staked += stk
                prf = float(r["profit"])
                total_profit += prf
                cumulative_profit += prf
                equity_curve.append({
                    "time": r["settled_at"] or r["placed_at"],
                    "profit": round(cumulative_profit, 2),
                    "cumulative_pnl": round(cumulative_profit, 2),
                    "delta": prf,
                    "event": r["event_name"],
                    "selection": r["selection"],
                    "sportsbook": r["sportsbook"],
                    "stake": stk,
                    "odds": odds,
                    "potential_profit": 0.0,
                    "result": "won",
                })
            elif st == "lost":
                lost_count += 1
                settled_staked += stk
                prf = float(r["profit"])
                total_profit += prf
                cumulative_profit += prf
                equity_curve.append({
                    "time": r["settled_at"] or r["placed_at"],
                    "profit": round(cumulative_profit, 2),
                    "cumulative_pnl": round(cumulative_profit, 2),
                    "delta": prf,
                    "event": r["event_name"],
                    "selection": r["selection"],
                    "sportsbook": r["sportsbook"],
                    "stake": stk,
                    "odds": odds,
                    "potential_profit": 0.0,
                    "result": "lost",
                })
            elif st in ("push", "void"):
                push_count += 1
                settled_staked += stk
                equity_curve.append({
                    "time": r["settled_at"] or r["placed_at"],
                    "profit": round(cumulative_profit, 2),
                    "cumulative_pnl": round(cumulative_profit, 2),
                    "delta": 0.0,
                    "event": r["event_name"],
                    "selection": r["selection"],
                    "sportsbook": r["sportsbook"],
                    "stake": stk,
                    "odds": odds,
                    "potential_profit": 0.0,
                    "result": "push",
                })

        resolved_decisive = won_count + lost_count
        win_rate = round((won_count / resolved_decisive * 100), 1) if resolved_decisive > 0 else 0.0
        roi = round((total_profit / settled_staked * 100), 2) if settled_staked > 0 else 0.0

        return {
            "total_bets": total_bets,
            "pending_count": pending_count,
            "pending_bets": pending_count,
            "won_count": won_count,
            "won_bets": won_count,
            "lost_count": lost_count,
            "lost_bets": lost_count,
            "push_count": push_count,
            "push_bets": push_count,
            "total_staked": round(total_staked, 2),
            "settled_staked": round(settled_staked, 2),
            "total_profit": round(total_profit, 2),
            "net_profit": round(total_profit, 2),
            "win_rate": win_rate,
            "win_rate_pct": win_rate,
            "roi": roi,
            "roi_pct": roi,
            "equity_curve": equity_curve,
            "timeline": equity_curve,
        }
    finally:
        conn.close()


def list_all_users() -> list[Dict[str, Any]]:
    """List all registered users without sensitive credentials."""
    conn = get_connection()
    try:
        rows = conn.execute("SELECT id, email, name, auth_provider, bankroll, kelly_multiplier, created_at FROM users ORDER BY id ASC").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def clear_all_users() -> int:
    """Clear all records from users, sessions, bets, and activity_logs tables."""
    conn = get_connection()
    try:
        with conn:
            conn.execute("DELETE FROM sessions;")
            conn.execute("DELETE FROM bets;")
            conn.execute("DELETE FROM activity_logs;")
            cursor = conn.execute("DELETE FROM users;")
            conn.execute("DELETE FROM sqlite_sequence WHERE name IN ('users', 'sessions', 'bets', 'activity_logs');")
            deleted_count = cursor.rowcount
        trigger_gcs_backup()
        return deleted_count
    finally:
        conn.close()


def log_activity(
    sport_key: str,
    sport_name: str,
    action: str = "view_sport",
    user_id: Optional[int] = None,
    user_email: Optional[str] = None,
    user_name: Optional[str] = None,
    ip_address: Optional[str] = None,
) -> int:
    """Record user or guest sport viewing/action activity timelog in SQLite."""
    conn = get_connection()
    try:
        with conn:
            cur = conn.execute(
                """
                INSERT INTO activity_logs (user_id, user_email, user_name, sport_key, sport_name, action, ip_address, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    user_id,
                    user_email or "Guest (Visitor)",
                    user_name or "Guest Visitor",
                    sport_key,
                    sport_name,
                    action,
                    ip_address or "127.0.0.1",
                    time.time(),
                ),
            )
            return cur.lastrowid
    finally:
        conn.close()


def get_activity_logs(
    limit: int = 100,
    user_id: Optional[int] = None,
    sport_key: Optional[str] = None,
) -> list[Dict[str, Any]]:
    """Retrieve recent activity timelogs ordered newest first."""
    conn = get_connection()
    try:
        query = "SELECT * FROM activity_logs"
        params: list[Any] = []
        clauses = []
        if user_id is not None:
            clauses.append("user_id = ?")
            params.append(user_id)
        if sport_key is not None:
            clauses.append("sport_key = ?")
            params.append(sport_key)
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY timestamp DESC LIMIT ?;"
        params.append(limit)
        rows = conn.execute(query, params).fetchall()
        result = []
        for r in rows:
            ts = r["timestamp"]
            time_struct = time.gmtime(ts)
            iso_str = time.strftime("%Y-%m-%d %H:%M:%S UTC", time_struct)
            result.append({
                "id": r["id"],
                "user_id": r["user_id"],
                "user_email": r["user_email"],
                "user_name": r["user_name"],
                "sport_key": r["sport_key"],
                "sport_name": r["sport_name"],
                "action": r["action"],
                "ip_address": r["ip_address"],
                "timestamp": ts,
                "formatted_time": iso_str,
            })
        return result
    finally:
        conn.close()


# Ensure DB schema is initialized on import
init_db()
