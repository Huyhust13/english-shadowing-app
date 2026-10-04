#!/usr/bin/env python3
"""Shadowing Tracker server: serves index.html and stores sessions in SQLite."""
import html
import json
import os
import re
import sqlite3
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("SHADOWING_DB", os.path.join(BASE_DIR, "data", "shadowing.db"))
HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8080"))

COLUMNS = ("date", "loggedAt", "clipTitle", "clipUrl", "reps", "confidence", "notes")


def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    with connect() as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT NOT NULL,
                loggedAt TEXT NOT NULL UNIQUE,
                clipTitle TEXT NOT NULL DEFAULT '',
                clipUrl TEXT NOT NULL DEFAULT '',
                reps INTEGER NOT NULL DEFAULT 1,
                confidence INTEGER,
                notes TEXT NOT NULL DEFAULT ''
            )"""
        )


def clean(s):
    """Validate one session dict from the client; raises ValueError if bad."""
    if not isinstance(s, dict):
        raise ValueError("session must be an object")
    date, logged_at = s.get("date"), s.get("loggedAt")
    if not isinstance(date, str) or len(date) != 10:
        raise ValueError("bad date")
    if not isinstance(logged_at, str) or not logged_at:
        raise ValueError("bad loggedAt")
    conf = s.get("confidence")
    if conf not in (None, 1, 2, 3):
        raise ValueError("bad confidence")
    return (
        date,
        logged_at,
        str(s.get("clipTitle") or "")[:500],
        str(s.get("clipUrl") or "")[:2000],
        max(1, min(int(s.get("reps") or 1), 1000)),
        conf,
        str(s.get("notes") or "")[:200000],
    )


def insert(conn, sessions):
    conn.executemany(
        "INSERT OR IGNORE INTO sessions (date, loggedAt, clipTitle, clipUrl, reps, confidence, notes)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        [clean(s) for s in sessions],
    )


USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36"
YOUTUBE_HOSTS = ("youtube.com", "www.youtube.com", "m.youtube.com", "music.youtube.com", "youtu.be")


def http_get(url, limit=512 * 1024):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Language": "en"})
    with urllib.request.urlopen(req, timeout=8) as res:
        charset = res.headers.get_content_charset() or "utf-8"
        return res.read(limit).decode(charset, errors="replace")


def fetch_title(url):
    """Return the page title for url, or '' if none was found."""
    parts = urllib.parse.urlparse(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError("only http(s) links are supported")

    if parts.hostname in YOUTUBE_HOSTS:
        oembed = "https://www.youtube.com/oembed?format=json&url=" + urllib.parse.quote(url, safe="")
        try:
            return json.loads(http_get(oembed)).get("title", "")
        except Exception:
            pass  # fall back to scraping the page

    page = http_get(url)
    for pattern in (
        r'<meta[^>]+property=["\']og:title["\'][^>]+content=["\']([^"\']+)',
        r'<meta[^>]+content=["\']([^"\']+)["\'][^>]+property=["\']og:title',
        r"<title[^>]*>(.*?)</title>",
    ):
        m = re.search(pattern, page, re.IGNORECASE | re.DOTALL)
        if m:
            return " ".join(html.unescape(m.group(1)).split())
    return ""


def session_id(path):
    """Return the id from /api/sessions/<id>, or None if path doesn't match."""
    m = re.fullmatch(r"/api/sessions/(\d+)", path)
    return int(m.group(1)) if m else None


# Only these files are served, so nothing else in the app folder (like the DB) is exposed.
STATIC_FILES = {
    "/icons/icon.svg": ("icons/icon.svg", "image/svg+xml"),
    "/icons/icon-32.png": ("icons/icon-32.png", "image/png"),
    "/favicon.ico": ("icons/icon-32.png", "image/png"),
    "/apple-touch-icon.png": ("icons/apple-touch-icon.png", "image/png"),
}


class Handler(BaseHTTPRequestHandler):
    def send_json(self, status, payload):
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_json(self):
        length = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(length) or b"null")

    def send_file(self, name, content_type, max_age=0):
        with open(os.path.join(BASE_DIR, name), "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        if max_age:
            self.send_header("Cache-Control", f"public, max-age={max_age}")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html"):
            self.send_file("index.html", "text/html; charset=utf-8")
        elif path in STATIC_FILES:
            self.send_file(*STATIC_FILES[path], max_age=86400)
        elif path == "/api/sessions":
            with connect() as conn:
                rows = conn.execute(
                    "SELECT id, " + ", ".join(COLUMNS) + " FROM sessions ORDER BY date, loggedAt"
                ).fetchall()
            self.send_json(200, [dict(r) for r in rows])
        elif path == "/api/title":
            query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            try:
                self.send_json(200, {"title": fetch_title(query.get("url", [""])[0])})
            except ValueError as e:
                self.send_json(400, {"error": str(e)})
            except Exception as e:
                self.send_json(502, {"error": "couldn't fetch title: " + str(e)})
        else:
            self.send_json(404, {"error": "not found"})

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        try:
            data = self.read_json()
            with connect() as conn:
                if path == "/api/sessions":
                    insert(conn, [data])
                elif path == "/api/sessions/import":
                    if not isinstance(data, list):
                        raise ValueError("expected a list")
                    insert(conn, data)
                else:
                    return self.send_json(404, {"error": "not found"})
        except (ValueError, TypeError, json.JSONDecodeError) as e:
            return self.send_json(400, {"error": str(e)})
        self.send_json(201, {"ok": True})

    def do_PUT(self):
        sid = session_id(self.path.split("?", 1)[0])
        if sid is None:
            return self.send_json(404, {"error": "not found"})
        try:
            row = clean(self.read_json())
        except (ValueError, TypeError, json.JSONDecodeError) as e:
            return self.send_json(400, {"error": str(e)})
        with connect() as conn:
            cur = conn.execute(
                "UPDATE sessions SET date=?, loggedAt=?, clipTitle=?, clipUrl=?, reps=?, confidence=?, notes=?"
                " WHERE id=?",
                row + (sid,),
            )
        if cur.rowcount == 0:
            return self.send_json(404, {"error": "no such session"})
        self.send_json(200, {"ok": True})

    def do_DELETE(self):
        sid = session_id(self.path.split("?", 1)[0])
        if sid is None:
            return self.send_json(404, {"error": "not found"})
        with connect() as conn:
            cur = conn.execute("DELETE FROM sessions WHERE id=?", (sid,))
        if cur.rowcount == 0:
            return self.send_json(404, {"error": "no such session"})
        self.send_json(200, {"ok": True})


if __name__ == "__main__":
    init_db()
    print(f"Shadowing Tracker on http://{HOST}:{PORT}  (db: {DB_PATH})", flush=True)
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
