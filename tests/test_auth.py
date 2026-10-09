from conftest import login
from hub import users


def test_pages_and_api_need_login(app):
    c = app.test_client()
    assert c.get("/").status_code == 302
    assert c.get("/").headers["Location"].startswith("/login")
    assert c.get("/api/sessions").status_code == 401
    assert c.get("/login").status_code == 200


def test_login_logout(app, make_user):
    make_user("huy")
    c = app.test_client()
    assert login(c, "huy", "wrong-password").status_code == 401
    assert login(c, "HUY").status_code == 200  # usernames are case-insensitive
    assert c.get("/api/me").get_json()["username"] == "huy"
    c.post("/api/auth/logout")
    assert c.get("/api/me").status_code == 401


def test_login_rate_limit(app, make_user):
    make_user("huy")
    c = app.test_client()
    for _ in range(8):
        login(c, "huy", "nope-nope")
    assert login(c, "huy").status_code == 429


def test_invite_flow(app, conn, make_user):
    admin = make_user("huy", admin=True)
    token = users.create_link(conn, "invite", admin, note="Lan")
    c = app.test_client()
    assert c.get(f"/api/auth/link/{token}").get_json()["kind"] == "invite"
    r = c.post(f"/api/auth/link/{token}", json={"username": "lan", "displayName": "Lan",
                                               "password": "short", "timezone": "Europe/Berlin"})
    assert r.status_code == 400  # bad password; the link must still work afterwards
    r = c.post(f"/api/auth/link/{token}", json={"username": "lan", "displayName": "Lan",
                                               "password": "longenough", "timezone": "Europe/Berlin"})
    assert r.status_code == 200 and r.get_json()["next"].startswith("/settings")
    me = c.get("/api/me").get_json()
    assert me["username"] == "lan" and me["timezone"] == "Europe/Berlin" and not me["isAdmin"]
    # one-time
    assert app.test_client().post(f"/api/auth/link/{token}", json={"username": "x2", "password": "longenough"}).status_code == 400


def test_password_change_logs_out_other_devices(app, make_user):
    make_user("huy")
    a, b = app.test_client(), app.test_client()
    login(a, "huy"), login(b, "huy")
    assert a.post("/api/me/password", json={"current": "password123", "new": "newpassword1"}).status_code == 200
    assert a.get("/api/me").status_code == 200
    assert b.get("/api/me").status_code == 401


def test_reset_link(app, conn, make_user):
    uid = make_user("lan")
    token = users.create_link(conn, "reset", None, user_id=uid)
    c = app.test_client()
    assert c.get(f"/api/auth/link/{token}").get_json() == {"kind": "reset", "username": "lan",
                                                           "defaultTimezone": "Asia/Ho_Chi_Minh"}
    assert c.post(f"/api/auth/link/{token}", json={"password": "brandnew99"}).status_code == 200
    assert login(app.test_client(), "lan", "brandnew99").status_code == 200


def test_cross_site_writes_refused(app, make_user):
    make_user("huy")
    c = app.test_client()
    login(c, "huy")
    r = c.post("/api/sessions", json={}, headers={"Sec-Fetch-Site": "cross-site"})
    assert r.status_code == 403
    r = c.post("/api/sessions", json={}, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403
    r = c.put("/api/practice/2026-10-10", json={"done": True}, headers={"Origin": "https://hub.example"})
    assert r.status_code == 200


def test_admin_only(app, make_user):
    make_user("huy", admin=True)
    make_user("lan")
    c = app.test_client()
    login(c, "lan")
    assert c.get("/api/admin/users").status_code == 403
    assert c.get("/admin").status_code == 302
    c2 = app.test_client()
    login(c2, "huy")
    assert c2.post("/api/admin/invites", json={"note": "Minh"}).get_json()["url"].startswith("https://hub.example/join/")
    assert [u["username"] for u in c2.get("/api/admin/users").get_json()] == ["huy", "lan"]


def test_deactivated_user_is_logged_out(app, make_user):
    make_user("huy", admin=True)
    lan = make_user("lan")
    a, b = app.test_client(), app.test_client()
    login(a, "huy"), login(b, "lan")
    assert a.put(f"/api/admin/users/{lan}/active", json={"active": False}).status_code == 200
    assert b.get("/api/me").status_code == 401
    assert login(b, "lan").status_code == 401
