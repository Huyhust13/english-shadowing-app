"""Shadowing sessions and practice ticks for one person, plus streak maths.

Every query is scoped by user_id; there is no function here that reads across
users. Dates are 'YYYY-MM-DD' strings in the person's own calendar (the browser
sends them; the reminder computes them in the user's timezone).
"""
import datetime
import re

COLUMNS = ("date", "loggedAt", "clipTitle", "clipUrl", "reps", "confidence", "notes")
DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


def valid_date(date):
    if not isinstance(date, str) or not DATE_RE.fullmatch(date):
        return False
    try:
        datetime.date.fromisoformat(date)
    except ValueError:
        return False
    return True


def clean_session(s):
    """Validate one session dict from the client; raises ValueError if bad."""
    if not isinstance(s, dict):
        raise ValueError("session must be an object")
    date, logged_at = s.get("date"), s.get("loggedAt")
    if not valid_date(date):
        raise ValueError("bad date")
    if not isinstance(logged_at, str) or not 0 < len(logged_at) <= 40:
        raise ValueError("bad loggedAt")
    conf = s.get("confidence")
    if conf not in (None, 1, 2, 3):
        raise ValueError("bad confidence")
    return (
        date,
        logged_at,
        str(s.get("clipTitle") or "")[:500],
        str(s.get("clipUrl") or "")[:2000],
        max(1, min(int(s.get("reps") or 1), 1000)),
        conf,
        str(s.get("notes") or "")[:200000],
    )


# ---- Shadowing ------------------------------------------------------------------

def list_sessions(conn, user_id):
    rows = conn.execute(
        "SELECT id, " + ", ".join(COLUMNS) + " FROM sessions WHERE user_id = ? ORDER BY date, loggedAt",
        (user_id,)).fetchall()
    return [dict(r) for r in rows]


def add_sessions(conn, user_id, sessions):
    rows = [(user_id, *clean_session(s)) for s in sessions]
    with conn:
        conn.executemany(
            "INSERT OR IGNORE INTO sessions (user_id, " + ", ".join(COLUMNS) + ") VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            rows)


def update_session(conn, user_id, session_id, data):
    row = clean_session(data)
    with conn:
        cur = conn.execute(
            "UPDATE sessions SET " + ", ".join(f"{c} = ?" for c in COLUMNS) + " WHERE id = ? AND user_id = ?",
            (*row, session_id, user_id))
    return cur.rowcount == 1


def delete_session(conn, user_id, session_id):
    with conn:
        cur = conn.execute("DELETE FROM sessions WHERE id = ? AND user_id = ?", (session_id, user_id))
    return cur.rowcount == 1


# ---- Practice ---------------------------------------------------------------------

def set_practice(conn, user_id, date, done, note=""):
    if not valid_date(date):
        raise ValueError("bad date")
    with conn:
        if done:
            conn.execute(
                "INSERT INTO practice_days (user_id, date, note, markedAt) VALUES (?, ?, ?, datetime('now'))"
                " ON CONFLICT(user_id, date) DO UPDATE SET note = excluded.note",
                (user_id, date, str(note or "")[:200000]))
        else:
            conn.execute("DELETE FROM practice_days WHERE user_id = ? AND date = ?", (user_id, date))


# ---- Summary & streaks ---------------------------------------------------------------

def shadow_days(conn, user_id):
    return {r["date"]: r["reps"] for r in conn.execute(
        "SELECT date, SUM(reps) AS reps FROM sessions WHERE user_id = ? GROUP BY date", (user_id,))}


def practice_days(conn, user_id):
    return {r["date"]: r["note"] for r in conn.execute(
        "SELECT date, note FROM practice_days WHERE user_id = ?", (user_id,))}


def streak(done_dates, today):
    """Consecutive days ending today (or yesterday, if today isn't done yet)."""
    day = today if today.isoformat() in done_dates else today - datetime.timedelta(days=1)
    n = 0
    while day.isoformat() in done_dates:
        n += 1
        day -= datetime.timedelta(days=1)
    return n


def export(conn, user_id):
    return {
        "exportedAt": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
        "sessions": list_sessions(conn, user_id),
        "practice": [dict(r) for r in conn.execute(
            "SELECT date, note, markedAt FROM practice_days WHERE user_id = ? ORDER BY date", (user_id,))],
    }
