#!/usr/bin/env python3
"""Anki side of English Hub: a real Anki collection that syncs with AnkiWeb.

The collection lives in data/anki/ and is kept in step with the person's AnkiWeb
account, exactly like Anki desktop or AnkiDroid would. AnkiWeb stays the source of
truth: this module only ever does a normal sync, or a full *download* when the local
copy is empty or when explicitly asked. It never uploads over AnkiWeb.

Needs the `anki` package (pip install anki); server.py runs without it and reports
the Anki part as unavailable.

CLI:
  python anki_service.py login            log in with AnkiWeb email + password
  python anki_service.py import-desktop   reuse the login of Anki desktop on this machine
  python anki_service.py sync             one sync, then print the status
"""
import datetime
import getpass
import json
import mimetypes
import os
import pickle
import re
import sqlite3
import sys
import threading
import time

from anki.collection import Collection  # must come first: anki.cards imports it circularly
from anki.cards import Card
from anki.scheduler_pb2 import CardAnswer, SchedulingStates
from anki.sound import SoundOrVideoTag, TTSTag
from anki.sync import SyncAuth, SyncOutput

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ANKI_DIR = os.environ.get("ANKI_DIR", os.path.join(BASE_DIR, "data", "anki"))
COL_PATH = os.path.join(ANKI_DIR, "collection.anki2")
BACKUP_DIR = os.path.join(ANKI_DIR, "backups")
AUTH_PATH = os.path.expanduser(os.environ.get("ANKI_AUTH", "~/.config/english-hub/ankiweb.json"))
DESKTOP_PREFS = os.path.expanduser("~/.local/share/Anki2/prefs21.db")

ADD_DECK = "My Words"   # where cards added from this app go
SYNC_EVERY = 10 * 60    # background sync interval, seconds
SYNC_AFTER_REVIEW = 60  # sync this long after the last answer, seconds

RATINGS = {1: CardAnswer.AGAIN, 2: CardAnswer.HARD, 3: CardAnswer.GOOD, 4: CardAnswer.EASY}


class AnkiError(Exception):
    """An error worth showing to the person as-is."""


# ---- AnkiWeb login ----------------------------------------------------------

def load_auth():
    try:
        with open(AUTH_PATH) as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    if not data.get("hkey"):
        return None
    return data


def save_auth(hkey, endpoint, username):
    os.makedirs(os.path.dirname(AUTH_PATH), exist_ok=True)
    fd = os.open(AUTH_PATH, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump({"hkey": hkey, "endpoint": endpoint or "", "username": username or ""}, f)


def desktop_auth(profile="User 1"):
    """Return (hkey, endpoint, username) from Anki desktop's profile on this machine."""
    conn = sqlite3.connect(f"file:{DESKTOP_PREFS}?mode=ro", uri=True)
    try:
        row = conn.execute("SELECT cast(data as blob) FROM profiles WHERE name=?", (profile,)).fetchone()
    finally:
        conn.close()
    if not row:
        raise AnkiError(f"no Anki desktop profile called {profile!r}")
    prof = pickle.loads(row[0])
    if not prof.get("syncKey"):
        raise AnkiError("Anki desktop is not logged in to AnkiWeb")
    return prof["syncKey"], prof.get("currentSyncUrl") or "", prof.get("syncUser") or ""


# ---- Card rendering ---------------------------------------------------------

PLAY_TAG = re.compile(r"\[anki:play:([qa]):(\d+)\]")
TYPE_TAG = re.compile(r"\[\[type:[^\]]*\]\]")
PLAY_BUTTON = (
    '<a class="replay-button soundLink" href="#" data-play="{side}:{idx}" '
    'onclick="parent.postMessage({{ankiPlay:\'{side}:{idx}\'}},\'*\');return false;">'
    '<svg class="playImage" viewBox="0 0 64 64" width="40" height="40"><circle cx="32" cy="32" r="29" '
    'fill="#fff" stroke="#888" stroke-width="2"/><path d="M26 20v24l18-12z" fill="#555"/></svg></a>'
)


def av_list(tags):
    out = []
    for tag in tags:
        if isinstance(tag, SoundOrVideoTag):
            out.append({"type": "sound", "file": tag.filename})
        elif isinstance(tag, TTSTag):
            out.append({"type": "tts", "text": tag.field_text, "lang": tag.lang})
        else:
            out.append({"type": "none"})
    return out


def render_html(text):
    text = TYPE_TAG.sub("", text)
    return PLAY_TAG.sub(lambda m: PLAY_BUTTON.format(side=m.group(1), idx=m.group(2)), text)


# ---- The service ------------------------------------------------------------

class AnkiService:
    def __init__(self):
        os.makedirs(ANKI_DIR, exist_ok=True)
        self.lock = threading.RLock()
        self.col = Collection(COL_PATH)
        self.status = {"state": "idle", "message": "", "lastSync": None, "lastError": ""}
        self.last_answer = 0.0
        self._wake = threading.Event()
        self._last_backup_day = None

    # -- sync --

    def auth(self):
        data = load_auth()
        if not data:
            return None
        return SyncAuth(hkey=data["hkey"], endpoint=data["endpoint"] or None)

    def login(self, username, password):
        with self.lock:
            try:
                auth = self.col.sync_login(username, password, None)
            except Exception as e:
                raise AnkiError(f"AnkiWeb login failed: {e}") from e
            save_auth(auth.hkey, auth.endpoint, username)

    def logout(self):
        try:
            os.remove(AUTH_PATH)
        except FileNotFoundError:
            pass

    def sync(self, force_download=False):
        """Sync with AnkiWeb. Returns the status dict; never uploads a full collection."""
        auth = self.auth()
        if not auth:
            self._set_status("needs-login", "Log in to AnkiWeb to sync.")
            return self.status
        with self.lock:
            self._set_status("syncing", "Syncing with AnkiWeb…")
            try:
                if force_download:
                    out = None
                    self._full_download(auth, None)
                else:
                    out = self.col.sync_collection(auth, sync_media=True)
                    self._apply_endpoint(out)
                    self._handle_required(auth, out)
                self.status["lastSync"] = datetime.datetime.now().isoformat(timespec="seconds")
                self.status["lastError"] = ""
                msg = out.server_message if out is not None and out.server_message else "Synced."
                self._set_status("ok", msg)
                self._daily_backup()
            except AnkiError as e:
                self.status["lastError"] = str(e)
                self._set_status("conflict" if "full sync" in str(e).lower() else "error", str(e))
            except Exception as e:  # network down, AnkiWeb hiccup, expired login…
                text = str(e) or e.__class__.__name__
                self.status["lastError"] = text
                if "auth" in text.lower() or "403" in text:
                    self._set_status("needs-login", "AnkiWeb rejected the login; log in again.")
                else:
                    self._set_status("error", "Sync failed: " + text)
        return self.status

    def _apply_endpoint(self, out: SyncOutput):
        if out.new_endpoint:
            data = load_auth() or {}
            save_auth(data.get("hkey"), out.new_endpoint, data.get("username"))

    def _handle_required(self, auth, out: SyncOutput):
        req = out.required
        if req in (out.NO_CHANGES, out.NORMAL_SYNC):
            return
        if req == out.FULL_DOWNLOAD or (req == out.FULL_SYNC and self.col.card_count() == 0):
            self._full_download(auth, out.server_media_usn)
            return
        if req == out.FULL_UPLOAD:
            raise AnkiError("AnkiWeb has no collection yet. Upload it from Anki desktop first; "
                            "this app never uploads a full collection.")
        raise AnkiError("AnkiWeb asks for a full sync (the copies diverged). Use "
                        "\"Replace with AnkiWeb copy\" to download AnkiWeb's version here.")

    def _full_download(self, auth, server_media_usn):
        self._set_status("syncing", "Downloading your collection from AnkiWeb…")
        self.col.close_for_full_sync()
        try:
            self.col.full_upload_or_download(auth=auth, server_usn=server_media_usn, upload=False)
        finally:
            self.col.reopen(after_full_sync=True)
        if server_media_usn is None:
            self.col.sync_media(auth)

    def _daily_backup(self):
        today = datetime.date.today()
        if self._last_backup_day == today or self.col.card_count() == 0:
            return
        try:
            os.makedirs(BACKUP_DIR, exist_ok=True)
            self.col.create_backup(backup_folder=BACKUP_DIR, force=True, wait_for_completion=False)
            self._last_backup_day = today
        except Exception as e:
            print("anki backup failed:", e, flush=True)

    def _set_status(self, state, message):
        self.status["state"] = state
        self.status["message"] = message

    def media_status(self):
        try:
            st = self.col.media_sync_status()
            return {"active": st.active, "checked": strip_bidi(st.progress.checked),
                    "added": strip_bidi(st.progress.added), "removed": strip_bidi(st.progress.removed)}
        except Exception as e:
            return {"active": False, "error": str(e)}

    def request_sync_soon(self):
        self._wake.set()

    def start_background(self):
        def loop():
            next_periodic = 0.0
            while True:
                now = time.time()
                due_after_review = self.last_answer and now - self.last_answer >= SYNC_AFTER_REVIEW
                if now >= next_periodic or due_after_review or self._wake.is_set():
                    self._wake.clear()
                    self.last_answer = 0.0
                    self.sync()
                    next_periodic = time.time() + SYNC_EVERY
                self._wake.wait(15)
        threading.Thread(target=loop, name="anki-sync", daemon=True).start()

    def close(self):
        with self.lock:
            self.col.close()

    # -- decks & stats --

    def state(self):
        with self.lock:
            data = load_auth()
            return {
                "available": True,
                "loggedIn": bool(data),
                "username": (data or {}).get("username", ""),
                "sync": dict(self.status),
                "media": self.media_status(),
                "cards": self.col.card_count(),
            }

    def decks(self):
        with self.lock:
            tree = self.col.sched.deck_due_tree()
            out = []

            def walk(node, depth, prefix=""):
                for child in node.children:
                    full = prefix + child.name
                    out.append({
                        "id": child.deck_id, "name": child.name, "fullName": full, "depth": depth,
                        "new": child.new_count, "learn": child.learn_count, "review": child.review_count,
                        "total": child.total_including_children, "collapsed": child.collapsed,
                        "hasChildren": bool(child.children),
                    })
                    walk(child, depth + 1, full + "::")
            walk(tree, 0)
            return out

    def review_days(self):
        """{ 'YYYY-MM-DD': reviews } by local calendar date, for streaks and charts."""
        with self.lock:
            stamps = self.col.db.list("SELECT id FROM revlog WHERE ease > 0")
        days = {}
        for ms in stamps:
            day = datetime.date.fromtimestamp(ms / 1000).isoformat()
            days[day] = days.get(day, 0) + 1
        return days

    # -- studying --

    def _top_card(self, deck_id):
        if deck_id:
            self.col.decks.select(deck_id)
        queued = self.col.sched.get_queued_cards(fetch_limit=1)
        if not queued.cards:
            return None, queued
        qc = queued.cards[0]
        card = Card(self.col)
        card._load_from_backend_card(qc.card)
        return (card, qc), queued

    def next_card(self, deck_id):
        with self.lock:
            top, queued = self._top_card(deck_id)
            deck = self.col.decks.get(self.col.decks.selected())
            counts = {"new": queued.new_count, "learn": queued.learning_count, "review": queued.review_count}
            if top is None:
                return {"done": True, "deckName": deck["name"], "counts": counts}
            card, qc = top
            labels = [strip_bidi(s) for s in self.col.sched.describe_next_states(qc.states)]
            # question()/answer() already start with the note type's <style> block.
            return {
                "done": False,
                "deckName": deck["name"],
                "counts": counts,
                "queue": {0: "new", 1: "learn", 2: "review", 3: "learn"}.get(qc.queue, "review"),
                "cardId": card.id,
                "ord": card.ord,
                "question": render_html(card.question()),
                "answer": render_html(card.answer()),
                "avQuestion": av_list(card.question_av_tags()),
                "avAnswer": av_list(card.answer_av_tags()),
                "buttons": labels,
            }

    def answer(self, card_id, rating, ms_taken):
        if rating not in RATINGS:
            raise AnkiError("rating must be 1–4")
        with self.lock:
            top, _ = self._top_card(None)
            if top is None or top[0].id != card_id:
                raise AnkiError("That card is no longer next in the queue; reloading.")
            card, qc = top
            states: SchedulingStates = qc.states
            new_state = {1: states.again, 2: states.hard, 3: states.good, 4: states.easy}[rating]
            self.col.sched.answer_card(CardAnswer(
                card_id=card.id,
                current_state=states.current,
                new_state=new_state,
                rating=RATINGS[rating],
                answered_at_millis=int(time.time() * 1000),
                milliseconds_taken=max(0, min(int(ms_taken or 0), 60 * 60 * 1000)),
            ))
            self.last_answer = time.time()

    def undo(self):
        with self.lock:
            try:
                changes = self.col.undo()
            except Exception as e:
                raise AnkiError("Nothing to undo.") from e
            return getattr(changes, "operation", "") or "Undone"

    # -- notes --

    def note_types(self):
        with self.lock:
            return [{"id": m["id"], "name": m["name"], "fields": [f["name"] for f in m["flds"]]}
                    for m in self.col.models.all()]

    def add_note(self, notetype_name, deck_name, fields, tags):
        with self.lock:
            model = self.col.models.by_name(notetype_name or "Basic")
            if not model:
                raise AnkiError(f"no note type called {notetype_name!r}")
            note = self.col.new_note(model)
            names = [f["name"] for f in model["flds"]]
            for name, value in (fields or {}).items():
                if name in names:
                    note[name] = str(value)
            if not note.fields[0].strip():
                raise AnkiError(f"{names[0]} can't be empty")
            note.tags = [t for t in (tags or []) if t]
            deck_id = self.col.decks.id(deck_name or ADD_DECK)
            self.col.add_note(note, deck_id)
            self.request_sync_soon()
            return note.id

    def search(self, query, limit=50):
        with self.lock:
            found = list(self.col.find_notes(query or "added:7"))
            total = len(found)
            newest_first = not query or query.startswith("added:")
            ids = found[-limit:][::-1] if newest_first else found[:limit]
            out = []
            for nid in ids:
                note = self.col.get_note(nid)
                model = note.note_type()
                card = note.cards()[0] if note.cards() else None
                out.append({
                    "id": nid,
                    "notetype": model["name"],
                    "fields": dict(zip([f["name"] for f in model["flds"]], note.fields)),
                    "tags": note.tags,
                    "deck": self.col.decks.name(card.did) if card else "",
                    "due": card_due_text(self.col, card) if card else "",
                })
            return {"total": total, "notes": out}

    def update_note(self, note_id, fields, tags):
        with self.lock:
            note = self.col.get_note(note_id)
            names = [f["name"] for f in note.note_type()["flds"]]
            for name, value in (fields or {}).items():
                if name in names:
                    note[name] = str(value)
            if tags is not None:
                note.tags = [t for t in tags if t]
            self.col.update_note(note)
            self.request_sync_soon()

    def media_file(self, name):
        """Absolute path of a media file, or None. Only plain file names are allowed."""
        if not name or "/" in name or "\\" in name or name.startswith("."):
            return None
        path = os.path.join(self.col.media.dir(), name)
        return path if os.path.isfile(path) else None


def strip_bidi(text):
    """Anki wraps numbers in its translated strings with Unicode bidi isolates; drop them."""
    return text.replace("⁨", "").replace("⁩", "")


def card_due_text(col, card):
    if card.queue == -1:
        return "suspended"
    if card.type == 0:
        return "new"
    if card.queue in (1, 3) or card.type in (1, 3):
        return "learning"
    days = card.due - col.sched.today
    return "due today" if days <= 0 else f"in {days} d"


def guess_type(path):
    return mimetypes.guess_type(path)[0] or "application/octet-stream"



def main(argv):
    cmd = argv[1] if len(argv) > 1 else ""
    if cmd == "login":
        svc = AnkiService()
        user = input("AnkiWeb email: ").strip()
        svc.login(user, getpass.getpass("AnkiWeb password: "))
        print("Logged in; credentials saved to", AUTH_PATH)
    elif cmd == "import-desktop":
        hkey, endpoint, user = desktop_auth(argv[2] if len(argv) > 2 else "User 1")
        save_auth(hkey, endpoint, user)
        print(f"Reused Anki desktop's AnkiWeb login for {user}; saved to {AUTH_PATH}")
    elif cmd == "sync":
        svc = AnkiService()
        print(json.dumps(svc.sync(), indent=2))
        while svc.media_status().get("active"):
            print("media:", svc.media_status(), flush=True)
            time.sleep(5)
        print("cards:", svc.col.card_count())
        svc.col.close()
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
