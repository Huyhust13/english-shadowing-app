<p align="center">
  <img src="icons/apple-touch-icon.png" width="96" height="96" alt="English Hub icon">
</p>

# English Hub

A small, self-hosted web app that brings **three daily English habits** together in one
place, with one streak:

1. **Vocab** — your real **Anki** collection, synced with your AnkiWeb account. Study your
   decks, add cards and browse notes here, just like on AnkiWeb or Anki desktop; reviews
   done here, on Anki desktop or on AnkiDroid all end up in the same collection.
2. **Sentence practice** — practise writing and saying sentences with an AI tutor. For now
   this is a placeholder with a **"done today"** tick (and an optional note) that counts
   towards the streak; AI modes come later.
3. **Shadowing** — the original Shadowing Tracker, unchanged: log the clip, reps, how it
   felt, and notes/script.

The **Today** page shows what's done today, a streak for each habit, an "all three done"
streak and the last 14 days at a glance.

> This branch is the new English Hub. The Pi at `english.nvh` still runs the original
> Shadowing Tracker; the deployment sections further down describe that setup.

## English Hub quick start (this machine)

```sh
deploy/install-hub.sh          # venv + `anki` package, systemd user service on :8090
```

Then open <http://localhost:8090>, go to **Vocab** and log in with your AnkiWeb email and
password (only an AnkiWeb session key is stored, in `~/.config/english-hub/ankiweb.json`,
mode `0600`). The first sync downloads your collection and media (a few minutes).

If Anki desktop on the same machine is already logged in, you can reuse its login instead:

```sh
~/.local/share/english-hub/venv/bin/python anki_service.py import-desktop
```

| Where | What |
|---|---|
| `~/.local/share/english-hub/data/shadowing.db` | shadowing sessions and practice ticks |
| `~/.local/share/english-hub/data/anki/` | the synced Anki collection, media and daily backups |
| `~/.local/share/english-hub/venv/` | Python venv with the `anki` package |
| `journalctl --user -u english-hub -f` | logs |

### On the Pi (next to the old Shadowing Tracker)

The Pi runs English Hub on port 8090 (<http://english.nvh:8090>). It uses the original
app's database, `~/shadowing-app/data/shadowing.db` (the hub only adds its
`practice_days` table), so the old history and the Telegram reminder carry on. Since
2026-10-08 the old web app (`shadowing-tracker`, port 80) is disabled; the reminder's
link points to the hub (`SHADOWING_URL=http://192.168.10.21:8090/`).

```sh
rsync -av --exclude .git --exclude data/ --exclude __pycache__ --exclude .claude \
  ./ huy@english.nvh:/home/huy/english-hub/
ssh huy@english.nvh 'cd ~/english-hub && SHADOWING_DB=/home/huy/shadowing-app/data/shadowing.db ./deploy/install-hub.sh'
```

Then log in to AnkiWeb on the Vocab page (or copy `~/.config/english-hub/ankiweb.json`
with mode `0600` from a machine that's already logged in). The first sync downloads the
collection and ~15,000 media files (about 6 minutes on a Pi 4). Re-run the same two
commands to update.

### How the Anki part works

- `anki_service.py` uses the official [`anki`](https://pypi.org/project/anki/) Python
  package — the same engine as Anki desktop — on its **own** collection in `data/anki/`.
  It never touches Anki desktop's files.
- It syncs with AnkiWeb at start-up, every 10 minutes, a minute after your last review,
  after adding/editing a card, and when you press **Sync now**.
- **AnkiWeb stays the source of truth.** The app only does normal syncs, or a full
  *download* when its local copy is empty. It **never uploads** a full collection. If
  AnkiWeb ever asks for a full sync (copies diverged), the Vocab page shows
  **Replace with AnkiWeb copy**, which downloads AnkiWeb's version here.
- Cards are rendered with your note types' templates and CSS inside a sandboxed frame;
  audio plays automatically (press **R** to replay). Shortcuts: **Space** show answer /
  Good, **1–4** answer, **Z** undo.
- New cards go to the **My Words** deck by default (created on first add).
- Avoid reviewing the *same* deck on two devices at the very same moment; otherwise
  syncing merges reviews just like it does between Anki desktop and AnkiDroid.

## What is shadowing, and why track it?

**Shadowing** is a speaking technique: you play a short clip of a native speaker and
repeat it out loud at the same time, or a split second behind, copying not just the
words but the rhythm, stress, intonation and linking. Done for a few minutes every day,
it builds pronunciation and speaking fluency faster than reading or listening alone.

What makes it work is **consistency** and **noticing**:

- **Consistency** — a short session every day beats a long one once a week. A visible
  streak and a reminder make it much easier to keep going.
- **Noticing** — writing down *what* was hard ("linking in *check it out*", "stress on
  *auTONomous*") turns a vague feeling into something you can fix, and lets you see
  progress when you come back to the same clip later.

The Shadowing Tracker is built around those two things. It's deliberately small: no
accounts, no ads, no cloud service — your practice log lives on your own machine.

**Who it's for:** English learners (originally an IELTS learner working towards
speaking band 7) who practise with YouTube videos, TED talks, podcasts or any clip with
a link, and want a lightweight log rather than a full course platform.

## Features

**Daily logging**
- Log a session in a few seconds: clip title, link, repetitions, and how it felt
  (**Rough / OK / Smooth**).
- **Automatic clip titles** — paste a YouTube, TED or other link and the title fills
  itself in (it never overwrites a title you typed).
- If you log again later the same day, the form starts pre-filled with today's clip.

**Notes and scripts**
- A **rich-text notes editor** for the transcript and your observations: **bold**,
  *italic*, underline, strikethrough, highlight, bullet and numbered lists.
- Shortcuts: `Ctrl+B`, `Ctrl+I`, `Ctrl+U`, `Ctrl+Shift+H` (highlight).
- Pasting a script from a web page pastes plain text, so it doesn't bring the site's
  fonts and colours along.
- Long notes are collapsed in the history with a **Show more** button.

**Progress**
- **Day streak** counter: consecutive days with at least one session. Not having
  practised *yet* today doesn't reset it — until midnight it shows yesterday's streak
  with a "Log today to keep the streak alive" hint.
- **Last 14 days** bar chart; bar height is the number of reps that day.
- **History** of every session, newest first, with links back to the clips.

**Managing entries**
- **Edit** any past session, including its date (useful when you forgot to log
  yesterday).
- **Delete** with a two-step confirm (click *Delete*, then *Delete?* within 3 seconds).

**Everywhere**
- Works on phone and desktop; can be added to a phone's home screen with its own icon.
- Light and dark themes (follows the system, with a manual toggle).
- **Daily Telegram reminder** at a time you choose, only on days with nothing logged,
  mentioning the streak you're about to lose.

## How it works

```
  Phone / laptop browser                      Raspberry Pi (or any Linux box)
 ┌──────────────────────┐   HTTP (LAN or    ┌──────────────────────────────────────┐
 │ index.html           │   Tailscale)      │ server.py  (systemd service, :80)    │
 │  - form, streak,     │ ────────────────▶ │  - serves the page and icons         │
 │    chart, history    │ ◀──────────────── │  - JSON API  /api/sessions …         │
 │  - rich-text editor  │      JSON         │  - /api/title ──▶ YouTube oEmbed /   │
 └──────────────────────┘                   │                   the linked page    │
                                            │            │                         │
                                            │            ▼                         │
                                            │   data/shadowing.db  (SQLite)        │
                                            │            ▲ read-only               │
                                            │            │                         │
                                            │ remind.py  (systemd timer, daily) ───┼──▶ Telegram
                                            └──────────────────────────────────────┘
```

- **Front end** — one HTML file per page (`today.html`, `vocab.html`, `practice.html`,
  `shadowing.html`) plus shared `static/app.css` and `static/app.js`: plain HTML, CSS and
  JavaScript, no framework and no build step. Pages talk to the server with `fetch()`.
- **Back end** — `server.py` uses only the standard library (`http.server`, `sqlite3`,
  `urllib`). The Anki part, `anki_service.py`, needs the `anki` package; without it the
  server still runs and reports Vocab as unavailable.
- **Storage** — one SQLite file, `data/shadowing.db`. Backing up the app means copying
  that file.
- **Clip titles** — the browser can't read other websites directly (CORS), so it asks
  the server: `GET /api/title?url=…`. For YouTube the server uses YouTube's official
  oEmbed API; for other sites it reads the page's `og:title`, falling back to `<title>`.
- **Reminder** — a systemd *user timer* runs `deploy/remind.py` once a day. It opens the
  database read-only, so it still works if the web server is down, and sends a message
  through the Telegram Bot API only if no session exists for today.

## Project structure

```
.
├── today.html                    Today page: three habits, streaks, last 14 days
├── vocab.html                    Anki: decks, study, add, browse, sync/login
├── practice.html                 Sentence practice (placeholder + daily tick)
├── shadowing.html                The original Shadowing Tracker page
├── static/app.css, app.js        Shared styles, navigation and helpers
├── server.py                     Web server, JSON API, SQLite access, title lookup
├── anki_service.py               Anki collection synced with AnkiWeb (needs `anki`)
├── requirements.txt              `anki` for the Vocab part
├── README.md
├── .gitignore                    Ignores data/ and Python caches
├── icons/
│   ├── icon.svg                  Browser-tab icon (vector)
│   ├── icon-32.png               Fallback favicon (also served as /favicon.ico)
│   ├── apple-touch-icon.png      Phone home-screen icon (180×180)
│   └── make_icons.py             Draws all three from one definition (pure Python)
├── deploy/
│   ├── install-hub.sh            English Hub as a systemd user service on :8090
│   ├── english-hub.service       Unit template used by install-hub.sh
│   ├── install.sh                Installs the systemd service on port 80 (sudo)
│   ├── shadowing-tracker.service Service template used by install.sh
│   ├── setup-telegram.py         One-time Telegram bot connection
│   ├── install-reminder.sh       Installs/removes the daily reminder timer (no sudo)
│   └── remind.py                 The reminder: checks today's log, messages Telegram
└── data/                         Created at first start; git-ignored
    └── shadowing.db              All your sessions
```

Outside the repo, the reminder keeps its credentials in
`~/.config/shadowing-tracker/telegram.env` (mode `0600`) so they're never committed.

### Data model

`practice_days(date, note, markedAt)` holds the sentence-practice ticks (one row per
day). Anki data stays in the Anki collection. Shadowing sessions are in `sessions`:

| Column       | Type    | Meaning                                                        |
|--------------|---------|----------------------------------------------------------------|
| `id`         | integer | Primary key                                                    |
| `date`       | text    | Practice day, `YYYY-MM-DD` in the browser's local time         |
| `loggedAt`   | text    | When it was logged (ISO timestamp); unique, used to skip duplicates on import |
| `clipTitle`  | text    | Clip name (up to 500 chars)                                    |
| `clipUrl`    | text    | Link to the clip (optional)                                    |
| `reps`       | integer | Repetitions, 1–1000                                            |
| `confidence` | integer | 1 = Rough, 2 = OK, 3 = Smooth, or empty                        |
| `notes`      | text    | Notes/script as limited HTML (up to 200,000 chars)             |

The server validates every field before writing. The page cleans notes before showing
them: only formatting tags (bold, italic, underline, strikethrough, highlight, lists,
line breaks) are kept, and every attribute is removed, so notes can't run scripts.

### API

| Method | Path                      | Body / query            | Returns |
|--------|---------------------------|-------------------------|---------|
| GET    | `/api/summary`            | —                       | `{shadow, practice, anki}` per-day activity, for streaks |
| PUT    | `/api/practice/<date>`    | `{done, note}`          | ticks (or unticks) sentence practice for that day |
| GET    | `/api/anki/state`         | —                       | login, sync and media-sync status |
| GET    | `/api/anki/decks`         | —                       | deck tree with new/learn/due counts |
| GET    | `/api/anki/next?deck=<id>`| —                       | next card to study (rendered HTML, audio, button labels) |
| POST   | `/api/anki/answer`        | `{cardId, rating 1–4, ms}` | answers the card |
| POST   | `/api/anki/undo`          | —                       | undoes the last action |
| POST   | `/api/anki/sync`          | `{forceDownload?}`      | syncs with AnkiWeb |
| POST   | `/api/anki/login`         | `{username, password}`  | logs in to AnkiWeb and syncs |
| GET/POST | `/api/anki/notes`       | `?q=<search>` / `{notetype, deck, fields, tags}` | search notes / add a note |
| PUT    | `/api/anki/notes/<id>`    | `{fields, tags}`        | edits a note |
| GET    | `/anki-media/<file>`      | —                       | a media file from the collection |
| GET    | `/api/sessions`           | —                       | all sessions, oldest first, with `id` |
| POST   | `/api/sessions`           | one session (JSON)      | `201 {"ok": true}` |
| POST   | `/api/sessions/import`    | list of sessions        | `201`; duplicates (same `loggedAt`) are skipped |
| PUT    | `/api/sessions/<id>`      | full session (JSON)     | `200`, or `404` if no such id |
| DELETE | `/api/sessions/<id>`      | —                       | `200`, or `404` if no such id |
| GET    | `/api/title?url=<link>`   | —                       | `{"title": "…"}`; `400` for non-http links, `502` if the page can't be fetched |

A session is `{date, loggedAt, clipTitle, clipUrl, reps, confidence, notes}`. Invalid
input returns `400 {"error": "…"}`.

### Design choices

- **No dependencies, no build.** Python's standard library and one HTML file, so it runs
  on a fresh Raspberry Pi OS and is easy to read end to end.
- **Allow-listed files only.** The server serves the page, the icons and the API, and
  nothing else — the database and scripts in the same folder can't be downloaded.
- **Least privilege.** The service runs as your normal user; systemd grants it only the
  right to bind port 80 (`CAP_NET_BIND_SERVICE`), not root.
- **No login — keep it private.** There are no accounts, so anyone who can reach the
  app can read and change the log. Use it on your home network or over a private VPN
  such as Tailscale; **don't** expose it to the internet with port forwarding.
- **Migration from the first version.** The very first version stored sessions in the
  browser's `localStorage`. If a browser still has those, the page imports them into
  SQLite once and then clears them.

---

## Run it locally

Needs Python 3.9+. Without the `anki` package everything except Vocab works:

```sh
python3 server.py
```

With Anki (what `deploy/install-hub.sh` sets up):

```sh
python3 -m venv ~/.local/share/english-hub/venv
~/.local/share/english-hub/venv/bin/pip install -r requirements.txt
~/.local/share/english-hub/venv/bin/python server.py
```

Open <http://localhost:8090>. The database is created on first start.

| Variable       | Default               | Purpose                         |
|----------------|-----------------------|---------------------------------|
| `PORT`         | `8090`                | Port to listen on               |
| `HOST`         | `0.0.0.0`             | Address to bind                 |
| `SHADOWING_DB` | `data/shadowing.db`   | Path to the SQLite database     |
| `ANKI_DIR`     | `data/anki`           | Where the synced Anki collection lives |
| `ANKI_AUTH`    | `~/.config/english-hub/ankiweb.json` | AnkiWeb session key |

## Deploy to a server (e.g. a Raspberry Pi)

These steps run the app as a systemd service on port 80, starting on boot. They
assume a Debian-based server (Raspberry Pi OS, Ubuntu) with `python3` and `curl`,
and that you can `ssh` into it with sudo rights. The examples use the SSH host
`pi-server` and the folder `/home/huy/shadowing-app`; change them to yours.

### 1. Copy the app to the server

From your machine, in this repo:

```sh
rsync -av --exclude .git --exclude data/ --exclude __pycache__ \
  ./ pi-server:/home/huy/shadowing-app/
```

Or clone it on the server instead (into a folder that doesn't exist yet):

```sh
ssh pi-server 'git clone git@github.com:Huyhust13/english-shadowing-app.git /home/huy/shadowing-app'
```

### 2. (Optional) Bring your existing history

To move sessions from another machine, copy a consistent snapshot of its database
(safe even while the app is running there):

```sh
python3 -c "import sqlite3; s=sqlite3.connect('data/shadowing.db'); d=sqlite3.connect('/tmp/shadowing.db'); s.backup(d); d.close()"
ssh pi-server 'mkdir -p /home/huy/shadowing-app/data'
rsync -av /tmp/shadowing.db pi-server:/home/huy/shadowing-app/data/shadowing.db
```

Do this **before** you start logging on the server, or you'll overwrite its sessions.

### 3. Install the service

```sh
ssh pi-server 'cd /home/huy/shadowing-app && sudo ./deploy/install.sh'
```

`deploy/install.sh`:

- installs `/etc/systemd/system/shadowing-tracker.service`, running `server.py` as
  your user on port 80 (it gets only the capability to bind port 80, not root);
- enables and starts it, so it comes back after a reboot;
- adds `english.nvh` → `127.0.0.1` to the **server's** `/etc/hosts` (a backup is saved
  next to it) and waits for `http://english.nvh/` to answer.

### 4. Open it

From any device on the same network, use the server's IP:

```sh
ssh pi-server 'hostname -I'     # first address is usually the LAN IP
```

then browse to `http://<server-ip>/`.

`english.nvh` only resolves on the server itself. To use the name from another
computer, add a line to that computer's `/etc/hosts`:

```
192.168.10.21	english.nvh
```

On a phone, use the IP, or add the page to your home screen (it has its own icon).

## Access from outside your home network

Use a private VPN rather than opening a port to the internet (the app has no login).
If the server is on [Tailscale](https://tailscale.com):

1. Install the Tailscale app on your phone and sign in to the same tailnet as the
   server.
2. Open `http://<server-tailscale-name>/` — e.g. `http://pi-server/` with MagicDNS —
   or the server's `100.x.y.z` Tailscale IP.

This works both at home and away, so it's also a good choice for the reminder's
`SHADOWING_URL` (below). A name like `english.nvh` on a phone would additionally need a
DNS server that knows it (e.g. dnsmasq on the server plus Tailscale split DNS).

## Daily Telegram reminder (optional)

At a set time each day, the server checks the database and, if nothing was logged
that day, messages you on Telegram (mentioning the streak at risk).

### 1. Connect a bot (once)

On the server, in a real terminal (it asks for the token with hidden input):

```sh
ssh -t pi-server 'cd /home/huy/shadowing-app && python3 deploy/setup-telegram.py'
```

Follow the prompts: create a bot with [@BotFather](https://t.me/BotFather), paste its
token, then send the bot any message. The token and chat id are saved to
`~/.config/shadowing-tracker/telegram.env` (mode `0600`, outside the repo — never
commit it). A test message is sent.

Already set up on another machine? Copy that file instead:

```sh
ssh pi-server 'mkdir -p ~/.config/shadowing-tracker && chmod 700 ~/.config/shadowing-tracker'
rsync -a --chmod=F600 ~/.config/shadowing-tracker/telegram.env \
  pi-server:.config/shadowing-tracker/telegram.env
```

### 2. Install the timer

```sh
ssh pi-server 'sudo loginctl enable-linger $USER'
ssh pi-server 'cd /home/huy/shadowing-app && SHADOWING_URL=http://<server-ip>/ ./deploy/install-reminder.sh 20:00'
```

- `enable-linger` is needed so the reminder runs even when you're not logged in.
- `20:00` is the reminder time in the server's timezone (24h `HH:MM`, default `20:00`).
- `SHADOWING_URL` is the link in the message; default `http://english.nvh/`, which
  phones can't open, so set it to the server's IP or Tailscale name.

Check it:

```sh
ssh pi-server 'systemctl --user list-timers shadowing-reminder.timer'
ssh pi-server 'cd /home/huy/shadowing-app && python3 deploy/remind.py --dry-run'   # prints, doesn't send
```

Remove it with `./deploy/install-reminder.sh --remove`.

Run the reminder on **one** machine only — the one with the live database —
otherwise you'll get reminders on days you did practise.

## Update a running deployment

```sh
rsync -av --exclude .git --exclude data/ --exclude __pycache__ \
  ./ pi-server:/home/huy/shadowing-app/
ssh pi-server 'sudo systemctl restart shadowing-tracker'
```

(or `git pull` on the server, then restart). The `data/` exclude keeps the server's
database untouched. Reminder changes need no restart; changes to
`deploy/install-reminder.sh` itself need it re-run.

## Back up

The whole history is one file. To copy a consistent snapshot from the server:

```sh
ssh pi-server "python3 -c \"import sqlite3; s=sqlite3.connect('/home/huy/shadowing-app/data/shadowing.db'); d=sqlite3.connect('/tmp/shadowing-backup.db'); s.backup(d); d.close()\""
rsync -av pi-server:/tmp/shadowing-backup.db ./shadowing-$(date +%F).db
```

## Change the icon

Edit the colours or shapes at the top of `icons/make_icons.py`, then:

```sh
python3 icons/make_icons.py
```

and deploy. Browsers cache icons for a day; a hard refresh (`Ctrl+Shift+R`) shows the
new one sooner.

## Troubleshooting

| Problem | Check |
|---|---|
| Page doesn't load | `ssh pi-server 'systemctl status shadowing-tracker'` and `journalctl -u shadowing-tracker -n 50` |
| "Couldn't reach the server" on the page | The service is down or the device can't reach the server (wrong network, VPN off) |
| Port 80 already in use | `sudo ss -ltnp \| grep ':80 '` on the server; stop the other service, or set `Environment=PORT=…` in the unit file |
| `english.nvh` opens nothing on a laptop/phone | It only exists in the server's `/etc/hosts` — use the IP, or add it to that device's hosts file |
| Title doesn't auto-fill | The server needs internet access; some sites block scripted requests — type the title instead |
| Streak looks off by a day | Dates use the browser's local time; check the device's timezone |
| No Telegram reminder | `systemctl --user status shadowing-reminder.service`, `loginctl show-user $USER -p Linger` (must be `yes`), and run `remind.py --dry-run` |
| Old icon in the browser tab | Hard refresh (Ctrl+Shift+R); on a phone, re-add the home-screen shortcut |

To stop and remove the app from a machine:

```sh
sudo systemctl disable --now shadowing-tracker
sudo rm /etc/systemd/system/shadowing-tracker.service && sudo systemctl daemon-reload
```
