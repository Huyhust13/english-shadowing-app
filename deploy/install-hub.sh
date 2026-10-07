#!/usr/bin/env bash
# Install English Hub as a systemd *user* service (no sudo).
#
#   deploy/install-hub.sh            install/update and (re)start, port 8090
#   PORT=9000 deploy/install-hub.sh  use another port
#   SHADOWING_DB=~/shadowing-app/data/shadowing.db deploy/install-hub.sh
#                                    share the shadowing log with an existing Shadowing Tracker
#   deploy/install-hub.sh --remove   stop and remove the service (data is kept)
#
# Code runs from this checkout; data lives in ~/.local/share/english-hub/data, and the
# Python venv with the `anki` package in ~/.local/share/english-hub/venv.
# Afterwards: log in to AnkiWeb on the Vocab page (or run anki_service.py login).
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
SHARE="${XDG_DATA_HOME:-$HOME/.local/share}/english-hub"
VENV="$SHARE/venv"
DATA_DIR="$SHARE/data"
PORT="${PORT:-8090}"
SHADOWING_DB="${SHADOWING_DB:-$DATA_DIR/shadowing.db}"
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
UNIT="$UNIT_DIR/english-hub.service"

if [[ "${1:-}" == "--remove" ]]; then
  systemctl --user disable --now english-hub.service 2>/dev/null || true
  rm -f "$UNIT"
  systemctl --user daemon-reload
  echo "Removed english-hub.service (data kept in $DATA_DIR)."
  exit 0
fi

mkdir -p "$DATA_DIR" "$UNIT_DIR"
if [[ ! -x "$VENV/bin/python" ]]; then
  python3 -m venv "$VENV"
fi
"$VENV/bin/pip" install -q --upgrade pip
"$VENV/bin/pip" install -q -r "$APP_DIR/requirements.txt"

sed -e "s|__APP_DIR__|$APP_DIR|g" -e "s|__VENV__|$VENV|g" \
    -e "s|__DATA_DIR__|$DATA_DIR|g" -e "s|__PORT__|$PORT|g" -e "s|__SHADOWING_DB__|$SHADOWING_DB|g" \
    "$APP_DIR/deploy/english-hub.service" > "$UNIT"

systemctl --user daemon-reload
systemctl --user enable english-hub.service >/dev/null
systemctl --user restart english-hub.service

# Keep running after logout / across reboots without a login session.
if ! loginctl show-user "$USER" -p Linger 2>/dev/null | grep -q yes; then
  echo "Tip: run 'sudo loginctl enable-linger $USER' so it also runs when you're not logged in."
fi

echo "English Hub is running on http://$(hostname -I | awk '{print $1}'):$PORT"
echo "Logs: journalctl --user -u english-hub -f"
