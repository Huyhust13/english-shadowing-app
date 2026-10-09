#!/usr/bin/env bash
# Install or update English Hub as a systemd *user* service (no sudo).
#
#   deploy/install-hub.sh            install/update and (re)start on 127.0.0.1:8090
#   PORT=9000 deploy/install-hub.sh  use another port
#   deploy/install-hub.sh --remove   stop and remove the service (data is kept)
#
# Code runs from this checkout. Data (database, per-user Anki collections, keys)
# lives in ~/.local/share/english-hub/data; the Python venv in ~/.local/share/english-hub/venv;
# settings in ~/.config/english-hub/hub.env (created on first run, mode 0600).
#
# The app only listens on localhost. Publish it with Tailscale Funnel:
#   sudo tailscale funnel --bg 8090
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SHARE="${XDG_DATA_HOME:-$HOME/.local/share}/english-hub"
VENV="$SHARE/venv"
DATA_DIR="$SHARE/data"
PORT="${PORT:-8090}"
CONF_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/english-hub"
ENV_FILE="$CONF_DIR/hub.env"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
UNIT="$UNIT_DIR/english-hub.service"

if [[ "${1:-}" == "--remove" ]]; then
  systemctl --user disable --now english-hub.service 2>/dev/null || true
  rm -f "$UNIT"
  systemctl --user daemon-reload
  echo "Removed english-hub.service (data kept in $DATA_DIR)."
  exit 0
fi

mkdir -p "$DATA_DIR" "$UNIT_DIR" "$CONF_DIR"
chmod 700 "$CONF_DIR" "$SHARE" "$DATA_DIR"

if [[ ! -f "$ENV_FILE" ]]; then
  # PUBLIC_URL: https://<this machine's Tailscale name>, which is what Funnel serves.
  url="${PUBLIC_URL:-}"
  if [[ -z "$url" ]] && command -v tailscale >/dev/null; then
    name="$(tailscale status --self --json 2>/dev/null \
      | python3 -c 'import json,sys; print(json.load(sys.stdin)["Self"]["DNSName"].rstrip("."))' 2>/dev/null || true)"
    if [[ -n "$name" ]]; then url="https://$name"; fi
  fi
  token=""
  old="$HOME/.config/shadowing-tracker/telegram.env"   # reuse the old reminder bot, if any
  if [[ -f "$old" ]]; then token="$(sed -n 's/^TELEGRAM_BOT_TOKEN=//p' "$old")"; fi
  (
    umask 077
    cat > "$ENV_FILE" <<CONF
# English Hub settings (read by the systemd unit). Restart after editing:
#   systemctl --user restart english-hub
PUBLIC_URL=${url:-http://localhost:$PORT}
DATA_DIR=$DATA_DIR
TELEGRAM_BOT_TOKEN=$token
DEFAULT_TIMEZONE=Asia/Ho_Chi_Minh
CONF
  )
  echo "Wrote $ENV_FILE (PUBLIC_URL=${url:-http://localhost:$PORT})."
fi

if [[ ! -x "$VENV/bin/python" ]]; then
  python3 -m venv "$VENV"
fi
"$VENV/bin/pip" install -q --upgrade pip
"$VENV/bin/pip" install -q -r "$APP_DIR/requirements.txt"

sed -e "s|__APP_DIR__|$APP_DIR|g" -e "s|__VENV__|$VENV|g" -e "s|__DATA_DIR__|$DATA_DIR|g" \
    -e "s|__PORT__|$PORT|g" -e "s|__ENV_FILE__|$ENV_FILE|g" \
    "$APP_DIR/deploy/english-hub.service" > "$UNIT"

systemctl --user daemon-reload
systemctl --user enable english-hub.service >/dev/null
systemctl --user restart english-hub.service

if ! loginctl show-user "$USER" -p Linger 2>/dev/null | grep -q yes; then
  echo "Tip: run 'sudo loginctl enable-linger $USER' so it also runs when you're not logged in."
fi

echo "English Hub is running on http://127.0.0.1:$PORT (public: $(sed -n 's/^PUBLIC_URL=//p' "$ENV_FILE"))"
echo "First time? Create your account:  cd $APP_DIR && $VENV/bin/python -m hub create-admin <username> --link"
echo "Logs: journalctl --user -u english-hub -f"
