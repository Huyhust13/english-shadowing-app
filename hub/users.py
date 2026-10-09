"""Accounts: create, look up, passwords, invite and reset links, settings.

All functions take an open connection as their first argument, so the same code
serves requests (get_db()) and background jobs (db.connect()). Functions that write
commit their own transaction.
"""
import datetime
import hashlib
import re
import secrets
import zoneinfo

from werkzeug.security import check_password_hash, generate_password_hash

USERNAME_RE = re.compile(r"[a-z0-9][a-z0-9_.-]{1,31}")
MIN_PASSWORD = 8
INVITE_DAYS = 7
RESET_DAYS = 2
TIME_RE = re.compile(r"([01]\d|2[0-3]):[0-5]\d")


class AccountError(ValueError):
    """Bad input from the person (shown to them as-is)."""


def _now():
    return datetime.datetime.now(datetime.timezone.utc).replace(microsecond=0)


def _iso(dt):
    return dt.strftime("%Y-%m-%d %H:%M:%S")  # same format as SQLite's datetime('now')


def hash_token(token):
    return hashlib.sha256(token.encode()).hexdigest()


def check_username(username):
    username = (username or "").strip().lower()
    if not USERNAME_RE.fullmatch(username):
        raise AccountError("Username: 2–32 characters, lowercase letters, digits, '.', '_' or '-'.")
    return username


def check_password(password):
    if not isinstance(password, str) or len(password) < MIN_PASSWORD:
        raise AccountError(f"Password must be at least {MIN_PASSWORD} characters.")
    if len(password) > 200:
        raise AccountError("Password is too long.")
    return password


def check_timezone(tz):
    try:
        zoneinfo.ZoneInfo(tz)
    except (zoneinfo.ZoneInfoNotFoundError, ValueError, TypeError):
        raise AccountError("Unknown timezone.") from None
    return tz


def check_display_name(name):
    name = " ".join(str(name or "").split())
    if not 1 <= len(name) <= 60:
        raise AccountError("Name must be 1–60 characters.")
    return name


# ---- Accounts -----------------------------------------------------------------

def create_user(conn, username, display_name, password, timezone, is_admin=False):
    username = check_username(username)
    with conn:
        if conn.execute("SELECT 1 FROM users WHERE username = ?", (username,)).fetchone():
            raise AccountError("That username is taken.")
        cur = conn.execute(
            "INSERT INTO users (username, display_name, password_hash, is_admin, media_key, timezone)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (username, check_display_name(display_name or username),
             generate_password_hash(check_password(password)), int(bool(is_admin)),
             secrets.token_urlsafe(24), check_timezone(timezone)),
        )
    return cur.lastrowid


def get_user(conn, user_id):
    return conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def find_by_username(conn, username):
    return conn.execute("SELECT * FROM users WHERE username = ?", ((username or "").strip(),)).fetchone()


def find_by_media_key(conn, key):
    return conn.execute("SELECT id FROM users WHERE media_key = ? AND is_active = 1", (key,)).fetchone()


def authenticate(conn, username, password):
    """The user row if the login is right and the account is active, else None."""
    user = find_by_username(conn, username)
    if user is None:
        check_password_hash(generate_password_hash("x"), str(password))  # same timing either way
        return None
    if not user["is_active"] or not check_password_hash(user["password_hash"], str(password or "")):
        return None
    return user


def set_password(conn, user_id, password):
    """Set a new password and log out every other device (session_version bump)."""
    with conn:
        conn.execute("UPDATE users SET password_hash = ?, session_version = session_version + 1 WHERE id = ?",
                     (generate_password_hash(check_password(password)), user_id))


def update_settings(conn, user_id, data):
    fields = {}
    if "displayName" in data:
        fields["display_name"] = check_display_name(data["displayName"])
    if "timezone" in data:
        fields["timezone"] = check_timezone(data["timezone"])
    if "reminderEnabled" in data:
        fields["reminder_enabled"] = int(bool(data["reminderEnabled"]))
    if "reminderTime" in data:
        if not isinstance(data["reminderTime"], str) or not TIME_RE.fullmatch(data["reminderTime"]):
            raise AccountError("Reminder time must be HH:MM.")
        fields["reminder_time"] = data["reminderTime"]
    if {"timezone", "reminderTime", "reminderEnabled"} & data.keys():
        fields["reminder_last_date"] = None  # let a new time fire today
    if not fields:
        return
    with conn:
        conn.execute("UPDATE users SET " + ", ".join(f"{k} = ?" for k in fields) + " WHERE id = ?",
                     (*fields.values(), user_id))


def set_active(conn, user_id, active):
    with conn:
        conn.execute("UPDATE users SET is_active = ?, session_version = session_version + 1 WHERE id = ?",
                     (int(bool(active)), user_id))


def list_users(conn):
    return conn.execute(
        "SELECT u.id, u.username, u.display_name, u.is_admin, u.is_active, u.created_at,"
        " (SELECT MAX(date) FROM sessions s WHERE s.user_id = u.id) AS last_shadowing,"
        " (SELECT MAX(date) FROM practice_days p WHERE p.user_id = u.id) AS last_practice"
        " FROM users u ORDER BY u.id").fetchall()


# ---- Invite and reset links ------------------------------------------------------

def create_link(conn, kind, created_by, user_id=None, note=""):
    """Make a one-time link token; only its hash is stored. Returns the token."""
    token = secrets.token_urlsafe(24)
    days = INVITE_DAYS if kind == "invite" else RESET_DAYS
    with conn:
        if kind == "reset":  # only the newest reset link for a user works
            conn.execute("DELETE FROM invites WHERE kind = 'reset' AND user_id = ? AND used_at IS NULL", (user_id,))
        conn.execute(
            "INSERT INTO invites (token_hash, kind, user_id, note, created_by, expires_at) VALUES (?, ?, ?, ?, ?, ?)",
            (hash_token(token), kind, user_id, str(note or "")[:200], created_by,
             _iso(_now() + datetime.timedelta(days=days))),
        )
    return token


def find_link(conn, token):
    """The unused, unexpired invites row for this token, or None."""
    if not token or len(token) > 100:
        return None
    return conn.execute(
        "SELECT i.*, u.username FROM invites i LEFT JOIN users u ON u.id = i.user_id"
        " WHERE i.token_hash = ? AND i.used_at IS NULL AND i.expires_at > ?",
        (hash_token(token), _iso(_now()))).fetchone()


def use_link(conn, token, username=None, display_name=None, password=None, timezone=None):
    """Redeem an invite (creates the account) or a reset link (sets the password).

    Returns the user id. The link is claimed first with a conditional UPDATE, so two
    people racing on the same link can't both redeem it; it's released again if the
    form input turns out to be invalid.
    """
    link = find_link(conn, token)
    if link is None:
        raise AccountError("This link has expired or was already used. Ask for a new one.")
    with conn:
        cur = conn.execute("UPDATE invites SET used_at = ? WHERE id = ? AND used_at IS NULL",
                           (_iso(_now()), link["id"]))
    if cur.rowcount != 1:
        raise AccountError("This link was already used.")
    try:
        if link["kind"] == "invite":
            user_id = create_user(conn, username, display_name, password, timezone)
        else:
            user_id = link["user_id"]
            set_password(conn, user_id, password)
    except Exception:
        with conn:
            conn.execute("UPDATE invites SET used_at = NULL WHERE id = ?", (link["id"],))
        raise
    with conn:
        conn.execute("UPDATE invites SET user_id = ? WHERE id = ?", (user_id, link["id"]))
    return user_id


def pending_invites(conn):
    return conn.execute(
        "SELECT id, note, created_at, expires_at FROM invites"
        " WHERE kind = 'invite' AND used_at IS NULL AND expires_at > ? ORDER BY id DESC",
        (_iso(_now()),)).fetchall()


def revoke_invite(conn, invite_id):
    with conn:
        conn.execute("DELETE FROM invites WHERE id = ? AND used_at IS NULL", (invite_id,))
