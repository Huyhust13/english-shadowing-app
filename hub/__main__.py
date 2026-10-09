"""Command line: run the server and manage accounts.

  python -m hub                         run the server (waitress) on HOST:PORT
  python -m hub create-admin <username> [--link]
                                        create the first (admin) account; asks for a password,
                                        or with --link prints a link to set it in the browser
  python -m hub invite [note]           print a one-time invite link for a friend
  python -m hub reset-link <username>   print a password-reset link
  python -m hub import-legacy <username> --shadowing-db PATH [--anki-dir PATH]
        [--ankiweb-json PATH] [--telegram-env PATH]
                                        move the single-user English Hub's data into an account
"""
import argparse
import getpass
import logging
import os
import secrets
import shutil
import signal
import sqlite3
import sys

from . import __version__, activity, create_app, db, users
from .config import Config


def serve(config):
    from waitress import serve as waitress_serve

    app = create_app(config)

    def stop(*_):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, stop)  # systemd stops us with SIGTERM; close collections cleanly
    logging.getLogger(__name__).info("English Hub %s on http://%s:%s (public: %s)",
                                     __version__, config.HOST, config.PORT, config.PUBLIC_URL)
    try:
        waitress_serve(app, host=config.HOST, port=config.PORT, threads=8, ident="english-hub")
    except KeyboardInterrupt:
        pass
    finally:
        app.extensions["hub"].pool.close_all()


def create_admin(config, username, by_link=False):
    db.migrate(config.DATABASE)
    if by_link:
        password = secrets.token_urlsafe(32)  # never shown; the person sets their own via the link
    else:
        password = getpass.getpass("Password (8+ characters): ")
        if password != getpass.getpass("Again: "):
            sys.exit("Passwords don't match.")
    conn = db.connect(config.DATABASE)
    try:
        uid = users.create_user(conn, username, username, password, config.DEFAULT_TIMEZONE, is_admin=True)
    except users.AccountError as e:
        sys.exit(str(e))
    print(f"Created admin account {username!r} (id {uid}).")
    if by_link:
        token = users.create_link(conn, "reset", None, user_id=uid)
        print(f"Set its password here (valid {users.RESET_DAYS} days): {config.PUBLIC_URL}/join/{token}")


def make_link(config, kind, username=None, note=""):
    db.migrate(config.DATABASE)
    conn = db.connect(config.DATABASE)
    user_id = None
    if kind == "reset":
        user = users.find_by_username(conn, username)
        if user is None:
            sys.exit(f"No user {username!r}.")
        user_id = user["id"]
    token = users.create_link(conn, kind, None, user_id=user_id, note=note)
    print(f"{config.PUBLIC_URL}/join/{token}")


def import_legacy(config, username, shadowing_db, anki_dir=None, ankiweb_json=None, telegram_env=None):
    """Copy the old single-user data into `username`'s account. Idempotent for sessions."""
    import json

    db.migrate(config.DATABASE)
    conn = db.connect(config.DATABASE)
    user = users.find_by_username(conn, username)
    if user is None:
        sys.exit(f"No user {username!r}; create it first.")
    uid = user["id"]

    old = sqlite3.connect(f"file:{shadowing_db}?mode=ro", uri=True)
    old.row_factory = sqlite3.Row
    sessions = [dict(r) for r in old.execute("SELECT * FROM sessions")]
    activity.add_sessions(conn, uid, sessions)
    practice = []
    if old.execute("SELECT 1 FROM sqlite_master WHERE name = 'practice_days'").fetchone():
        practice = [dict(r) for r in old.execute("SELECT * FROM practice_days")]
        with conn:
            conn.executemany(
                "INSERT OR IGNORE INTO practice_days (user_id, date, note, markedAt) VALUES (?, ?, ?, ?)",
                [(uid, p["date"], p["note"], p["markedAt"]) for p in practice])
    old.close()
    print(f"Imported {len(sessions)} shadowing sessions and {len(practice)} practice days.")

    if anki_dir:
        target = os.path.join(config.USERS_DIR, str(uid), "anki")
        if os.path.exists(os.path.join(target, "collection.anki2")):
            print(f"Skipped Anki: {target} already has a collection.")
        else:
            os.makedirs(os.path.dirname(target), exist_ok=True)
            if os.path.exists(target):
                os.rmdir(target)  # an empty folder left by a first visit to Vocab
            shutil.move(anki_dir, target)
            print(f"Moved Anki collection {anki_dir} -> {target}")

    if ankiweb_json:
        with open(ankiweb_json) as f:
            auth = json.load(f)
        with conn:
            conn.execute(
                "INSERT INTO anki_accounts (user_id, username, hkey, endpoint) VALUES (?, ?, ?, ?)"
                " ON CONFLICT(user_id) DO UPDATE SET username = excluded.username, hkey = excluded.hkey,"
                " endpoint = excluded.endpoint",
                (uid, auth.get("username", ""), auth["hkey"], auth.get("endpoint", "")))
        print("Imported the AnkiWeb login.")

    if telegram_env:
        env = {}
        with open(telegram_env) as f:
            for line in f:
                if "=" in line and not line.lstrip().startswith("#"):
                    k, v = line.strip().split("=", 1)
                    env[k.strip()] = v.strip()
        if env.get("TELEGRAM_CHAT_ID"):
            with conn:
                conn.execute("INSERT OR REPLACE INTO telegram_links (user_id, chat_id, name) VALUES (?, ?, ?)",
                             (uid, int(env["TELEGRAM_CHAT_ID"]), user["display_name"]))
            print("Linked the existing Telegram chat.")
    conn.close()


def load_env_file(path=os.path.expanduser("~/.config/english-hub/hub.env")):
    """Read the service's settings file, so CLI commands use the same database and URL.

    Variables already set in the environment win.
    """
    try:
        with open(path) as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    os.environ.setdefault(key.strip(), value.strip())
    except FileNotFoundError:
        pass


def main(argv=None):
    load_env_file(os.environ.get("HUB_ENV_FILE", os.path.expanduser("~/.config/english-hub/hub.env")))
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    parser = argparse.ArgumentParser(prog="python -m hub", description="English Hub")
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("serve")
    p = sub.add_parser("create-admin")
    p.add_argument("username")
    p.add_argument("--link", action="store_true")
    p = sub.add_parser("invite")
    p.add_argument("note", nargs="?", default="")
    p = sub.add_parser("reset-link")
    p.add_argument("username")
    p = sub.add_parser("import-legacy")
    p.add_argument("username")
    p.add_argument("--shadowing-db", required=True)
    p.add_argument("--anki-dir")
    p.add_argument("--ankiweb-json")
    p.add_argument("--telegram-env")
    args = parser.parse_args(argv)

    if args.cmd in (None, "serve"):
        return serve(Config())
    config = Config(START_WORKERS=False)
    if args.cmd == "create-admin":
        create_admin(config, args.username, args.link)
    elif args.cmd == "invite":
        make_link(config, "invite", note=args.note)
    elif args.cmd == "reset-link":
        make_link(config, "reset", username=args.username)
    elif args.cmd == "import-legacy":
        import_legacy(config, args.username, args.shadowing_db, args.anki_dir, args.ankiweb_json, args.telegram_env)


if __name__ == "__main__":
    main()
