"""The logged-in person's own account: profile, reminder settings, Telegram, push, export."""
import datetime
import json
import zoneinfo

from flask import Blueprint, Response, g, jsonify, request

from .. import activity, services, telegram_bot, users
from ..db import get_db
from ..security import login_required, log_in, log_out

bp = Blueprint("me", __name__, url_prefix="/api/me")


def _data():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


@bp.before_request
@login_required
def _guard():
    return None


@bp.get("")
def me():
    conn, u, svc = get_db(), g.user, services()
    tg = conn.execute("SELECT name, linked_at FROM telegram_links WHERE user_id = ?", (u["id"],)).fetchone()
    devices = conn.execute("SELECT COUNT(*) FROM push_subscriptions WHERE user_id = ?", (u["id"],)).fetchone()[0]
    anki = conn.execute("SELECT username FROM anki_accounts WHERE user_id = ?", (u["id"],)).fetchone()
    return jsonify(
        id=u["id"], username=u["username"], displayName=u["display_name"], isAdmin=bool(u["is_admin"]),
        timezone=u["timezone"],
        reminder={"enabled": bool(u["reminder_enabled"]), "time": u["reminder_time"]},
        telegram={"available": svc.bot is not None, "bot": svc.bot.username if svc.bot else "",
                  "linked": tg is not None, "name": tg["name"] if tg else ""},
        push={"available": svc.push.available, "publicKey": svc.push.public_key, "devices": devices},
        anki={"available": svc.pool.available, "connected": anki is not None,
              "username": anki["username"] if anki else ""},
    )


@bp.put("")
def update():
    try:
        users.update_settings(get_db(), g.user["id"], _data())
    except users.AccountError as e:
        return jsonify(error=str(e)), 400
    return jsonify(ok=True)


@bp.post("/password")
def change_password():
    data = _data()
    conn = get_db()
    if users.authenticate(conn, g.user["username"], data.get("current", "")) is None:
        return jsonify(error="Your current password is wrong."), 400
    try:
        users.set_password(conn, g.user["id"], data.get("new"))
    except users.AccountError as e:
        return jsonify(error=str(e)), 400
    log_in(users.get_user(conn, g.user["id"]))  # stay logged in here; other devices are logged out
    return jsonify(ok=True)


@bp.post("/logout-everywhere")
def logout_everywhere():
    conn = get_db()
    with conn:
        conn.execute("UPDATE users SET session_version = session_version + 1 WHERE id = ?", (g.user["id"],))
    log_out()
    return jsonify(ok=True)


# ---- Telegram ------------------------------------------------------------------------

@bp.post("/telegram/link")
def telegram_link():
    bot = services().bot
    if bot is None or not bot.username:
        return jsonify(error="Telegram isn't set up on this server yet."), 503
    token = telegram_bot.create_link_token(get_db(), g.user["id"])
    return jsonify(url=f"https://t.me/{bot.username}?start={token}")


@bp.delete("/telegram")
def telegram_unlink():
    telegram_bot.unlink(get_db(), g.user["id"])
    return jsonify(ok=True)


# ---- Web Push --------------------------------------------------------------------------

@bp.post("/push")
def push_subscribe():
    sub = _data().get("subscription") or {}
    endpoint, keys = sub.get("endpoint"), sub.get("keys") or {}
    if not isinstance(endpoint, str) or not endpoint.startswith("https://") or len(endpoint) > 1000 \
            or not keys.get("p256dh") or not keys.get("auth"):
        return jsonify(error="bad subscription"), 400
    conn = get_db()
    with conn:
        conn.execute(
            "INSERT INTO push_subscriptions (user_id, endpoint, p256dh, auth, user_agent) VALUES (?, ?, ?, ?, ?)"
            " ON CONFLICT(endpoint) DO UPDATE SET user_id = excluded.user_id, p256dh = excluded.p256dh,"
            " auth = excluded.auth, user_agent = excluded.user_agent",
            (g.user["id"], endpoint, str(keys["p256dh"])[:200], str(keys["auth"])[:100],
             request.headers.get("User-Agent", "")[:300]))
    return jsonify(ok=True), 201


@bp.delete("/push")
def push_unsubscribe():
    endpoint = _data().get("endpoint")
    conn = get_db()
    with conn:
        conn.execute("DELETE FROM push_subscriptions WHERE user_id = ? AND endpoint = ?", (g.user["id"], endpoint))
    return jsonify(ok=True)


@bp.post("/test-notification")
def test_notification():
    """Send today's reminder right now (or an 'all done' message), to every channel."""
    today = datetime.datetime.now(zoneinfo.ZoneInfo(g.user["timezone"])).date()
    sent = services().reminders.remind(get_db(), g.user, today, force=True)
    return jsonify(sent=sent)


# ---- Export -----------------------------------------------------------------------------

@bp.get("/export")
def export():
    data = activity.export(get_db(), g.user["id"])
    body = json.dumps(data, ensure_ascii=False, indent=2)
    name = f"english-hub-{g.user['username']}-{datetime.date.today().isoformat()}.json"
    return Response(body, mimetype="application/json",
                    headers={"Content-Disposition": f'attachment; filename="{name}"'})
