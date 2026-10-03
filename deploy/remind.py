#!/usr/bin/env python3
"""Telegram reminder: message me if no shadowing session has been logged today.

Run by the shadowing-reminder systemd user timer. Reads the SQLite DB directly
(read-only), so it works even if the web server is down.

Credentials live outside the repo in ~/.config/shadowing-tracker/telegram.env
(created by deploy/setup-telegram.py):
    TELEGRAM_BOT_TOKEN=...
    TELEGRAM_CHAT_ID=...
"""
import datetime
import json
import os
import sqlite3
import sys
import urllib.parse
import urllib.request

APP_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DB_PATH = os.environ.get("SHADOWING_DB", os.path.join(APP_DIR, "data", "shadowing.db"))
APP_URL = os.environ.get("SHADOWING_URL", "http://english.nvh/")
CONFIG_PATH = os.path.expanduser("~/.config/shadowing-tracker/telegram.env")


def load_config(path=CONFIG_PATH):
    config = {}
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, value = line.split("=", 1)
                config[key.strip()] = value.strip()
    return config


def telegram_send(token, chat_id, text):
    data = urllib.parse.urlencode({"chat_id": chat_id, "text": text, "parse_mode": "HTML",
                                   "disable_web_page_preview": "true"}).encode()
    req = urllib.request.Request(f"https://api.telegram.org/bot{token}/sendMessage", data=data)
    with urllib.request.urlopen(req, timeout=15) as res:
        reply = json.load(res)
    if not reply.get("ok"):
        raise RuntimeError(f"Telegram error: {reply}")


def logged_dates():
    if not os.path.exists(DB_PATH):
        return set()
    conn = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
    try:
        return {row[0] for row in conn.execute("SELECT DISTINCT date FROM sessions")}
    finally:
        conn.close()


def reminder_text(dates, today):
    """Return the reminder message, or None if today is already logged."""
    if today.isoformat() in dates:
        return None

    # Length of the streak that ends tonight if today is skipped.
    streak = 0
    day = today - datetime.timedelta(days=1)
    while day.isoformat() in dates:
        streak += 1
        day -= datetime.timedelta(days=1)

    if streak:
        head = f"🔥 <b>Your {streak}-day shadowing streak ends tonight!</b>"
        body = "No session logged today yet. A few reps keep it going."
    else:
        head = "🎧 <b>Time for today's shadowing</b>"
        body = "No session logged today. Even 5 minutes counts."
    return f"{head}\n{body}\n\n{APP_URL}"


def main():
    text = reminder_text(logged_dates(), datetime.date.today())
    if text is None:
        print("Session already logged today; no reminder.")
        return
    if "--dry-run" in sys.argv:
        print(text)
        return
    config = load_config()
    telegram_send(config["TELEGRAM_BOT_TOKEN"], config["TELEGRAM_CHAT_ID"], text)
    print("Reminder sent to Telegram.")


if __name__ == "__main__":
    main()
