"""Daily reminders, at each person's own time and timezone.

A background thread wakes once a minute. For every active user with reminders on,
once their local clock passes their reminder time, it checks today's habits and,
if any are left, sends one message on every channel they've set up (Telegram,
Web Push). reminder_last_date records that today has been handled, so each person
gets at most one reminder a day, and a restart doesn't send it twice.

Habits counted: practice and shadowing always; vocab (Anki reviews) only for people
who connected an AnkiWeb account.
"""
import datetime
import logging
import threading
import zoneinfo

from . import db, streak
from .notify import Message

log = logging.getLogger(__name__)
LATE_LIMIT = datetime.timedelta(hours=3)  # if the server was down longer than this, skip the day
NAMES = {"vocab": "vocab", "practice": "sentence practice", "shadow": "shadowing"}


def habit_status(conn, user_id, today, anki_days=None):
    """(habits left today, streak state from streak.compute)."""
    days = streak.habit_days(conn, user_id, anki_days)
    left = [h for h in streak.HABITS if h in days and today.isoformat() not in days[h]]
    return left, streak.compute(days, today)


def build_message(name, left, state, url):
    todo = ", ".join(NAMES[h] for h in left)
    n, status = state["current"], state["todayStatus"]
    if status == "repair":
        title = f"⚠️ Save your {n}-day streak today"
        body = f"Hi {name}, you missed yesterday. Do every habit today to earn it back: {todo}."
    elif status == "done":
        title = f"🔥 {n}-day streak is safe"
        body = f"Hi {name}, today already counts. Still open if you want a perfect day: {todo}."
    elif n and state["freezes"]:
        title = f"🔥 Keep your {n}-day streak going"
        body = f"Hi {name}, still to do today: {todo}. A ❄️ freeze will cover today if you can't."
    elif n:
        title = f"🔥 Your {n}-day streak ends tonight"
        body = f"Hi {name}, still to do today: {todo}. A few minutes keeps it going."
    else:
        title = "🎧 Time for today's English practice"
        body = f"Hi {name}, still to do today: {todo}. Even 5 minutes counts."
    return Message(title, body, url)


class ReminderService:
    def __init__(self, db_path, pool, notifier, public_url):
        self.db_path = db_path
        self.pool = pool
        self.notifier = notifier
        self.public_url = public_url
        self._stop = threading.Event()

    def start(self):
        threading.Thread(target=self._loop, name="reminders", daemon=True).start()

    def stop(self):
        self._stop.set()

    def _loop(self):
        while not self._stop.wait(60 - datetime.datetime.now().second):
            try:
                self.run_once(datetime.datetime.now(datetime.timezone.utc))
            except Exception:
                log.exception("reminder run failed")

    def run_once(self, now_utc):
        conn = db.connect(self.db_path)
        try:
            users = conn.execute(
                "SELECT id, display_name, timezone, reminder_time, reminder_last_date FROM users"
                " WHERE is_active = 1 AND reminder_enabled = 1").fetchall()
            for user in users:
                try:
                    self._check_user(conn, user, now_utc)
                except Exception:
                    log.exception("reminder for user %s failed", user["id"])
        finally:
            conn.close()

    def _check_user(self, conn, user, now_utc):
        local = now_utc.astimezone(zoneinfo.ZoneInfo(user["timezone"]))
        today = local.date()
        if user["reminder_last_date"] == today.isoformat():
            return
        hour, minute = map(int, user["reminder_time"].split(":"))
        due_at = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if local < due_at:
            return
        if local - due_at <= LATE_LIMIT:
            self.remind(conn, user, today)
        with conn:
            conn.execute("UPDATE users SET reminder_last_date = ? WHERE id = ?", (today.isoformat(), user["id"]))

    def remind(self, conn, user, today, force=False):
        """Send today's reminder if anything is left (or always, with force). Returns what was sent."""
        anki_days = self._anki_days(user)
        left, state = habit_status(conn, user["id"], today, anki_days)
        if not left and not force:
            return {}
        if not left:
            msg = Message("✅ All done today", f"Nice work, {user['display_name']}! This is a test reminder.",
                          self.public_url + "/")
        else:
            msg = build_message(user["display_name"], left, state, self.public_url + "/")
        sent = self.notifier.send(user["id"], msg)
        log.info("reminder for user %s: left=%s sent=%s", user["id"], left, sent)
        return sent

    def _anki_days(self, user):
        """Review counts per local day, after a sync so phone/desktop reviews count; None if no Anki."""
        if not self.pool.available or not self.pool.is_connected(user["id"]):
            return None
        svc = self.pool.get(user["id"])
        svc.sync()
        return svc.review_days(zoneinfo.ZoneInfo(user["timezone"]))
