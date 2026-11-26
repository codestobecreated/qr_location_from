#!/usr/bin/env bash
# Start Gunicorn for this site (CloudPanel Python site, run as the site's SSH user),
# or gracefully reload it if it is already running.
#
#   bash deploy/start.sh          # start, or reload if running
#   bash deploy/start.sh ensure   # start only if it is down (use from a CloudPanel cron job after reboots)
#
# Needs APP_PORT = the CloudPanel "App Port" of qr.reluxelectric.com, from the environment or .deploy.env.
set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
cd "$APP_DIR"
if [ "$(id -u)" -eq 0 ]; then
  echo "!! Do not start Gunicorn as root. Run as the site user:  su - $(stat -c %U "$APP_DIR")" >&2
  exit 1
fi
if [ -f .deploy.env ]; then set -a; . ./.deploy.env; set +a; fi

APP_PORT="${APP_PORT:-}"
[ -n "$APP_PORT" ] || { echo "!! APP_PORT is not set. Add APP_PORT=<CloudPanel App Port> to $APP_DIR/.deploy.env" >&2; exit 1; }
GUNICORN_WORKERS="${GUNICORN_WORKERS:-3}"
if [ -z "${VENV_DIR:-}" ]; then
  for c in "$APP_DIR/.venv" "$APP_DIR/venv" "$APP_DIR/env"; do [ -x "$c/bin/gunicorn" ] && VENV_DIR="$c" && break; done
fi
[ -x "${VENV_DIR:-}/bin/gunicorn" ] || { echo "!! gunicorn not found in the virtual environment (${VENV_DIR:-none})." >&2; exit 1; }

PID_FILE="$APP_DIR/gunicorn.pid"
mkdir -p "$APP_DIR/logs"

RUNNING=0
if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then RUNNING=1; fi

if [ "${1:-}" = "ensure" ]; then
  # Already running (maybe started by another user) -> nothing to do.
  if [ "$RUNNING" = 1 ] || (exec 3<>"/dev/tcp/127.0.0.1/$APP_PORT") 2>/dev/null; then exit 0; fi
fi

if [ "$RUNNING" = 1 ]; then
  echo "Reloading Gunicorn (pid $(cat "$PID_FILE"))"
  kill -HUP "$(cat "$PID_FILE")"
else
  if (exec 3<>"/dev/tcp/127.0.0.1/$APP_PORT") 2>/dev/null; then
    echo "!! Port $APP_PORT is already in use by another process – not starting a second server." >&2
    exit 1
  fi
  echo "Starting Gunicorn on 127.0.0.1:$APP_PORT"
  "$VENV_DIR/bin/gunicorn" config.wsgi:application \
    --chdir "$APP_DIR" \
    --bind "127.0.0.1:$APP_PORT" \
    --workers "$GUNICORN_WORKERS" \
    --timeout 120 \
    --pid "$PID_FILE" \
    --access-logfile "$APP_DIR/logs/access.log" \
    --error-logfile "$APP_DIR/logs/error.log" \
    --daemon 9>&- 8>&-
fi
