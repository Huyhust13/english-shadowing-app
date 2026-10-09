"""HTML pages, static files, the web-app manifest, the service worker and Anki media.

Only the files listed here are served, so nothing else in the app folder (the
database, secrets) can be downloaded.
"""
import mimetypes
import os

from flask import Blueprint, abort, current_app, g, redirect, send_file, send_from_directory

from .. import services, users
from ..db import get_db
from ..security import admin_required, login_required

bp = Blueprint("pages", __name__)

PRIVATE_PAGES = {"/": "today.html", "/today": "today.html", "/vocab": "vocab.html",
                 "/practice": "practice.html", "/shadowing": "shadowing.html", "/settings": "settings.html",
                 "/guide": "guide.html"}
STATIC = {"app.css", "app.js", "editor.css", "editor.js"}
ICONS = {"icon.svg", "icon-32.png", "icon-192.png", "icon-512.png", "apple-touch-icon.png"}


def _page(name):
    resp = send_from_directory(current_app.config["WEB_DIR"], name, max_age=0)
    resp.headers["Cache-Control"] = "no-cache"
    return resp


def _private(path, name):
    @login_required
    def view():
        return _page(name)
    view.__name__ = "page_" + name.replace(".", "_") + path.replace("/", "_")
    bp.add_url_rule(path, view_func=view)


for _path, _name in PRIVATE_PAGES.items():
    _private(_path, _name)


@bp.get("/admin")
@admin_required
def admin_page():
    return _page("admin.html")


@bp.get("/login")
def login_page():
    if g.user is not None:
        return redirect("/")
    return _page("login.html")


@bp.get("/join/<token>")
def join_page(token):
    return _page("join.html")


@bp.get("/static/<name>")
def static_file(name):
    if name not in STATIC:
        abort(404)
    resp = send_from_directory(os.path.join(current_app.config["WEB_DIR"], "static"), name, max_age=0)
    resp.headers["Cache-Control"] = "no-cache"
    return resp


@bp.get("/icons/<name>")
def icon(name):
    if name not in ICONS:
        abort(404)
    return send_from_directory(current_app.config["ICONS_DIR"], name, max_age=86400)


@bp.get("/favicon.ico")
def favicon():
    return send_from_directory(current_app.config["ICONS_DIR"], "icon-32.png", max_age=86400)


@bp.get("/apple-touch-icon.png")
def apple_icon():
    return send_from_directory(current_app.config["ICONS_DIR"], "apple-touch-icon.png", max_age=86400)


@bp.get("/manifest.webmanifest")
def manifest():
    resp = send_from_directory(current_app.config["WEB_DIR"], "manifest.webmanifest", max_age=3600)
    resp.headers["Content-Type"] = "application/manifest+json"
    return resp


@bp.get("/sw.js")
def service_worker():
    # Served from the root so it controls the whole site; never cached, so updates land.
    resp = send_from_directory(current_app.config["WEB_DIR"], "sw.js", max_age=0)
    resp.headers["Cache-Control"] = "no-cache"
    resp.headers["Content-Type"] = "text/javascript; charset=utf-8"
    return resp


@bp.get("/anki-media/<key>/<path:name>")
def anki_media(key, name):
    """Images and audio for Anki cards.

    Cards render in a sandboxed iframe, which doesn't send our login cookie, so the
    URL itself carries a per-user secret (users.media_key) instead.
    """
    pool = services().pool
    row = users.find_by_media_key(get_db(), key) if pool.available else None
    if row is None:
        abort(404)
    path = pool.get(row["id"]).media_file(name)
    if not path:
        abort(404)
    resp = send_file(path, mimetype=mimetypes.guess_type(path)[0] or "application/octet-stream", max_age=86400)
    resp.headers["Cache-Control"] = "private, max-age=86400"
    return resp
