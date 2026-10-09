<p align="center">
  <img src="icons/apple-touch-icon.png" width="96" height="96" alt="English Hub icon">
</p>

# English Hub

A small, self-hosted web app for **daily English practice with friends**. Each person
has their own private account and keeps three habits going, with one streak:

1. **Vocab** — their own **Anki** collection, synced with their own AnkiWeb account
   (optional).
2. **Sentence practice** — a "done today" tick with a note (AI modes later).
3. **Shadowing** — log the clip, reps, how it felt, and notes/script.

The **Today** page shows what's left today, streaks and the last 14 days. A **daily
reminder** goes out by Telegram and/or phone notification at each person's own
time, only on days they haven't finished.

It runs on a Raspberry Pi at home and is published on the internet over HTTPS with
**Tailscale Funnel**. Accounts are invite-only.

- How it's built and why (design patterns): **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)**
- Versions: `v1.0.0` Shadowing Tracker (single user) · `v2.0.0` English Hub (single
  user, LAN) · `v3.0.0` multi-user, public link.

---

## For friends: getting started

1. Open the **invite link** you were sent and create your account (name, username,
   password). Links work once and expire after 7 days.
2. You land on **Settings**. Pick your reminder time, then either:
   - **Connect Telegram**: tap it, then press **Start** in Telegram. Done.
   - **Notifications on this device**: tap **Turn on** and allow notifications.
     On **iPhone/iPad**, first add the app to your Home Screen (Share → *Add to Home
     Screen*), open it from the new icon, then turn notifications on.
   - Press **Send a test reminder** to check.
3. Optional: on **Vocab**, log in with **your own** AnkiWeb account to study your decks.
   Only a sync key is stored, never your password.
4. Forgot your password? Ask the admin for a reset link.

Your log is private: nobody else, including the admin, can see it. **Settings →
Download my data** gives you everything as JSON.

---

## Run it locally (development)

Needs Python 3.10+.

```sh
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt pytest
.venv/bin/python -m hub create-admin me        # asks for a password
.venv/bin/python -m hub                        # http://localhost:8090
.venv/bin/python -m pytest -q tests            # run the tests
```

Data goes to `./data/` (git-ignored). Settings are environment variables:

| Variable | Default | Purpose |
|---|---|---|
| `DATA_DIR` | `./data` | database, per-user Anki collections, keys |
| `HOST` / `PORT` | `127.0.0.1` / `8090` | where the server listens |
| `PUBLIC_URL` | `http://localhost:8090` | the address people open; used in links and the CSRF check |
| `TELEGRAM_BOT_TOKEN` | – | bot for reminders (from [@BotFather](https://t.me/BotFather)) |
| `DEFAULT_TIMEZONE` | `Asia/Ho_Chi_Minh` | used if the browser's timezone is unknown |
| `ANKI_ENABLED` | `1` | `0` to run without the Vocab part |
| `SECRET_KEY` | generated in `DATA_DIR/secret_key` | signs login cookies |

---

## Deploy on the Pi

The live server is the Pi at `huy@english.nvh` (code in `~/english-hub`).

### Update to a new version

```sh
rsync -av --delete --exclude .git --exclude data/ --exclude __pycache__ --exclude .claude \
  ./ huy@english.nvh:/home/huy/english-hub/
ssh huy@english.nvh 'cd ~/english-hub && ./deploy/install-hub.sh'
```

`install-hub.sh` installs Python packages into `~/.local/share/english-hub/venv`,
writes the systemd *user* unit and restarts it. Database migrations run
automatically at start-up.

### First install on a new machine

```sh
./deploy/install-hub.sh                          # creates ~/.config/english-hub/hub.env
sudo loginctl enable-linger $USER                # keep running without a login session
sudo tailscale funnel --bg 8090                  # publish https://<machine>.<tailnet>.ts.net
.../venv/bin/python -m hub create-admin <you> --link    # prints a link to set your password
```

- Funnel must be allowed for the machine in the Tailscale admin console (the
  `funnel` node attribute, plus HTTPS certificates for the tailnet); the command
  prints a link if it isn't.
- Check `PUBLIC_URL` in `~/.config/english-hub/hub.env` matches the Funnel URL
  (`tailscale funnel status`), then `systemctl --user restart english-hub`.

### Files on the server

| Path | What |
|---|---|
| `~/english-hub/` | code (rsync'd, no .git) |
| `~/.config/english-hub/hub.env` | `PUBLIC_URL`, `DATA_DIR`, `TELEGRAM_BOT_TOKEN` (mode 0600) |
| `~/.local/share/english-hub/data/hub.db` | accounts and everyone's logs |
| `~/.local/share/english-hub/data/users/<id>/anki/` | each person's Anki collection, media, daily backups |
| `~/.local/share/english-hub/data/secret_key`, `vapid_private.pem` | cookie key, Web Push key |
| `sudo journalctl _SYSTEMD_USER_UNIT=english-hub.service -f` | logs (the Pi keeps user logs in the system journal) |

---

## Admin tasks

Everything is on the **Admin** page (Settings → Admin):

- **Invite a friend:** *Create invite link*, send it privately (works once, 7 days).
- **Forgotten password:** *Reset password* gives a one-time link (2 days).
- **Turn off** an account: they're logged out everywhere and can't log in.

From the command line on the Pi (`cd ~/english-hub`, using the venv's python):

```sh
~/.local/share/english-hub/venv/bin/python -m hub invite "Lan"
~/.local/share/english-hub/venv/bin/python -m hub reset-link lan
```

## Back up

```sh
ssh huy@english.nvh "python3 -c \"import sqlite3,os; s=sqlite3.connect(os.path.expanduser('~/.local/share/english-hub/data/hub.db')); d=sqlite3.connect('/tmp/hub-backup.db'); s.backup(d); d.close()\""
rsync -av huy@english.nvh:/tmp/hub-backup.db ./hub-$(date +%F).db
```

Anki collections are also on each person's AnkiWeb account, and the app keeps a daily
Anki backup in each `users/<id>/anki/backups/`.

## Troubleshooting

| Problem | Check |
|---|---|
| Link doesn't open from outside | `tailscale funnel status` on the Pi; `systemctl --user status english-hub` |
| "Please log in again" all the time | `PUBLIC_URL` must be the `https://` address people use (cookies are HTTPS-only) |
| Telegram "Not set up on this server" | `TELEGRAM_BOT_TOKEN` in `hub.env`, then restart; logs show `Telegram bot is @…` |
| No phone notification | iPhone: must be opened from the Home Screen icon. Check the browser allows notifications for the site. Use *Send a test reminder* |
| Reminder at the wrong time | Settings → Timezone |
| Vocab "needs login" | AnkiWeb session expired: log in again on the Vocab page |
| Title doesn't auto-fill | Some sites block scripted requests; links to private addresses are refused on purpose |

## Project structure

```
hub/        back end (Flask): see docs/ARCHITECTURE.md
web/        pages, shared JS/CSS, service worker, manifest
icons/      app icons (make_icons.py draws them, pure Python)
tests/      pytest suite
deploy/     systemd unit + install script
docs/       architecture and design patterns
```
