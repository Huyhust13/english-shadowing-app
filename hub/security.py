"""Who is asking, and are they allowed: login sessions, guards, CSRF, rate limits.

- Login state is Flask's signed session cookie holding {uid, ver}. `ver` must match
  users.session_version, so changing a password or deactivating an account logs
  out every device at once.
- @login_required / @admin_required guard views. Pages redirect to /login; API
  calls get a 401/403 JSON error.
- CSRF: the cookie is SameSite=Lax, and every state-changing request must also come
  from our own origin (Sec-Fetch-Site / Origin headers), see check_same_origin().
- Login and invite attempts are rate-limited in memory.
"""
import functools
import threading
import time
import urllib.parse

from flask import current_app, g, jsonify, redirect, request, session

from . import users
from .db import get_db

SAFE_METHODS = ("GET", "HEAD", "OPTIONS")


def load_user():
    """before_request hook: put the logged-in user (or None) on g.user."""
    g.user = None
    uid, ver = session.get("uid"), session.get("ver")
    if uid is None:
        return
    user = users.get_user(get_db(), uid)
    if user and user["is_active"] and user["session_version"] == ver:
        g.user = user
    else:
        session.clear()


def log_in(user):
    session.clear()
    session.permanent = True
    session["uid"] = user["id"]
    session["ver"] = user["session_version"]


def log_out():
    session.clear()


def _wants_json():
    return request.path.startswith("/api/")


def login_required(view):
    @functools.wraps(view)
    def wrapped(*args, **kwargs):
        if g.user is None:
            if _wants_json():
                return jsonify(error="Please log in again."), 401
            return redirect("/login?next=" + urllib.parse.quote(request.full_path.rstrip("?"), safe="/"))
        return view(*args, **kwargs)
    return wrapped


def admin_required(view):
    @functools.wraps(view)
    @login_required
    def wrapped(*args, **kwargs):
        if not g.user["is_admin"]:
            return (jsonify(error="Admins only."), 403) if _wants_json() else redirect("/")
        return view(*args, **kwargs)
    return wrapped


def safe_next(url):
    """Only allow redirects to a path on this site after login."""
    if not url or not url.startswith("/") or url.startswith("//") or "\\" in url:
        return "/"
    return url


def check_same_origin():
    """before_request hook: refuse cross-site writes (CSRF)."""
    if request.method in SAFE_METHODS:
        return None
    site = request.headers.get("Sec-Fetch-Site")
    if site is not None:
        if site in ("same-origin", "none"):
            return None
        return jsonify(error="Cross-site request refused."), 403
    origin = request.headers.get("Origin")
    if origin is None:  # not a browser (curl, tests); without our cookie it can't act as anyone
        return None
    allowed = {current_app.config["PUBLIC_URL"], request.host_url.rstrip("/")}
    if origin in allowed:
        return None
    return jsonify(error="Cross-site request refused."), 403


class RateLimiter:
    """At most `limit` failures per key in `window` seconds (in memory, per process)."""

    def __init__(self, limit=8, window=15 * 60):
        self.limit = limit
        self.window = window
        self._hits = {}
        self._lock = threading.Lock()

    def _recent(self, key, now):
        hits = [t for t in self._hits.get(key, ()) if now - t < self.window]
        self._hits[key] = hits
        return hits

    def blocked(self, *keys):
        now = time.time()
        with self._lock:
            return any(len(self._recent(k, now)) >= self.limit for k in keys)

    def fail(self, *keys):
        now = time.time()
        with self._lock:
            for k in keys:
                self._recent(k, now).append(now)

    def reset(self, *keys):
        with self._lock:
            for k in keys:
                self._hits.pop(k, None)


def limiter(name):
    """The app's RateLimiter for `name` (one set per app, so tests don't share state)."""
    return current_app.extensions["rate_limits"][name]


RATE_LIMITS = {
    "login": {"limit": 8, "window": 15 * 60},        # wrong passwords, per IP and per username
    "links": {"limit": 20, "window": 15 * 60},       # bad invite/reset tokens, per IP
    "anki-login": {"limit": 6, "window": 15 * 60},   # AnkiWeb logins, so we don't hammer AnkiWeb
}


def client_ip():
    return request.remote_addr or "?"
