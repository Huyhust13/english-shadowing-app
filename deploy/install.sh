#!/usr/bin/env bash
# Serve the Shadowing Tracker at http://english.nvh (port 80) as a systemd service.
# Usage: sudo ./deploy/install.sh
set -euo pipefail

HOSTNAME_ALIAS="english.nvh"
SERVICE="shadowing-tracker"
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_USER="${SUDO_USER:-$(stat -c %U "$APP_DIR")}"

if [[ $EUID -ne 0 ]]; then
  echo "Run with sudo: sudo $0" >&2
  exit 1
fi

# 1. Hostname -> this machine
if grep -qE "^[^#]*\s${HOSTNAME_ALIAS//./\\.}(\s|$)" /etc/hosts; then
  echo "/etc/hosts already has ${HOSTNAME_ALIAS}"
else
  cp /etc/hosts "/etc/hosts.bak.$(date +%Y%m%d%H%M%S)"
  printf '127.0.0.1\t%s\n' "$HOSTNAME_ALIAS" >> /etc/hosts
  echo "Added ${HOSTNAME_ALIAS} to /etc/hosts (backup saved next to it)"
fi

# 2. systemd service on port 80
sed -e "s|__USER__|${APP_USER}|g" -e "s|__APP_DIR__|${APP_DIR}|g" \
  "$APP_DIR/deploy/${SERVICE}.service" > "/etc/systemd/system/${SERVICE}.service"
systemctl daemon-reload
systemctl enable --now "$SERVICE"
systemctl restart "$SERVICE"

sleep 1
if curl -fsS -o /dev/null "http://${HOSTNAME_ALIAS}/"; then
  echo "Done: http://${HOSTNAME_ALIAS}/ is up (service: ${SERVICE}, user: ${APP_USER})"
else
  echo "Service installed but http://${HOSTNAME_ALIAS}/ didn't respond. Check: journalctl -u ${SERVICE} -n 50" >&2
  exit 1
fi
