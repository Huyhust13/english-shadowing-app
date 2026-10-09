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

from . import activity, db
from .notify import Message

log = logging.getLogger(__name__)
LATE_LIMIT = datetime.timedelta(hours=3)  # if the server was down longer than this, skip the day
NAMES = {"vocab": "vocab", "practice": "sentence practice", "shadow": "shadowing"}


def habit_status(conn, user_id, today, anki_days=None):
    """(habits left today, streak of days with every habit done)."""
    done = {"practice": set(activity.practice_days(conn, user_id)),
            "shadow": {d for d, reps in activity.shadow_days(conn, user_id).items() if reps}}
    if anki_days is not None:
        done["vocab"] = {d for d, n in anki_days.items() if n}
    left = [h for h in ("vocab", "practice", "shadow") if h in done and today.isoformat() not in done[h]]
    all_done = set.intersection(*done.values())
    return left, activity.streak(all_done, today)


def build_message(name, left, streak, url):
    todo = ", ".join(NAMES[h] for h in left)
    if streak:
        title = f"🔥 Your {streak}-day streak ends tonight"
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
        left, streak = habit_status(conn, user["id"], today, anki_days)
        if not left and not force:
            return {}
        if not left:
            msg = Message("✅ All done today", f"Nice work, {user['display_name']}! This is a test reminder.",
                          self.public_url + "/")
        else:
            msg = build_message(user["display_name"], left, streak, self.public_url + "/")
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
