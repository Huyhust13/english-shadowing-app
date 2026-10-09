"""SQLite access and schema migrations.

One database file (data/hub.db) holds accounts and everyone's logs; each row that
belongs to a person carries a user_id. Anki collections are separate files, one per
person (see anki_pool.py).

- Inside a request, use get_db(): one connection per request, closed at the end.
- In background threads, use connect(path) and close it yourself.

Migrations are numbered SQL scripts in MIGRATIONS. The database remembers how many
have run in `PRAGMA user_version`, and migrate() runs the rest in order, each in its
own transaction. To change the schema, append a new script; never edit an old one.
"""
import sqlite3

from flask import current_app, g

MIGRATIONS = [
    # 1: accounts, per-user logs, notification channels
    """
    CREATE TABLE users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL UNIQUE COLLATE NOCASE,
        display_name TEXT NOT NULL,
        password_hash TEXT NOT NULL,
        is_admin INTEGER NOT NULL DEFAULT 0,
        is_active INTEGER NOT NULL DEFAULT 1,
        session_version INTEGER NOT NULL DEFAULT 1,  -- bump to log out every device
        media_key TEXT NOT NULL UNIQUE,              -- secret part of /anki-media/<key>/ URLs
        timezone TEXT NOT NULL,
        reminder_enabled INTEGER NOT NULL DEFAULT 1,
        reminder_time TEXT NOT NULL DEFAULT '20:00', -- HH:MM in the user's timezone
        reminder_last_date TEXT,                     -- last local date the reminder was handled
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    );

    -- One-time links: 'invite' creates an account, 'reset' sets a new password.
    CREATE TABLE invites (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        token_hash TEXT NOT NULL UNIQUE,
        kind TEXT NOT NULL CHECK (kind IN ('invite', 'reset')),
        user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
        note TEXT NOT NULL DEFAULT '',
        created_by INTEGER REFERENCES users(id) ON DELETE SET NULL,
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        expires_at TEXT NOT NULL,
        used_at TEXT
    );

    CREATE TABLE sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        date TEXT NOT NULL,
        loggedAt TEXT NOT NULL,
        clipTitle TEXT NOT NULL DEFAULT '',
        clipUrl TEXT NOT NULL DEFAULT '',
        reps INTEGER NOT NULL DEFAULT 1,
        confidence INTEGER,
        notes TEXT NOT NULL DEFAULT '',
        UNIQUE (user_id, loggedAt)
    );
    CREATE INDEX sessions_user_date ON sessions (user_id, date);

    CREATE TABLE practice_days (
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        date TEXT NOT NULL,
        note TEXT NOT NULL DEFAULT '',
        markedAt TEXT NOT NULL,
        PRIMARY KEY (user_id, date)
    );

    CREATE TABLE anki_accounts (
        user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
        username TEXT NOT NULL DEFAULT '',
        hkey TEXT NOT NULL,
        endpoint TEXT NOT NULL DEFAULT ''
    );

    CREATE TABLE telegram_links (
        user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
        chat_id INTEGER NOT NULL,
        name TEXT NOT NULL DEFAULT '',
        linked_at TEXT NOT NULL DEFAULT (datetime('now'))
    );
    CREATE TABLE telegram_link_tokens (
        token TEXT PRIMARY KEY,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        expires_at TEXT NOT NULL
    );

    CREATE TABLE push_subscriptions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
        endpoint TEXT NOT NULL UNIQUE,
        p256dh TEXT NOT NULL,
        auth TEXT NOT NULL,
        user_agent TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    );

    -- Small key/value store for the app itself (e.g. the Telegram update offset).
    CREATE TABLE app_state (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );
    """,
]


def connect(path):
    conn = sqlite3.connect(path, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def migrate(path):
    conn = connect(path)
    try:
        conn.execute("PRAGMA journal_mode = WAL")  # readers don't block the writer
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        for number, script in enumerate(MIGRATIONS[version:], start=version + 1):
            # executescript() commits first, so wrap each script in its own transaction.
            conn.executescript(f"BEGIN; {script}; PRAGMA user_version = {number}; COMMIT;")
    finally:
        conn.close()


def get_db():
    if "db" not in g:
        g.db = connect(current_app.config["DATABASE"])
    return g.db


def close_db(_exc=None):
    conn = g.pop("db", None)
    if conn is not None:
        conn.close()


def get_state(conn, key, default=None):
    row = conn.execute("SELECT value FROM app_state WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_state(conn, key, value):
    conn.execute("INSERT INTO app_state (key, value) VALUES (?, ?)"
                 " ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, str(value)))
