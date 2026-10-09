# English Hub — architecture and design patterns

This document explains how English Hub (v3, multi-user) is put together and **why**,
pattern by pattern. Read it top to bottom once; afterwards use the
[pattern index](#pattern-index) to jump to what you need.

---

## 1. The big picture

```
 Friend's phone / laptop                       Raspberry Pi (home)
┌──────────────────────┐   HTTPS    ┌──────────────────┐  HTTP   ┌──────────────────────────────┐
│ Browser / home-screen│ ─────────▶ │ Tailscale Funnel │ ──────▶ │ waitress  (127.0.0.1:8090)   │
│ app (PWA)            │ ◀───────── │ TLS + public URL │ ◀────── │   └─ Flask app (hub/)        │
│  web/*.html          │            └──────────────────┘         │       ├─ blueprints (routes/)│
│  sw.js (push)        │                                         │       ├─ services            │
└──────────────────────┘                                         │       └─ background threads  │
        ▲                                                        │            │                 │
        │ Web Push (via Google/Apple/Mozilla push service)       │   data/hub.db (SQLite)       │
        └────────────────────────────────────────────────────────│   data/users/<id>/anki/      │
  Telegram app ◀──── Telegram Bot API ◀──────────────────────────│   data/vapid_private.pem     │
                                                                 └──────────────────────────────┘
                                                                        │ AnkiWeb sync (each
                                                                        ▼ user's own account)
```

- **One process** serves everything: pages, JSON API, and three background workers
  (Anki sync, reminders, Telegram bot). For 5–20 friends this is plenty and keeps
  operations simple: one service, one log, one data folder.
- **The app never listens on the network directly.** It binds to `127.0.0.1`;
  Tailscale Funnel terminates HTTPS and forwards to it. No router port-forwarding,
  no certificates to renew.
- **Front end:** plain HTML + vanilla JS pages, one per screen, sharing
  `web/static/app.js` and `app.css`. No build step.

### Folder map

```
hub/                      the Python package (back end)
  __init__.py             create_app() — application factory, wires everything
  __main__.py             CLI: serve, create-admin, invite, reset-link, import-legacy
  config.py               Config — all settings from environment variables
  db.py                   SQLite connections + numbered migrations
  security.py             login session, @login_required/@admin_required, CSRF, rate limits
  users.py                accounts, passwords, invite/reset links, settings     (data access)
  activity.py             shadowing sessions, practice ticks, streak maths      (data access)
  anki_service.py         one person's Anki collection (wraps the `anki` package)
  anki_pool.py            AnkiPool: opens/closes/syncs collections per user
  notify.py               Message, TelegramChannel, PushChannel, Notifier
  telegram_bot.py         bot inbox: links Telegram chats to accounts
  reminders.py            ReminderService: daily per-user reminder scheduler
  titles.py               clip-title lookup with SSRF protection
  routes/                 one Flask blueprint per area of the API
    pages.py  auth.py  api.py  anki.py  me.py  admin.py
web/                      pages, shared JS/CSS, service worker, manifest
tests/                    pytest suite (auth, isolation, CSRF, reminders)
deploy/                   systemd unit + install script
```

---

## 2. Request lifecycle

What happens for `PUT /api/practice/2026-10-10`:

1. **Tailscale Funnel** receives HTTPS, forwards plain HTTP to `127.0.0.1:8090`
   with `X-Forwarded-For/Proto/Host` headers.
2. **waitress** (production WSGI server, a thread pool of 8) hands the request to Flask.
3. **ProxyFix** middleware rewrites `request.remote_addr`/scheme from those headers,
   so rate limits see the friend's real IP.
4. `before_request` hooks run, in order:
   - `security.load_user` — reads the signed session cookie, loads the user, puts it
     on `g.user` (or `None`).
   - `security.check_same_origin` — refuses cross-site writes (CSRF).
5. The **blueprint view** runs. `@login_required` returns 401 if `g.user` is `None`.
6. The view calls a **data-access function** with the request's connection:
   `activity.set_practice(get_db(), g.user["id"], date, done, note)`.
7. The response is JSON; `after_request` adds security headers; `teardown_appcontext`
   closes the DB connection.

---

## 3. Patterns, one by one

### 3.1 Application Factory — `hub/__init__.py: create_app(config)`

**What:** instead of a global `app = Flask(...)`, a function builds and returns a
fully wired app from a `Config` object.

**Why here:**
- Tests create a fresh app per test with a temporary data folder and workers off
  (`tests/conftest.py`), so tests never touch real data or each other.
- The CLI (`python -m hub invite`) and the server share the same wiring.
- There is exactly one place to read to understand how the app is assembled.

```python
def create_app(config=None):
    app = Flask(__name__)
    app.config.from_object(config or Config())
    db.migrate(...)
    app.extensions["hub"] = Services(pool=..., notifier=..., reminders=...)
    for module in (pages, auth, api, anki, me, admin):
        app.register_blueprint(module.bp)
    return app
```

### 3.2 Configuration object — `hub/config.py`

All settings come from environment variables, read once into a `Config` object,
each with a safe default for local development. Production values come from the
systemd unit and `~/.config/english-hub/hub.env`. Secrets that the app can make itself
(the cookie-signing `secret_key`, VAPID keys) are generated on first start and kept
in the data folder with mode `0600`. **Rule:** no module reads `os.environ` directly;
they read `current_app.config` or receive values through constructors.

### 3.3 Blueprints (modular routing) — `hub/routes/*.py`

Each area of the API is a Flask **Blueprint** with its own URL prefix and its own
guard:

| Blueprint | Prefix | Guard |
|---|---|---|
| `pages` | `/`, `/static`, `/icons`, `/anki-media` | per page |
| `auth` | `/api/auth` | public, rate-limited |
| `api` | `/api` | `@login_required` per view |
| `anki` | `/api/anki` | `before_request` login + Anki available |
| `me` | `/api/me` | `before_request` login |
| `admin` | `/api/admin` | `before_request` admin |

Putting the guard in the blueprint's `before_request` means **a new route added to
`admin.py` is protected automatically**; you can't forget the decorator.

### 3.4 Data-access functions ("repository" modules) — `users.py`, `activity.py`

SQL lives in a few modules of plain functions, never in views. Every function takes
an **open connection as its first argument**:

```python
def delete_session(conn, user_id, session_id):
    with conn:   # transaction: commit on success, roll back on error
        cur = conn.execute("DELETE FROM sessions WHERE id = ? AND user_id = ?", (session_id, user_id))
    return cur.rowcount == 1
```

- Passing the connection in (dependency injection) lets the same function serve a
  request (`get_db()`), a background thread (`db.connect(path)`) and a test.
- **Tenant isolation lives here:** every query on personal data has
  `WHERE user_id = ?`. There is no function that reads across users, so a view
  *can't* accidentally return someone else's rows. Updates/deletes include
  `user_id` too, so guessing another row's id gives 404, not access.
- Writes commit their own transaction with `with conn:`.

This is a lightweight cousin of the Repository pattern: no classes or ORM, because
the schema is small and plain SQL stays readable.

### 3.5 Unit of work per request — `db.get_db()` / `close_db()`

One SQLite connection per request, created lazily on first use and stored on
Flask's `g`; `teardown_appcontext` closes it. Background threads never use `g`; they
open and close their own connection. SQLite runs in **WAL mode**, so readers don't
block the writer.

### 3.6 Versioned migrations — `db.MIGRATIONS`

The schema is a list of SQL scripts. The database stores how many have run in
`PRAGMA user_version`; `migrate()` runs the rest at start-up, each in a transaction.

**Rules:** never edit a script that has shipped; to change the schema, **append** a
new one (e.g. `ALTER TABLE users ADD COLUMN ...`). This makes upgrades automatic and
repeatable on every machine.

### 3.7 Service layer + Registry — `Services` in `app.extensions["hub"]`

Long-lived objects (Anki pool, notifier, Telegram bot, reminder service) are created
once in the factory and stored in a small `Services` dataclass. Views get them with
`services().pool`, etc. This is a simple **registry / service locator**: one place
that owns object lifetimes, with no global variables scattered across modules.

### 3.8 Decorator (guards) — `security.login_required`, `admin_required`

Cross-cutting checks are Python decorators wrapped around views. `admin_required`
is itself built on `login_required` (composition). The decorators know whether the
caller is a page (redirect to `/login?next=…`) or the API (JSON 401/403).

### 3.9 Signed-cookie session with a version counter (revocation)

Login state is Flask's signed session cookie containing `{uid, ver}`. On every
request `ver` is compared with `users.session_version`. Changing a password,
"Log out everywhere", or an admin turning an account off **increments the
counter**, which instantly invalidates every other device's cookie. This gives
server-side revocation without a sessions table.

Cookie flags: `HttpOnly` (JS can't read it), `Secure` (HTTPS only), `SameSite=Lax`.

### 3.10 Defence in depth against CSRF — `security.check_same_origin`

1. `SameSite=Lax` already stops browsers sending the cookie on cross-site POSTs.
2. Every non-GET request must also come from our own origin: modern browsers send
   `Sec-Fetch-Site`; it must be `same-origin`. Older ones send `Origin`; it must
   match `PUBLIC_URL`.

### 3.11 Capability tokens (one-time links) — `users.create_link` / `use_link`

Invites and password resets are **one-time random tokens** in a URL. Only a SHA-256
hash is stored (a leaked database doesn't leak working links). Links expire (7 days
for invites, 2 for resets). Redeeming **claims the link first with a conditional
UPDATE** (`WHERE used_at IS NULL`) so two people can't redeem it at once, and
releases it again if the form input is invalid.

The same idea secures Anki media: cards render in a sandboxed iframe that can't send
our cookie, so media URLs carry a per-user secret: `/anki-media/<media_key>/file.mp3`.

### 3.12 Object pool with idle eviction — `anki_pool.AnkiPool`

An open Anki collection costs memory, so the pool:
- opens a user's collection **lazily** on first use (`pool.get(user_id)`),
- keeps it in a dict, guarded by a lock,
- closes it after 30 minutes unused (re-checking under the lock so a request that
  just grabbed it isn't pulled out from under),
- runs **one** background thread that syncs whichever open collections are due,
  instead of one thread per user.

Each `AnkiService` has its own `RLock`, so two requests from the same person are
serialised while different people run in parallel.

### 3.13 Strategy / Adapter — `AccountStore` for AnkiWeb logins

`AnkiService` needs to load and save an AnkiWeb login but shouldn't know *where*.
It receives a store object with `load() / save() / clear()`. `AccountStore` stores
it in the `anki_accounts` table for one user. (The single-user v2 kept it in a JSON
file. Swapping the store needed no change to the Anki logic.)

### 3.14 Strategy + Facade for notifications — `notify.py`

Each channel is a class with the same interface:

```python
class TelegramChannel:  name = "telegram"; def send(self, user_id, msg) -> int
class PushChannel:      name = "push";     def send(self, user_id, msg) -> int
```

`Notifier([telegram, push]).send(user_id, msg)` (the **facade**) sends a channel-neutral
`Message(title, body, url)` on every channel and isolates failures (one broken
channel doesn't stop the others). **To add email or Zalo:** write one class with
`name` and `send`, and add it to the list in `create_app`.

### 3.15 Background workers (scheduler, poller) — `reminders.py`, `telegram_bot.py`

Daemon threads started by `start_workers(app)`, never in tests:

- **ReminderService** wakes every minute. For each user it converts "now" to *their*
  timezone. Once it's past their reminder time, it checks today's habits and sends
  at most one message. `reminder_last_date` makes it **idempotent**: a restart or a
  second tick on the same day sends nothing more. If the server was down for more
  than 3 hours past the reminder time, it skips the day instead of nagging at
  midnight.
- **TelegramBot** long-polls `getUpdates` (no webhook needed, so nothing extra is
  exposed). It stores the update offset in `app_state` so a restart doesn't replay
  messages. Linking is a deep link `t.me/<bot>?start=<token>`: the friend presses
  *Start* and the bot matches the token. No codes to copy.

Pure logic (`habit_status`, `build_message`, `activity.streak`) is kept separate from
the threads so it can be unit-tested with fixed dates.

### 3.16 Progressive Web App + Web Push — `web/manifest.webmanifest`, `web/sw.js`

- The **manifest** makes the site installable ("Add to Home Screen") with its own icon.
  iPhones *require* this for web push.
- The **service worker** (`/sw.js`, served from the root so it controls the whole
  site) only handles `push` (show the notification) and `notificationclick` (open
  the app). It caches nothing, on purpose: the app needs the server anyway.
- **VAPID**: the server has a key pair (`data/vapid_private.pem`). The browser
  subscribes with the public key; the server signs pushes with the private key.
  Subscriptions that the push service reports as gone (404/410) are deleted
  automatically.

### 3.17 Input validation at the edge, sanitisation at render

- Every value from the client is validated in the data-access layer
  (`clean_session`, `check_username`, `check_timezone`, …) and turned into a 400 with a
  readable message (`AccountError`, `ValueError`).
- Shadowing notes are limited HTML; the page strips every tag except basic
  formatting before showing them (as in v1).
- **SSRF guard** (`titles.py`): the server only fetches clip titles from hosts that
  resolve to public IPs, and re-checks every redirect, so a friend can't make the
  Pi probe your home network.

### 3.18 Rate limiting — `security.RateLimiter`

A small in-memory sliding window, one per purpose (`login`, `links`, `anki-login`),
created per app (so tests don't share counters). Keys are both IP and username, so
one attacker can't lock everyone out, and one account can't be brute-forced from
many IPs quickly.

---

## 4. Data model

```
users ──┬──< sessions          (user_id, date, loggedAt, clip, reps, confidence, notes)
        ├──< practice_days     (user_id, date) PK, note
        ├──1 anki_accounts     AnkiWeb session key (never the password)
        ├──1 telegram_links    chat_id
        ├──< telegram_link_tokens   15-minute tokens for linking
        ├──< push_subscriptions     one per browser/device
        └──< invites           invite/reset links (hashed tokens)
app_state                      key/value (Telegram offset)
data/users/<id>/anki/          that user's Anki collection, media, backups
```

`ON DELETE CASCADE` everywhere: deleting a user row removes all their data.

---

## 5. Security model (summary)

| Threat | Mitigation |
|---|---|
| Stranger signs up | Invite-only, one-time links that expire |
| Password guessing | scrypt hashes (werkzeug), rate limit per IP + username |
| Stolen/old device | "Log out everywhere", password change, admin "Turn off" — all bump `session_version` |
| Friend reads another's data | Every query scoped by `user_id`; tests prove it (`test_each_user_sees_only_their_own_log`) |
| CSRF | SameSite=Lax + same-origin check |
| XSS via notes/cards | Notes sanitised on render; Anki cards in a sandboxed iframe without same-origin |
| SSRF via title lookup | Public-IP-only fetch, redirects re-checked |
| Leaked DB | Tokens stored hashed; passwords scrypt; AnkiWeb stores a session key, not the password |
| Downloading the DB | Only allow-listed files are served; app listens on localhost only |
| Admin snooping | Admin API exposes accounts and last-active date only, never logs |

Known limits (fine for a friends app): rate limits reset on restart; the SSRF check
resolves DNS separately from the fetch (DNS-rebinding window); one server process,
so no horizontal scaling.

---

## 6. How to extend

- **New API endpoint:** add a view to the right blueprint; put SQL in a data-access
  function that takes `(conn, user_id, …)`; add a test in `tests/`.
- **New table/column:** append a script to `db.MIGRATIONS`.
- **New notification channel:** class with `name` + `send(user_id, msg)`, add it to
  `Notifier` in `create_app`.
- **New habit** (e.g. AI sentence practice): store per-user rows, add it to
  `reminders.habit_status` and the Today page's `habits()`.
- **New page:** `web/<page>.html` using `app.css`/`app.js`, then register it in
  `routes/pages.py` (`PRIVATE_PAGES`).

## Pattern index

| Pattern | Where |
|---|---|
| Application factory | `hub/__init__.py` |
| Config object | `hub/config.py` |
| Blueprints + per-blueprint guards | `hub/routes/` |
| Data-access functions, tenant scoping | `hub/users.py`, `hub/activity.py` |
| Unit of work per request | `hub/db.py` |
| Versioned migrations | `hub/db.py` |
| Service registry | `Services` in `hub/__init__.py` |
| Decorators (auth guards) | `hub/security.py` |
| Versioned signed session | `hub/security.py` |
| Capability tokens | `hub/users.py`, `/anki-media/<key>/` |
| Object pool + idle eviction | `hub/anki_pool.py` |
| Strategy / adapter (login store) | `AccountStore` |
| Strategy + facade (notifications) | `hub/notify.py` |
| Scheduler / poller workers | `hub/reminders.py`, `hub/telegram_bot.py` |
| PWA + Web Push | `web/manifest.webmanifest`, `web/sw.js` |
| Rate limiter | `hub/security.py` |
