"""Log in, log out, and redeem invite / password-reset links."""
from flask import Blueprint, current_app, jsonify, request

from .. import users
from ..db import get_db
from ..security import client_ip, limiter, log_in, log_out, safe_next

bp = Blueprint("auth", __name__, url_prefix="/api/auth")


def _body():
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


@bp.post("/login")
def login():
    data = _body()
    username = str(data.get("username", "")).strip().lower()
    keys = ("ip:" + client_ip(), "user:" + username)
    if limiter("login").blocked(*keys):
        return jsonify(error="Too many attempts. Wait 15 minutes and try again."), 429
    user = users.authenticate(get_db(), username, data.get("password", ""))
    if user is None:
        limiter("login").fail(*keys)
        return jsonify(error="Wrong username or password."), 401
    limiter("login").reset("user:" + username)
    log_in(user)
    return jsonify(ok=True, next=safe_next(data.get("next")))


@bp.post("/logout")
def logout():
    log_out()
    return jsonify(ok=True)


@bp.get("/link/<token>")
def link_info(token):
    """What an invite/reset link is for, so the page can show the right form."""
    if limiter("links").blocked("ip:" + client_ip()):
        return jsonify(error="Too many attempts. Wait 15 minutes and try again."), 429
    link = users.find_link(get_db(), token)
    if link is None:
        limiter("links").fail("ip:" + client_ip())
        return jsonify(error="This link has expired or was already used. Ask for a new one."), 404
    return jsonify(kind=link["kind"], username=link["username"] if link["kind"] == "reset" else None,
                   defaultTimezone=current_app.config["DEFAULT_TIMEZONE"])


@bp.post("/link/<token>")
def link_redeem(token):
    if limiter("links").blocked("ip:" + client_ip()):
        return jsonify(error="Too many attempts. Wait 15 minutes and try again."), 429
    data = _body()
    conn = get_db()
    link = users.find_link(conn, token)
    try:  # the browser's timezone, unless it's one the server doesn't know
        timezone = users.check_timezone(data.get("timezone"))
    except users.AccountError:
        timezone = current_app.config["DEFAULT_TIMEZONE"]
    try:
        user_id = users.use_link(conn, token, username=data.get("username"), display_name=data.get("displayName"),
                                 password=data.get("password"), timezone=timezone)
    except users.AccountError as e:
        if "expired" in str(e) or "already used" in str(e):
            limiter("links").fail("ip:" + client_ip())
        return jsonify(error=str(e)), 400
    log_in(users.get_user(conn, user_id))
    return jsonify(ok=True, next="/settings?welcome=1" if link and link["kind"] == "invite" else "/")
