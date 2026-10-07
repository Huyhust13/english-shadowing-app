#!/usr/bin/env python3
"""English Hub server: the daily Today page, Anki vocab, sentence practice and shadowing.

Shadowing sessions and practice ticks live in SQLite (data/shadowing.db). The Anki part
is a real Anki collection synced with AnkiWeb (see anki_service.py); it needs the `anki`
package and is reported as unavailable without it.
"""
import html
import json
import os
import re
import signal
import sqlite3
import traceback
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get("SHADOWING_DB", os.path.join(BASE_DIR, "data", "shadowing.db"))
HOST = os.environ.get("HOST", "0.0.0.0")
PORT = int(os.environ.get("PORT", "8090"))

try:
    import anki_service
    ANKI_IMPORT_ERROR = ""
except ImportError as e:  # the app still works, just without the Vocab part
    anki_service = None
    ANKI_IMPORT_ERROR = str(e)
ANKI = None  # AnkiService, created in main

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
        conn.execute(
            """CREATE TABLE IF NOT EXISTS practice_days (
                date TEXT PRIMARY KEY,
                note TEXT NOT NULL DEFAULT '',
                markedAt TEXT NOT NULL
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


def valid_date(date):
    return isinstance(date, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", date) is not None


def summary():
    """Per-day activity for the Today page: shadowing reps, practice ticks, Anki reviews."""
    with connect() as conn:
        shadow = {r["date"]: r["reps"] for r in conn.execute(
            "SELECT date, SUM(reps) AS reps FROM sessions GROUP BY date")}
        practice = {r["date"]: r["note"] for r in conn.execute("SELECT date, note FROM practice_days")}
    anki, anki_error = {}, ANKI_IMPORT_ERROR
    if ANKI:
        try:
            anki = ANKI.review_days()
        except Exception as e:
            anki_error = str(e)
    return {"shadow": shadow, "practice": practice, "anki": anki,
            "ankiAvailable": ANKI is not None, "ankiError": anki_error}


def session_id(path):
    """Return the id from /api/sessions/<id>, or None if path doesn't match."""
    m = re.fullmatch(r"/api/sessions/(\d+)", path)
    return int(m.group(1)) if m else None


# Only these files are served, so nothing else in the app folder (like the DB) is exposed.
STATIC_FILES = {
    "/": ("today.html", "text/html; charset=utf-8"),
    "/today": ("today.html", "text/html; charset=utf-8"),
    "/vocab": ("vocab.html", "text/html; charset=utf-8"),
    "/practice": ("practice.html", "text/html; charset=utf-8"),
    "/shadowing": ("shadowing.html", "text/html; charset=utf-8"),
    "/static/app.css": ("static/app.css", "text/css; charset=utf-8"),
    "/static/app.js": ("static/app.js", "text/javascript; charset=utf-8"),
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
        if path in STATIC_FILES:
            name, ctype = STATIC_FILES[path]
            self.send_file(name, ctype, max_age=0 if name.endswith((".html", ".css", ".js")) else 86400)
        elif path.startswith("/anki-media/"):
            self.send_anki_media(urllib.parse.unquote(path[len("/anki-media/"):]))
        elif path.startswith("/api/anki/"):
            self.anki_api("GET", path)
        elif path == "/api/summary":
            self.send_json(200, summary())
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

    def query(self):
        return {k: v[0] for k, v in urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query).items()}

    def send_anki_media(self, name):
        path = ANKI.media_file(name) if ANKI else None
        if not path:
            return self.send_json(404, {"error": "no such media file"})
        with open(path, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", anki_service.guess_type(path))
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "public, max-age=86400")
        self.end_headers()
        self.wfile.write(body)

    def anki_api(self, method, path):
        """Everything under /api/anki/: decks, studying, notes, sync and login."""
        if not ANKI:
            return self.send_json(503, {"error": "Anki is not available: " + (ANKI_IMPORT_ERROR or "not started")})
        route = path[len("/api/anki/"):]
        try:
            data = self.read_json() if method in ("POST", "PUT") else None
            q = self.query()
            if method == "GET" and route == "state":
                return self.send_json(200, ANKI.state())
            if method == "GET" and route == "decks":
                return self.send_json(200, ANKI.decks())
            if method == "GET" and route == "next":
                return self.send_json(200, ANKI.next_card(int(q["deck"]) if q.get("deck") else None))
            if method == "POST" and route == "answer":
                ANKI.answer(int(data["cardId"]), int(data["rating"]), data.get("ms"))
                return self.send_json(200, {"ok": True})
            if method == "POST" and route == "undo":
                return self.send_json(200, {"undone": ANKI.undo()})
            if method == "POST" and route == "sync":
                return self.send_json(200, ANKI.sync(force_download=bool((data or {}).get("forceDownload"))))
            if method == "POST" and route == "login":
                ANKI.login(str(data.get("username", "")).strip(), str(data.get("password", "")))
                return self.send_json(200, ANKI.sync())
            if method == "POST" and route == "logout":
                ANKI.logout()
                return self.send_json(200, {"ok": True})
            if method == "GET" and route == "notetypes":
                return self.send_json(200, ANKI.note_types())
            if method == "GET" and route == "notes":
                return self.send_json(200, ANKI.search(q.get("q", "")))
            if method == "POST" and route == "notes":
                nid = ANKI.add_note(data.get("notetype"), data.get("deck"), data.get("fields"), data.get("tags"))
                return self.send_json(201, {"id": nid})
            m = re.fullmatch(r"notes/(\d+)", route)
            if method == "PUT" and m:
                ANKI.update_note(int(m.group(1)), data.get("fields"), data.get("tags"))
                return self.send_json(200, {"ok": True})
        except anki_service.AnkiError as e:
            return self.send_json(409, {"error": str(e)})
        except (ValueError, TypeError, KeyError, json.JSONDecodeError) as e:
            return self.send_json(400, {"error": "bad request: " + str(e)})
        except Exception as e:
            traceback.print_exc()
            return self.send_json(500, {"error": str(e)})
        self.send_json(404, {"error": "not found"})

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        if path.startswith("/api/anki/"):
            return self.anki_api("POST", path)
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
        path = self.path.split("?", 1)[0]
        if path.startswith("/api/anki/"):
            return self.anki_api("PUT", path)
        m = re.fullmatch(r"/api/practice/([0-9-]+)", path)
        if m:
            return self.put_practice(m.group(1))
        sid = session_id(path)
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

    def put_practice(self, date):
        """Tick (done: true, optional note) or untick a practice day."""
        try:
            data = self.read_json() or {}
            if not valid_date(date):
                raise ValueError("bad date")
        except (ValueError, TypeError, json.JSONDecodeError) as e:
            return self.send_json(400, {"error": str(e)})
        with connect() as conn:
            if data.get("done"):
                conn.execute(
                    "INSERT INTO practice_days (date, note, markedAt) VALUES (?, ?, datetime('now'))"
                    " ON CONFLICT(date) DO UPDATE SET note=excluded.note",
                    (date, str(data.get("note") or "")[:20000]),
                )
            else:
                conn.execute("DELETE FROM practice_days WHERE date=?", (date,))
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
    if anki_service:
        ANKI = anki_service.AnkiService()
        ANKI.start_background()
    else:
        print("Anki disabled:", ANKI_IMPORT_ERROR, flush=True)
    print(f"English Hub on http://{HOST}:{PORT}  (db: {DB_PATH})", flush=True)
    # systemd stops us with SIGTERM; turn it into a normal exit so the collection is closed cleanly.
    def stop(*_):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, stop)
    try:
        ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if ANKI:
            ANKI.close()
