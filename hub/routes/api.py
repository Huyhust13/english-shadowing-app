"""The logged-in person's shadowing sessions, practice ticks, Today summary, clip titles."""
import datetime
import zoneinfo

from flask import Blueprint, g, jsonify, request

from .. import activity, services, streak, titles
from ..db import get_db
from ..security import login_required

bp = Blueprint("api", __name__, url_prefix="/api")


def _json():
    return request.get_json(silent=True)


@bp.get("/sessions")
@login_required
def list_sessions():
    return jsonify(activity.list_sessions(get_db(), g.user["id"]))


@bp.post("/sessions")
@login_required
def add_session():
    try:
        activity.add_sessions(get_db(), g.user["id"], [_json()])
    except (ValueError, TypeError) as e:
        return jsonify(error=str(e)), 400
    return jsonify(ok=True), 201


@bp.post("/sessions/import")
@login_required
def import_sessions():
    data = _json()
    if not isinstance(data, list) or len(data) > 5000:
        return jsonify(error="expected a list"), 400
    try:
        activity.add_sessions(get_db(), g.user["id"], data)
    except (ValueError, TypeError) as e:
        return jsonify(error=str(e)), 400
    return jsonify(ok=True), 201


@bp.put("/sessions/<int:session_id>")
@login_required
def update_session(session_id):
    try:
        found = activity.update_session(get_db(), g.user["id"], session_id, _json())
    except (ValueError, TypeError) as e:
        return jsonify(error=str(e)), 400
    return (jsonify(ok=True), 200) if found else (jsonify(error="no such session"), 404)


@bp.delete("/sessions/<int:session_id>")
@login_required
def delete_session(session_id):
    if not activity.delete_session(get_db(), g.user["id"], session_id):
        return jsonify(error="no such session"), 404
    return jsonify(ok=True)


@bp.put("/practice/<date>")
@login_required
def put_practice(date):
    """Tick (done: true, optional note) or untick a practice day."""
    data = _json() or {}
    try:
        activity.set_practice(get_db(), g.user["id"], date, bool(data.get("done")), data.get("note"))
    except (ValueError, TypeError) as e:
        return jsonify(error=str(e)), 400
    return jsonify(ok=True)


@bp.get("/summary")
@login_required
def summary():
    """Per-day activity for the Today page (shadowing reps, practice ticks, Anki reviews) and the streak."""
    conn, uid = get_db(), g.user["id"]
    tz = zoneinfo.ZoneInfo(g.user["timezone"])
    today = datetime.datetime.now(tz).date()
    pool = services().pool
    anki, anki_error, connected = {}, pool.error, False
    if pool.available:
        try:
            connected = pool.is_connected(uid)
            if connected:
                anki = pool.get(uid).review_days(tz)
        except Exception as e:
            anki_error = str(e)
    days = streak.habit_days(conn, uid, anki if connected else None)
    return jsonify(shadow=activity.shadow_days(conn, uid), practice=activity.practice_days(conn, uid),
                   anki=anki, ankiAvailable=pool.available, ankiConnected=connected, ankiError=anki_error,
                   today=today.isoformat(), streak=streak.compute(days, today))


@bp.get("/title")
@login_required
def title():
    try:
        return jsonify(title=titles.fetch_title(request.args.get("url", "")))
    except ValueError as e:
        return jsonify(error=str(e)), 400
    except Exception as e:
        return jsonify(error="couldn't fetch title: " + str(e)), 502
