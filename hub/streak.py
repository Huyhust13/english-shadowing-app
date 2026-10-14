"""Streak maths, modelled on Duolingo's streak.

- A streak day is any day with at least one habit done.
- A perfect day has every habit done (vocab only counts from the first day with Anki
  reviews, so connecting Anki later doesn't change the past).
- Every 7th perfect day earns a freeze; you hold at most 2. A missed day uses one
  automatically: the streak survives but doesn't grow.
- Earn back: with no freeze left, a missed day is forgiven if the next day is perfect.
- Today not being done yet never breaks the streak; it only ends after midnight.

Everything is recomputed from the history on each call, so editing or back-filling a
day simply changes the answer. Dates are ISO strings in the person's own timezone.
"""
import datetime

from . import activity

HABITS = ("vocab", "practice", "shadow")
MAX_FREEZES = 2
FREEZE_EVERY = 7  # perfect days per freeze
DAY = datetime.timedelta(days=1)


def is_milestone(n):
    return n in (7, 21, 90) or (n >= 100 and n % 100 == 0)


def next_milestone(n):
    for m in (7, 21, 90):
        if n < m:
            return m
    return (n // 100 + 1) * 100


def consecutive(dates, today):
    """Days in a row ending today (or yesterday, if today isn't done yet). No freezes."""
    day = today if today.isoformat() in dates else today - DAY
    n = 0
    while day.isoformat() in dates:
        n += 1
        day -= DAY
    return n


def habit_days(conn, user_id, anki_days=None):
    """{habit: set of ISO dates it was done}; vocab only when Anki is connected (anki_days not None)."""
    days = {"practice": set(activity.practice_days(conn, user_id)),
            "shadow": {d for d, reps in activity.shadow_days(conn, user_id).items() if reps}}
    if anki_days is not None:
        days["vocab"] = {d for d, n in anki_days.items() if n}
    return days


def compute(days, today):
    """The streak state for habit_days() as of `today` (a date)."""
    done = {}
    for habit, dates in days.items():
        for d in dates:
            done.setdefault(d, set()).add(habit)
    vocab_since = min(days["vocab"]) if days.get("vocab") else None

    def is_perfect(d):
        iso = d.isoformat()
        need = {"practice", "shadow"} | ({"vocab"} if vocab_since and iso >= vocab_since else set())
        return need <= done.get(iso, set())

    current = longest = perfect_count = freezes = 0
    since, repair = None, False
    frozen, repaired, perfect = [], [], []
    first = min((datetime.date.fromisoformat(d) for d in done), default=today)
    day = min(first, today)
    while day <= today:
        iso = day.isoformat()
        if done.get(iso):
            if current == 0:
                since = iso
            current += 1
            if is_perfect(day):
                perfect.append(iso)
                perfect_count += 1
                if perfect_count % FREEZE_EVERY == 0:
                    freezes = min(MAX_FREEZES, freezes + 1)
        elif day == today or current == 0:
            pass  # today is still open; with no streak there's nothing to protect
        elif freezes:
            freezes -= 1
            frozen.append(iso)
        elif is_perfect(day + DAY):
            repaired.append(iso)
        elif day + DAY == today:
            repair = True  # yesterday was missed: a perfect day today saves the streak
        else:
            current, since = 0, None
        longest = max(longest, current)
        day += DAY

    today_iso = today.isoformat()
    if repair:
        status = "repair"  # even with some habits done: only a perfect day saves it
    elif done.get(today_iso):
        status = "done"
    else:
        status = "at_risk" if current else "none"
    return {
        "today": today_iso,
        "current": current,
        "longest": longest,
        "since": since,
        "todayStatus": status,
        "freezes": freezes,
        "perfectCount": perfect_count,
        "nextFreezeIn": FREEZE_EVERY - perfect_count % FREEZE_EVERY,
        "frozen": frozen,
        "repaired": repaired,
        "perfect": perfect,
        "nextMilestone": next_milestone(current),
        "milestone": current if status == "done" and is_milestone(current) else None,
        "perHabit": {h: consecutive(days[h], today) for h in HABITS if h in days},
    }
