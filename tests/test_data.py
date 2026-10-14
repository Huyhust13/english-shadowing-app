import datetime

from conftest import login
from hub import activity, reminders
from hub.notify import Message

SESSION = {"date": "2026-10-09", "loggedAt": "2026-10-09T10:00:00Z", "clipTitle": "TED", "reps": 3}


def test_each_user_sees_only_their_own_log(app, make_user):
    make_user("huy"), make_user("lan")
    a, b = app.test_client(), app.test_client()
    login(a, "huy"), login(b, "lan")
    assert a.post("/api/sessions", json=SESSION).status_code == 201
    assert b.post("/api/sessions", json=SESSION).status_code == 201  # same loggedAt is fine across users
    a_sessions = a.get("/api/sessions").get_json()
    assert len(a_sessions) == 1 and len(b.get("/api/sessions").get_json()) == 1
    sid = a_sessions[0]["id"]
    # lan can't touch huy's session
    assert b.put(f"/api/sessions/{sid}", json=SESSION).status_code == 404
    assert b.delete(f"/api/sessions/{sid}").status_code == 404
    assert a.delete(f"/api/sessions/{sid}").status_code == 200
    a.put("/api/practice/2026-10-09", json={"done": True, "note": "hi"})
    assert a.get("/api/summary").get_json()["practice"] == {"2026-10-09": "hi"}
    assert b.get("/api/summary").get_json()["practice"] == {}
    summary = a.get("/api/summary").get_json()
    assert summary["today"] == summary["streak"]["today"] and "current" in summary["streak"]


def test_bad_input(app, make_user):
    make_user("huy")
    c = app.test_client()
    login(c, "huy")
    assert c.post("/api/sessions", json=dict(SESSION, date="2026-13-45")).status_code == 400
    assert c.put("/api/practice/nope", json={"done": True}).status_code == 400
    assert c.get("/api/title?url=http://127.0.0.1/").status_code == 400
    assert c.get("/api/title?url=http://192.168.10.21:8090/").status_code == 400
    assert c.get("/api/title?url=file:///etc/passwd").status_code == 400


def test_reminder_runs_once_at_local_time(app, conn, make_user):
    uid = make_user("lan")
    conn.execute("UPDATE users SET timezone = 'Europe/Berlin', reminder_time = '20:00' WHERE id = ?", (uid,))
    conn.commit()
    svc = app.extensions["hub"].reminders
    sent = []
    svc.notifier.send = lambda user_id, msg: sent.append((user_id, msg)) or {}
    berlin_1959 = datetime.datetime(2026, 10, 10, 17, 59, tzinfo=datetime.timezone.utc)  # 19:59 CEST
    svc.run_once(berlin_1959)
    assert sent == []
    svc.run_once(berlin_1959 + datetime.timedelta(minutes=1))
    assert len(sent) == 1 and isinstance(sent[0][1], Message)
    assert "shadowing" in sent[0][1].body and "vocab" not in sent[0][1].body  # no Anki connected
    svc.run_once(berlin_1959 + datetime.timedelta(minutes=5))
    assert len(sent) == 1  # once a day


def test_no_reminder_when_done(app, conn, make_user):
    uid = make_user("huy")
    activity.add_sessions(conn, uid, [dict(SESSION, date="2026-10-10")])
    activity.set_practice(conn, uid, "2026-10-10", True)
    left, state = reminders.habit_status(conn, uid, datetime.date(2026, 10, 10))
    assert left == [] and state["current"] == 1 and state["perfect"] == ["2026-10-10"]


def test_pages_served(app, make_user):
    make_user("huy")
    c = app.test_client()
    login(c, "huy")
    for path in ("/", "/practice", "/shadowing", "/guide", "/settings", "/static/editor.js", "/static/editor.css"):
        assert c.get(path).status_code == 200, path


def test_long_rich_practice_note(app, make_user):
    make_user("huy")
    c = app.test_client()
    login(c, "huy")
    note = "<b>I have lived</b> here <mark>since</mark> 2020.<br>" * 2000  # ~70 KB
    assert c.put("/api/practice/2026-10-10", json={"done": True, "note": note}).status_code == 200
    assert c.get("/api/summary").get_json()["practice"]["2026-10-10"] == note
