"""Admin: invite friends, see accounts, reset passwords, turn accounts off.

Admins see who has an account and when they last practised, never anyone's notes
or logs.
"""
from flask import Blueprint, current_app, g, jsonify, request

from .. import services, users
from ..db import get_db
from ..security import admin_required

bp = Blueprint("admin", __name__, url_prefix="/api/admin")


@bp.before_request
@admin_required
def _guard():
    return None


def _link(token):
    return f"{current_app.config['PUBLIC_URL']}/join/{token}"


@bp.get("/users")
def list_users():
    return jsonify([{
        "id": r["id"], "username": r["username"], "displayName": r["display_name"],
        "isAdmin": bool(r["is_admin"]), "isActive": bool(r["is_active"]), "createdAt": r["created_at"],
        "lastActive": max(filter(None, (r["last_shadowing"], r["last_practice"])), default=None),
    } for r in users.list_users(get_db())])


@bp.get("/invites")
def list_invites():
    return jsonify([dict(r) for r in users.pending_invites(get_db())])


@bp.post("/invites")
def create_invite():
    note = (request.get_json(silent=True) or {}).get("note", "")
    token = users.create_link(get_db(), "invite", g.user["id"], note=note)
    return jsonify(url=_link(token), days=users.INVITE_DAYS), 201


@bp.delete("/invites/<int:invite_id>")
def revoke_invite(invite_id):
    users.revoke_invite(get_db(), invite_id)
    return jsonify(ok=True)


@bp.post("/users/<int:user_id>/reset")
def reset_link(user_id):
    if users.get_user(get_db(), user_id) is None:
        return jsonify(error="no such user"), 404
    token = users.create_link(get_db(), "reset", g.user["id"], user_id=user_id)
    return jsonify(url=_link(token), days=users.RESET_DAYS), 201


@bp.put("/users/<int:user_id>/active")
def set_active(user_id):
    if user_id == g.user["id"]:
        return jsonify(error="You can't turn off your own account."), 400
    active = bool((request.get_json(silent=True) or {}).get("active"))
    users.set_active(get_db(), user_id, active)
    if not active:
        services().pool.drop(user_id)
    return jsonify(ok=True)
