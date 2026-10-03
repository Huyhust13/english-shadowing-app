#!/usr/bin/env python3
"""One-time setup: connect the reminder to your Telegram bot.

1. In Telegram, open @BotFather, send /newbot and follow the steps.
   It gives you a bot token like 123456789:AA...
2. Run this script and paste the token when asked (input is hidden).
3. Open your new bot in Telegram and send it any message (e.g. /start).

The script finds your chat id, saves both to
~/.config/shadowing-tracker/telegram.env (readable only by you),
and sends a test message.
"""
import getpass
import json
import os
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from remind import CONFIG_PATH, telegram_send  # noqa: E402


def api(token, method, **params):
    query = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"https://api.telegram.org/bot{token}/{method}" + (f"?{query}" if query else "")
    try:
        with urllib.request.urlopen(url, timeout=40) as res:
            return json.load(res)
    except urllib.error.HTTPError as e:
        return json.load(e)


def main():
    token = getpass.getpass("Paste your bot token from @BotFather (hidden): ").strip()
    me = api(token, "getMe")
    if not me.get("ok"):
        sys.exit("That token didn't work. Copy it again from @BotFather.")
    username = me["result"]["username"]

    print(f"\nToken OK — bot is @{username}.")
    print(f"Now open https://t.me/{username} on your phone, tap Start (or send any message).")
    print("Waiting for your message (up to 3 minutes)...")

    offset = 0
    deadline = time.time() + 180
    chat = None
    while time.time() < deadline and chat is None:
        updates = api(token, "getUpdates", timeout=25, offset=offset)
        for update in updates.get("result", []):
            offset = update["update_id"] + 1
            message = update.get("message") or update.get("edited_message")
            if message and message.get("chat", {}).get("type") == "private":
                chat = message["chat"]
    if chat is None:
        sys.exit("No message received. Run the script again and message the bot.")
    api(token, "getUpdates", offset=offset)  # mark the message as read

    os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
    fd = os.open(CONFIG_PATH, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        f.write(f"TELEGRAM_BOT_TOKEN={token}\nTELEGRAM_CHAT_ID={chat['id']}\n")
    os.chmod(CONFIG_PATH, 0o600)

    telegram_send(token, chat["id"],
                  "✅ Shadowing Tracker is connected. I'll message you here on days you haven't practised.")
    print(f"\nConnected to {chat.get('first_name', 'your chat')}. Saved to {CONFIG_PATH}")
    print("A test message was sent — check Telegram.")


if __name__ == "__main__":
    main()
