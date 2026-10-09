"""The Telegram bot's inbox: links chats to accounts.

Linking works without anyone typing a code:
1. On Settings, "Connect Telegram" creates a one-time token and opens
   https://t.me/<bot>?start=<token>.
2. Telegram shows a Start button; pressing it sends "/start <token>" to the bot.
3. This poller sees the message, finds the token, and saves the chat id for that user.

It long-polls getUpdates in a background thread (no webhook, so nothing extra has
to be reachable from the internet). The update offset is kept in app_state so a
restart doesn't replay old messages.
"""
import datetime
import logging
import secrets
import threading

from . import db
from .notify import TelegramError

log = logging.getLogger(__name__)
LINK_MINUTES = 15


def create_link_token(conn, user_id):
    token = secrets.token_urlsafe(16)
    expires = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(minutes=LINK_MINUTES))
    with conn:
        conn.execute("DELETE FROM telegram_link_tokens WHERE user_id = ? OR expires_at < datetime('now')", (user_id,))
        conn.execute("INSERT INTO telegram_link_tokens (token, user_id, expires_at) VALUES (?, ?, ?)",
                     (token, user_id, expires.strftime("%Y-%m-%d %H:%M:%S")))
    return token


def unlink(conn, user_id):
    with conn:
        conn.execute("DELETE FROM telegram_links WHERE user_id = ?", (user_id,))


class TelegramBot:
    def __init__(self, db_path, api, public_url):
        self.db_path = db_path
        self.api = api
        self.public_url = public_url
        self.username = ""
        self._stop = threading.Event()

    def start(self):
        threading.Thread(target=self._loop, name="telegram-bot", daemon=True).start()

    def stop(self):
        self._stop.set()

    def _loop(self):
        while not self.username and not self._stop.is_set():
            try:
                self.username = self.api.call("getMe")["username"]
                log.info("Telegram bot is @%s", self.username)
            except Exception as e:
                log.warning("Telegram getMe failed (%s); retrying in a minute", e)
                self._stop.wait(60)
        while not self._stop.is_set():
            try:
                self.poll_once()
            except Exception as e:
                log.warning("Telegram polling failed: %s", e)
                self._stop.wait(30)

    def poll_once(self, timeout=25):
        conn = db.connect(self.db_path)
        try:
            offset = int(db.get_state(conn, "telegram_offset", "0"))
        finally:
            conn.close()
        updates = self.api.call("getUpdates", http_timeout=timeout + 10, offset=offset, timeout=timeout)
        for update in updates:
            offset = update["update_id"] + 1
            try:
                self.handle(update)
            except Exception:
                log.exception("handling Telegram update failed")
        if updates:
            conn = db.connect(self.db_path)
            try:
                with conn:
                    db.set_state(conn, "telegram_offset", offset)
            finally:
                conn.close()

    def handle(self, update):
        msg = update.get("message") or {}
        chat = msg.get("chat") or {}
        text = (msg.get("text") or "").strip()
        if chat.get("type") != "private" or not text:
            return
        chat_id = chat["id"]
        if text.startswith("/start"):
            token = text[len("/start"):].strip()
            self.reply(chat_id, self.link(chat_id, token, chat.get("first_name", "")) if token else
                       "👋 This is the English Hub reminder bot.\n"
                       f"To connect, open {self.public_url}/settings and press <b>Connect Telegram</b>.")
        elif text.startswith("/stop"):
            conn = db.connect(self.db_path)
            try:
                with conn:
                    cur = conn.execute("DELETE FROM telegram_links WHERE chat_id = ?", (chat_id,))
            finally:
                conn.close()
            self.reply(chat_id, "🔕 Disconnected. You won't get reminders here any more." if cur.rowcount
                       else "This chat isn't connected to an English Hub account.")
        else:
            self.reply(chat_id, f"I only send reminders. Settings: {self.public_url}/settings")

    def link(self, chat_id, token, name):
        conn = db.connect(self.db_path)
        try:
            row = conn.execute(
                "SELECT t.user_id, u.display_name FROM telegram_link_tokens t JOIN users u ON u.id = t.user_id"
                " WHERE t.token = ? AND t.expires_at > datetime('now') AND u.is_active = 1", (token,)).fetchone()
            if not row:
                return "⚠️ That link has expired. Go back to Settings and press <b>Connect Telegram</b> again."
            with conn:
                conn.execute("DELETE FROM telegram_link_tokens WHERE token = ?", (token,))
                # One chat belongs to one account.
                conn.execute("DELETE FROM telegram_links WHERE chat_id = ?", (chat_id,))
                conn.execute(
                    "INSERT INTO telegram_links (user_id, chat_id, name) VALUES (?, ?, ?)"
                    " ON CONFLICT(user_id) DO UPDATE SET chat_id = excluded.chat_id, name = excluded.name,"
                    " linked_at = datetime('now')", (row["user_id"], chat_id, str(name)[:100]))
            log.info("linked Telegram chat for user %s", row["user_id"])
            return (f"✅ Connected, {row['display_name']}! I'll remind you here on days you haven't "
                    "finished your English practice. Send /stop to disconnect.")
        finally:
            conn.close()

    def reply(self, chat_id, text):
        try:
            self.api.send(chat_id, text)
        except TelegramError as e:
            log.warning("Telegram reply failed: %s", e)
