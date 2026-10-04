# Shadowing Tracker

A small self-hosted app for logging daily English shadowing practice: which clip you
shadowed, how many reps, how it felt, and notes on tricky words. It shows your streak
and the last 14 days, and can send a Telegram reminder on days you haven't practised.

- **Backend:** one Python file (`server.py`), standard library only — no `pip install`.
- **Storage:** SQLite at `data/shadowing.db`, so every device sees the same history.
- **Clip titles:** paste a YouTube, TED or other link and the title fills in automatically.

## Run it locally

Needs Python 3.9+.

```sh
python3 server.py
```

Open <http://localhost:8080>. The database is created on first start.

| Variable       | Default               | Purpose                         |
|----------------|-----------------------|---------------------------------|
| `PORT`         | `8080`                | Port to listen on               |
| `HOST`         | `0.0.0.0`             | Address to bind                 |
| `SHADOWING_DB` | `data/shadowing.db`   | Path to the SQLite database     |

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

Or clone it on the server instead:

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
  phones can't open, so set it to the server's IP.

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

## Troubleshooting

| Problem | Check |
|---|---|
| Page doesn't load | `ssh pi-server 'systemctl status shadowing-tracker'` and `journalctl -u shadowing-tracker -n 50` |
| Port 80 already in use | `sudo ss -ltnp \| grep ':80 '` on the server; stop the other service, or set `Environment=PORT=…` in the unit file |
| `english.nvh` opens nothing on a laptop/phone | It only exists in the server's `/etc/hosts` — use the IP, or add it to that device's hosts file |
| Title doesn't auto-fill | The server needs internet access; some sites block scripted requests — type the title instead |
| No Telegram reminder | `systemctl --user status shadowing-reminder.service`, `loginctl show-user $USER -p Linger` (must be `yes`), and run `remind.py --dry-run` |
| Old icon in the browser tab | Hard refresh (Ctrl+Shift+R); on a phone, re-add the home-screen shortcut |

To stop and remove the app from a machine:

```sh
sudo systemctl disable --now shadowing-tracker
sudo rm /etc/systemd/system/shadowing-tracker.service && sudo systemctl daemon-reload
```

## Project layout

```
server.py                  web server + JSON API + SQLite
index.html                 the whole front end (no build step)
icons/                     app icons; regenerate with python3 icons/make_icons.py
deploy/install.sh          systemd service on port 80 (sudo)
deploy/install-reminder.sh daily Telegram reminder timer (user-level)
deploy/setup-telegram.py   one-time Telegram bot connection
deploy/remind.py           the reminder itself (reads the DB read-only)
data/                      SQLite database (git-ignored)
```

### API

| Method | Path                      | Body / query            |
|--------|---------------------------|-------------------------|
| GET    | `/api/sessions`           | —                       |
| POST   | `/api/sessions`           | one session (JSON)      |
| POST   | `/api/sessions/import`    | list of sessions; duplicates (same `loggedAt`) are skipped |
| PUT    | `/api/sessions/<id>`      | full session (JSON)     |
| DELETE | `/api/sessions/<id>`      | —                       |
| GET    | `/api/title?url=<link>`   | returns `{"title": …}`  |

A session is `{date, loggedAt, clipTitle, clipUrl, reps, confidence, notes}`, where
`date` is `YYYY-MM-DD` and `confidence` is `1`–`3` or `null`.
