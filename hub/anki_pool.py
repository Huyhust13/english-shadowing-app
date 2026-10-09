"""Keeps one open AnkiService per active user, and syncs them in the background.

Opening an Anki collection costs memory and a little time, so collections are
opened on first use (a request or a reminder check) and closed again after
IDLE_CLOSE seconds without use. One background thread walks the open collections
every few seconds and syncs the ones that are due (periodic, after reviews, or
after adding a card).
"""
import logging
import os
import threading
import time

from . import db

log = logging.getLogger(__name__)

try:
    from . import anki_service
    IMPORT_ERROR = ""
except ImportError as e:  # the app still works, just without Vocab
    anki_service = None
    IMPORT_ERROR = str(e)

IDLE_CLOSE = 30 * 60
TICK = 10


class AccountStore:
    """A user's AnkiWeb login (session key, not the password) in the anki_accounts table."""

    def __init__(self, db_path, user_id):
        self.db_path = db_path
        self.user_id = user_id

    def load(self):
        conn = db.connect(self.db_path)
        try:
            row = conn.execute("SELECT username, hkey, endpoint FROM anki_accounts WHERE user_id = ?",
                               (self.user_id,)).fetchone()
        finally:
            conn.close()
        return dict(row) if row and row["hkey"] else None

    def save(self, hkey, endpoint, username):
        conn = db.connect(self.db_path)
        try:
            with conn:
                conn.execute(
                    "INSERT INTO anki_accounts (user_id, username, hkey, endpoint) VALUES (?, ?, ?, ?)"
                    " ON CONFLICT(user_id) DO UPDATE SET username = excluded.username, hkey = excluded.hkey,"
                    " endpoint = excluded.endpoint",
                    (self.user_id, username or "", hkey, endpoint or ""))
        finally:
            conn.close()

    def clear(self):
        conn = db.connect(self.db_path)
        try:
            with conn:
                conn.execute("DELETE FROM anki_accounts WHERE user_id = ?", (self.user_id,))
        finally:
            conn.close()


class AnkiPool:
    def __init__(self, db_path, users_dir):
        self.db_path = db_path
        self.users_dir = users_dir
        self.available = anki_service is not None
        self.error = IMPORT_ERROR
        self._services = {}
        self._lock = threading.Lock()
        self._stop = threading.Event()

    def collection_dir(self, user_id):
        return os.path.join(self.users_dir, str(int(user_id)), "anki")

    def get(self, user_id):
        """The user's AnkiService, opening the collection if needed."""
        if not self.available:
            raise RuntimeError("Anki is not available: " + self.error)
        with self._lock:
            svc = self._services.get(user_id)
            if svc is None:
                svc = anki_service.AnkiService(self.collection_dir(user_id), AccountStore(self.db_path, user_id))
                self._services[user_id] = svc
                log.info("opened Anki collection for user %s", user_id)
            svc.last_used = time.time()
            return svc

    def is_connected(self, user_id):
        return AccountStore(self.db_path, user_id).load() is not None

    def start(self):
        threading.Thread(target=self._loop, name="anki-pool", daemon=True).start()

    def _loop(self):
        while not self._stop.wait(TICK):
            with self._lock:
                items = list(self._services.items())
            now = time.time()
            for user_id, svc in items:
                try:
                    if now - svc.last_used > IDLE_CLOSE and not svc.busy():
                        self._close(user_id, svc)
                    elif svc.sync_due(now) and svc.auth():
                        svc.background_sync()
                except Exception:
                    log.exception("Anki maintenance failed for user %s", user_id)

    def _close(self, user_id, svc):
        with self._lock:  # get() updates last_used under the same lock, so re-check here
            if self._services.get(user_id) is not svc or time.time() - svc.last_used <= IDLE_CLOSE:
                return
            del self._services[user_id]
        svc.close()
        log.info("closed idle Anki collection for user %s", user_id)

    def drop(self, user_id):
        """Close a user's collection now (e.g. their account was deactivated)."""
        with self._lock:
            svc = self._services.pop(user_id, None)
        if svc:
            svc.close()

    def close_all(self):
        self._stop.set()
        with self._lock:
            items, self._services = list(self._services.values()), {}
        for svc in items:
            try:
                svc.close()
            except Exception:
                log.exception("closing Anki collection failed")
