#!/usr/bin/env bash
# Daily Telegram reminder if no session was logged that day (systemd user timer, no sudo).
# Run deploy/setup-telegram.py first to connect your bot.
# Usage: ./deploy/install-reminder.sh [HH:MM]     default 20:00
#        ./deploy/install-reminder.sh --remove
set -euo pipefail

NAME="shadowing-reminder"
UNIT_DIR="$HOME/.config/systemd/user"
APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if [[ "${1:-}" == "--remove" ]]; then
  systemctl --user disable --now "$NAME.timer" 2>/dev/null || true
  rm -f "$UNIT_DIR/$NAME.timer" "$UNIT_DIR/$NAME.service"
  systemctl --user daemon-reload
  echo "Reminder removed."
  exit 0
fi

TIME="${1:-20:00}"
if ! [[ "$TIME" =~ ^([01][0-9]|2[0-3]):[0-5][0-9]$ ]]; then
  echo "Time must be HH:MM (24h), e.g. 20:00" >&2
  exit 1
fi

mkdir -p "$UNIT_DIR"
cat > "$UNIT_DIR/$NAME.service" <<EOF
[Unit]
Description=Shadowing Tracker: remind if no session logged today

[Service]
Type=oneshot
ExecStart=/usr/bin/python3 $APP_DIR/deploy/remind.py
# Retry if the network is down at reminder time.
Restart=on-failure
RestartSec=5min
EOF

cat > "$UNIT_DIR/$NAME.timer" <<EOF
[Unit]
Description=Daily shadowing practice reminder at $TIME

[Timer]
OnCalendar=*-*-* $TIME:00
AccuracySec=1min

[Install]
WantedBy=timers.target
EOF

systemctl --user daemon-reload
systemctl --user enable --now "$NAME.timer"
echo "Reminder set for $TIME daily."
systemctl --user list-timers "$NAME.timer" --no-pager | head -2
