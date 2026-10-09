"""Everything under /api/anki/: the logged-in person's decks, studying, notes, sync and AnkiWeb login."""
from flask import Blueprint, current_app, g, jsonify, request
from werkzeug.exceptions import HTTPException

from .. import services
from ..anki_pool import anki_service
from ..security import client_ip, limiter, login_required

bp = Blueprint("anki", __name__, url_prefix="/api/anki")


@bp.before_request
@login_required
def require_anki():
    pool = services().pool
    if not pool.available:
        return jsonify(error="Anki is not available: " + pool.error), 503
    g.anki = pool.get(g.user["id"])
    return None


@bp.errorhandler(Exception)
def errors(e):
    if isinstance(e, HTTPException):
        return jsonify(error=e.description), e.code
    if anki_service and isinstance(e, anki_service.AnkiError):
        return jsonify(error=str(e)), 409
    if isinstance(e, (ValueError, TypeError, KeyError)):
        return jsonify(error="bad request: " + str(e)), 400
    current_app.logger.exception("Anki request failed")
    return jsonify(error=str(e)), 500


def _data():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


@bp.get("/state")
def state():
    st = g.anki.state()
    st["mediaBase"] = f"/anki-media/{g.user['media_key']}/"
    return jsonify(st)


@bp.get("/decks")
def decks():
    return jsonify(g.anki.decks())


@bp.get("/next")
def next_card():
    deck = request.args.get("deck")
    return jsonify(g.anki.next_card(int(deck) if deck else None))


@bp.post("/answer")
def answer():
    data = _data()
    g.anki.answer(int(data["cardId"]), int(data["rating"]), data.get("ms"))
    return jsonify(ok=True)


@bp.post("/reveal")
def reveal():
    data = _data()
    return jsonify(answer=g.anki.reveal(int(data["cardId"]), data.get("typed", "")))


@bp.post("/undo")
def undo():
    return jsonify(undone=g.anki.undo())


@bp.post("/sync")
def sync():
    return jsonify(g.anki.sync(force_download=bool(_data().get("forceDownload"))))


@bp.post("/login")
def login():
    keys = ("ip:" + client_ip(), "user:" + str(g.user["id"]))
    if limiter("anki-login").blocked(*keys):
        return jsonify(error="Too many AnkiWeb login attempts. Wait 15 minutes."), 429
    data = _data()
    try:
        g.anki.login(str(data.get("username", "")).strip(), str(data.get("password", "")))
    except anki_service.AnkiError:
        limiter("anki-login").fail(*keys)
        raise
    return jsonify(g.anki.sync())


@bp.post("/logout")
def logout():
    g.anki.logout()
    return jsonify(ok=True)


@bp.get("/notetypes")
def note_types():
    return jsonify(g.anki.note_types())


@bp.get("/notes")
def search_notes():
    return jsonify(g.anki.search(request.args.get("q", "")))


@bp.post("/notes")
def add_note():
    data = _data()
    nid = g.anki.add_note(data.get("notetype"), data.get("deck"), data.get("fields"), data.get("tags"))
    return jsonify(id=nid), 201


@bp.put("/notes/<int:note_id>")
def update_note(note_id):
    data = _data()
    g.anki.update_note(note_id, data.get("fields"), data.get("tags"))
    return jsonify(ok=True)
