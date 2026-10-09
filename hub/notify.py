"""Sending notifications: Telegram and Web Push, behind one Notifier.

Each channel is a small class with the same send(user_id, message) method, and
Notifier sends a message on every channel a user has set up. Adding a channel
(email, Zalo…) means adding one more class to Notifier.channels.

A Message is channel-neutral: a title, a body and a link.
"""
import base64
import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

from . import db

log = logging.getLogger(__name__)


@dataclass
class Message:
    title: str
    body: str
    url: str


# ---- Telegram -------------------------------------------------------------------

class TelegramError(Exception):
    pass


class TelegramAPI:
    """Minimal Bot API client (urllib only)."""

    def __init__(self, token):
        self.token = token

    def call(self, method, http_timeout=20, **params):
        data = urllib.parse.urlencode(params).encode()
        req = urllib.request.Request(f"https://api.telegram.org/bot{self.token}/{method}", data=data)
        try:
            with urllib.request.urlopen(req, timeout=http_timeout) as res:
                reply = json.load(res)
        except urllib.error.HTTPError as e:
            try:
                reply = json.load(e)
            except ValueError:
                raise TelegramError(f"{method}: HTTP {e.code}") from None
        if not reply.get("ok"):
            raise TelegramError(f"{method}: {reply.get('description', reply)}")
        return reply["result"]

    def send(self, chat_id, html_text):
        return self.call("sendMessage", chat_id=chat_id, text=html_text, parse_mode="HTML",
                         disable_web_page_preview="true")


def _escape(text):
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


class TelegramChannel:
    name = "telegram"

    def __init__(self, db_path, api):
        self.db_path = db_path
        self.api = api  # None when no bot token is configured

    @property
    def available(self):
        return self.api is not None

    def send(self, user_id, msg):
        if not self.api:
            return 0
        conn = db.connect(self.db_path)
        try:
            row = conn.execute("SELECT chat_id FROM telegram_links WHERE user_id = ?", (user_id,)).fetchone()
        finally:
            conn.close()
        if not row:
            return 0
        self.api.send(row["chat_id"], f"<b>{_escape(msg.title)}</b>\n{_escape(msg.body)}\n\n{_escape(msg.url)}")
        return 1


# ---- Web Push ---------------------------------------------------------------------

class PushChannel:
    """Web Push (VAPID). Keys are created on first start in DATA_DIR/vapid_private.pem."""

    name = "push"

    def __init__(self, db_path, data_dir, subject):
        self.db_path = db_path
        self.subject = subject
        self.vapid = None
        self.public_key = ""
        try:
            from py_vapid import Vapid01
            from cryptography.hazmat.primitives import serialization
        except ImportError as e:
            log.warning("web push disabled: %s", e)
            return
        path = os.path.join(data_dir, "vapid_private.pem")
        if not os.path.exists(path):
            v = Vapid01()
            v.generate_keys()
            v.save_key(path)
            os.chmod(path, 0o600)
        self.vapid = Vapid01.from_file(path)
        raw = self.vapid.public_key.public_bytes(serialization.Encoding.X962,
                                                 serialization.PublicFormat.UncompressedPoint)
        self.public_key = base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    @property
    def available(self):
        return self.vapid is not None

    def send(self, user_id, msg):
        if not self.vapid:
            return 0
        from pywebpush import WebPushException, webpush

        conn = db.connect(self.db_path)
        try:
            subs = conn.execute("SELECT id, endpoint, p256dh, auth FROM push_subscriptions WHERE user_id = ?",
                                (user_id,)).fetchall()
            payload = json.dumps({"title": msg.title, "body": msg.body, "url": msg.url})
            sent = 0
            for sub in subs:
                try:
                    webpush({"endpoint": sub["endpoint"], "keys": {"p256dh": sub["p256dh"], "auth": sub["auth"]}},
                            data=payload, vapid_private_key=self.vapid,
                            vapid_claims={"sub": self.subject}, ttl=6 * 3600, timeout=15)
                    sent += 1
                except WebPushException as e:
                    status = getattr(e.response, "status_code", None)
                    if status in (404, 410):  # the browser dropped this subscription
                        with conn:
                            conn.execute("DELETE FROM push_subscriptions WHERE id = ?", (sub["id"],))
                        log.info("removed expired push subscription %s", sub["id"])
                    else:
                        log.warning("push to subscription %s failed: %s", sub["id"], e)
            return sent
        finally:
            conn.close()


# ---- Facade -------------------------------------------------------------------------

class Notifier:
    def __init__(self, channels):
        self.channels = channels

    def channel(self, name):
        return next(c for c in self.channels if c.name == name)

    def send(self, user_id, msg):
        """Send on every channel the user has; returns {channel: count sent}."""
        result = {}
        for ch in self.channels:
            try:
                result[ch.name] = ch.send(user_id, msg)
            except Exception as e:
                log.warning("%s notification for user %s failed: %s", ch.name, user_id, e)
                result[ch.name] = 0
        return result
