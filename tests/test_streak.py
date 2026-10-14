import datetime

from hub import streak

TODAY = datetime.date(2026, 10, 14)


def iso(days_ago):
    return (TODAY - datetime.timedelta(days=days_ago)).isoformat()


def days(practice=(), shadow=(), vocab=None):
    """habit_days()-shaped dict from days-ago numbers."""
    out = {"practice": {iso(n) for n in practice}, "shadow": {iso(n) for n in shadow}}
    if vocab is not None:
        out["vocab"] = {iso(n) for n in vocab}
    return out


def perfect(*ago):
    return days(practice=ago, shadow=ago)


def test_today_not_done_counts_from_yesterday():
    s = streak.compute(days(practice=[1, 2, 3]), TODAY)
    assert (s["current"], s["todayStatus"], s["since"]) == (3, "at_risk", iso(3))
    s = streak.compute(days(practice=[0, 1, 2, 3]), TODAY)
    assert (s["current"], s["todayStatus"]) == (4, "done")
    assert streak.compute(days(), TODAY)["todayStatus"] == "none"


def test_one_habit_is_enough():
    s = streak.compute(days(practice=[0, 2], shadow=[1]), TODAY)
    assert s["current"] == 3 and s["perfect"] == []


def test_freeze_every_seventh_perfect_day_capped_at_two():
    s = streak.compute(perfect(*range(1, 7)), TODAY)
    assert (s["freezes"], s["nextFreezeIn"]) == (0, 1)
    s = streak.compute(perfect(*range(1, 8)), TODAY)
    assert (s["freezes"], s["perfectCount"]) == (1, 7)
    s = streak.compute(perfect(*range(1, 22)), TODAY)
    assert s["freezes"] == 2  # the third one is dropped


def test_freeze_covers_missed_day_without_growing():
    d = perfect(*range(3, 10))     # 7 perfect days -> 1 freeze
    d["practice"] |= {iso(1)}       # day 2 missed, day 1 only one habit
    s = streak.compute(d, TODAY)
    assert s["frozen"] == [iso(2)] and s["freezes"] == 0
    assert s["current"] == 8 and s["repaired"] == []


def test_two_freezes_cover_two_days_but_not_three():
    base = range(5, 19)  # 14 perfect days -> 2 freezes
    s = streak.compute(days(practice=[*base, 2], shadow=base), TODAY)  # days 3-4 missed
    assert s["frozen"] == [iso(4), iso(3)] and s["current"] == 15
    s = streak.compute(days(practice=[*base, 1], shadow=base), TODAY)  # days 2-4 missed
    assert s["current"] == 1 and s["longest"] == 14


def test_earn_back_with_a_perfect_next_day():
    d = days(practice=[1, 3, 4, 5], shadow=[1])  # day 2 missed, day 1 perfect
    s = streak.compute(d, TODAY)
    assert s["repaired"] == [iso(2)] and s["current"] == 4
    d = days(practice=[1, 3, 4, 5])               # day 1 only one habit: no earn back
    assert streak.compute(d, TODAY)["current"] == 1


def test_repair_pending_today():
    s = streak.compute(days(practice=[2, 3, 4]), TODAY)  # yesterday missed
    assert (s["current"], s["todayStatus"]) == (3, "repair")
    s = streak.compute(days(practice=[0, 2, 3, 4]), TODAY)  # one habit today isn't enough
    assert (s["current"], s["todayStatus"], s["milestone"]) == (4, "repair", None)
    s = streak.compute(days(practice=[0, 2, 3, 4], shadow=[0]), TODAY)
    assert s["repaired"] == [iso(1)] and (s["current"], s["todayStatus"]) == (4, "done")
    tomorrow = streak.compute(days(practice=[-1, 0, 2, 3, 4]), TODAY + datetime.timedelta(days=1))
    assert tomorrow["current"] == 2  # not earned back: the old streak ended


def test_two_missed_days_cannot_be_earned_back():
    s = streak.compute(days(practice=[0, 3, 4, 5], shadow=[0]), TODAY)
    assert s["current"] == 1 and s["repaired"] == []


def test_freeze_is_used_before_earn_back():
    d = perfect(0, *range(2, 9))  # 7 perfect days, day 1 missed, perfect today
    s = streak.compute(d, TODAY)
    assert s["frozen"] == [iso(1)] and s["repaired"] == [] and s["freezes"] == 0


def test_vocab_needed_only_from_first_anki_day():
    d = perfect(1, 2, 3)
    d["vocab"] = {iso(1)}
    s = streak.compute(d, TODAY)
    assert s["perfect"] == [iso(3), iso(2), iso(1)]
    d["vocab"] = {iso(3)}
    assert streak.compute(d, TODAY)["perfect"] == [iso(3)]
    assert streak.compute(d, TODAY)["perHabit"] == {"vocab": 0, "practice": 3, "shadow": 3}


def test_backfill_rejoins_the_streak():
    d = days(practice=[1, 2, 4, 5, 6], shadow=[])
    d["shadow"] = {iso(1)}
    assert streak.compute(d, TODAY)["current"] == 2  # day 3 missed, day 2 not perfect
    d["practice"].add(iso(3))
    assert streak.compute(d, TODAY)["current"] == 6


def test_milestones():
    assert [streak.next_milestone(n) for n in (0, 7, 20, 21, 90, 100, 250)] == [7, 21, 21, 90, 100, 200, 300]
    assert [n for n in range(1, 401) if streak.is_milestone(n)] == [7, 21, 90, 100, 200, 300, 400]
    s = streak.compute(days(practice=range(0, 7)), TODAY)
    assert s["milestone"] == 7 and s["nextMilestone"] == 21
    assert streak.compute(days(practice=range(1, 8)), TODAY)["milestone"] is None


def test_consecutive():
    dates = {iso(1), iso(2), iso(3)}
    assert streak.consecutive(dates, TODAY) == 3
    assert streak.consecutive(dates | {iso(0)}, TODAY) == 4
    assert streak.consecutive({iso(2)}, TODAY) == 0


def test_reminder_message_branches():
    from hub import reminders
    msg = lambda d: reminders.build_message("Lan", ["shadow"], streak.compute(d, TODAY), "/")
    assert "Save your 3-day streak" in msg(days(practice=[2, 3, 4])).title
    assert "ends tonight" in msg(days(practice=[1, 2])).title
    assert "freeze" in msg(perfect(*range(1, 8))).body
    assert "is safe" in msg(days(practice=[0, 1])).title
    assert "Time for" in msg(days()).title
