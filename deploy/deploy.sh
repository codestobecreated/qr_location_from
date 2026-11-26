#!/usr/bin/env bash
# =============================================================================
# RELUX ELECTRIC – QR Lead Management: production deploy script
#
# Run on the server (GitHub Actions does this over SSH on every push to main):
#
#   bash deploy/deploy.sh --check   # READ-ONLY: detect venv / Gunicorn, show the plan, change nothing
#   bash deploy/deploy.sh           # deploy: pull, pip install, migrate, collectstatic, reload Gunicorn
#
# Never touches: .env, the database (backed up before migrate), media/, other CloudPanel sites, SSH keys.
# Git is only fast-forwarded (no reset --hard, no clean). The database is backed up before migrate.
#
# Optional server-only overrides (never committed) in  <app>/.deploy.env :
#   VENV_DIR=/home/reluxelectric-qr/htdocs/qr.reluxelectric.com/.venv
#   GUNICORN_SERVICE=relux-qr.service     # systemd unit to restart (needs passwordless sudo for it)
#   APP_PORT=8130                         # CloudPanel "App Port" – only used to START Gunicorn if it is not running
#   GUNICORN_WORKERS=3
#   SKIP_DB_BACKUP=1                      # only if mysqldump is unavailable (not recommended)
# =============================================================================
set -Eeuo pipefail

# Run from a private copy: the git update below may rewrite this very file while bash is still reading it.
if [ -z "${RELUX_DEPLOY_COPY:-}" ]; then
  COPY="$(mktemp)"
  cp "$0" "$COPY"
  SELF_DIR="$(cd "$(dirname "$0")/.." && pwd)"
  RELUX_DEPLOY_COPY=1 bash "$COPY" "$SELF_DIR" "$@"   # an explicit folder given by the caller wins (last one)
  rc=$?
  rm -f "$COPY"
  exit $rc
fi

MODE="deploy"
APP_DIR_ARG=""
for arg in "$@"; do
  case "$arg" in
    --check) MODE="check" ;;
    -h|--help) sed -n '2,22p' "$0"; exit 0 ;;
    *) APP_DIR_ARG="$arg" ;;
  esac
done

EXPECTED_REPO="codestobecreated/qr_location_from"
BRANCH="main"
WSGI_APP="config.wsgi:application"

log()  { printf '==> %s\n' "$*"; }
warn() { printf '!!  %s\n' "$*" >&2; }
die()  { printf '\n!!  DEPLOY FAILED: %s\n' "$*" >&2; exit 1; }
trap 'warn "Command failed on line $LINENO: $BASH_COMMAND"' ERR

# --- Locate the project --------------------------------------------------------
if [ -n "$APP_DIR_ARG" ]; then
  APP_DIR="$APP_DIR_ARG"
else
  APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
fi
[ -d "$APP_DIR" ] || die "Project directory $APP_DIR does not exist."
cd "$APP_DIR"
APP_DIR="$(pwd -P)"
log "Mode: $MODE | Project: $APP_DIR | User: $(id -un)"

# Never as root: files would become root-owned and the site user / Gunicorn could no longer update them.
if [ "$(id -u)" -eq 0 ]; then
  OWNER="$(stat -c %U "$APP_DIR" 2>/dev/null || echo '<site user>')"
  die "Do not run as root. Switch to the site user first:  su - $OWNER   (or use that user as SSH_USER in GitHub)."
fi

[ -f manage.py ] && [ -f config/settings.py ] || die "$APP_DIR is not this Django project (manage.py/config missing)."
[ -d .git ] || die "$APP_DIR is not a git clone. Clone the repo there first (see README → Deployment)."

# Server-only overrides
if [ -f .deploy.env ]; then
  # shellcheck disable=SC1091
  set -a; . ./.deploy.env; set +a
  log "Loaded overrides from .deploy.env"
fi
VENV_DIR="${VENV_DIR:-}"
GUNICORN_SERVICE="${GUNICORN_SERVICE:-}"
APP_PORT="${APP_PORT:-}"
GUNICORN_WORKERS="${GUNICORN_WORKERS:-3}"

# One deploy at a time
if command -v flock >/dev/null 2>&1 && [ "$MODE" = "deploy" ]; then
  exec 9>"$APP_DIR/.deploy.lock"
  flock -n 9 || die "Another deploy is already running."
fi

# --- Safety checks on protected files ------------------------------------------
[ -f .env ] || die ".env is missing in $APP_DIR. Create it from .env.example (it is never created or changed by this script)."
if ! grep -qE '^DB_ENGINE=sqlite' .env && ! grep -qE '^DB_PASSWORD=.+' .env; then
  die "DB_PASSWORD is not set in $APP_DIR/.env (the MySQL password lives only there, never in settings.py)."
fi
for protected in .env db.sqlite3 media; do
  if git ls-files --error-unmatch "$protected" >/dev/null 2>&1; then
    die "$protected is tracked by git – refusing to deploy (it could be overwritten)."
  fi
done

# --- Git: verify remote, refuse to overwrite local edits -----------------------
REAL_DIR="$APP_DIR"
git config --global --get-all safe.directory 2>/dev/null | grep -qxF "$REAL_DIR" \
  || git config --global --add safe.directory "$REAL_DIR"

REMOTE_URL="$(git remote get-url origin 2>/dev/null || true)"
case "$REMOTE_URL" in
  *"$EXPECTED_REPO"*) ;;
  *) die "git remote 'origin' is '$REMOTE_URL', expected $EXPECTED_REPO." ;;
esac

if [ -n "$(git status --porcelain --untracked-files=no)" ]; then
  git status --short --untracked-files=no >&2
  die "Tracked files were edited on the server. Commit them to GitHub or discard them manually, then redeploy."
fi

log "Fetching origin/$BRANCH"
git fetch --quiet origin "$BRANCH"
LOCAL="$(git rev-parse HEAD)"
REMOTE="$(git rev-parse "origin/$BRANCH")"
if ! git merge-base --is-ancestor "$LOCAL" "$REMOTE"; then
  die "Server branch has commits that are not on origin/$BRANCH (history diverged). Fix manually – no destructive reset is done."
fi
log "Server at $(git rev-parse --short "$LOCAL"), GitHub at $(git rev-parse --short "$REMOTE") ($(git rev-list --count "$LOCAL..$REMOTE") new commit(s))"

# --- Find the existing virtual environment -------------------------------------
if [ -z "$VENV_DIR" ]; then
  for candidate in "$APP_DIR/.venv" "$APP_DIR/venv" "$APP_DIR/env" "$(dirname "$APP_DIR")/.venv" "$(dirname "$APP_DIR")/venv"; do
    if [ -x "$candidate/bin/python" ]; then VENV_DIR="$candidate"; break; fi
  done
fi
[ -n "$VENV_DIR" ] && [ -x "$VENV_DIR/bin/python" ] \
  || die "No Python virtual environment found (looked for .venv, venv, env). Create one once:  python3 -m venv $APP_DIR/.venv   or set VENV_DIR in .deploy.env"
PY="$VENV_DIR/bin/python"
log "Virtual environment: $VENV_DIR ($("$PY" --version 2>&1))"

# --- Find how Gunicorn runs for THIS project -----------------------------------
PID_FILE="$APP_DIR/gunicorn.pid"
RESTART_METHOD=""
RESTART_TARGET=""

find_systemd_unit() {
  # Units whose definition mentions this project directory and gunicorn.
  local matches=() f
  for f in /etc/systemd/system/*.service /lib/systemd/system/*.service; do
    [ -r "$f" ] || continue
    if grep -qF "$APP_DIR" "$f" && grep -qi gunicorn "$f"; then matches+=("$(basename "$f")"); fi
  done
  if [ "${#matches[@]}" -gt 1 ]; then
    die "Several systemd units reference $APP_DIR: ${matches[*]}. Set GUNICORN_SERVICE in .deploy.env."
  fi
  [ "${#matches[@]}" -eq 1 ] && printf '%s' "${matches[0]}"
  return 0
}

find_gunicorn_master() {
  # A gunicorn master process of the current user, running from this directory with this WSGI app.
  local pid cwd ppid_cmd
  for pid in $(pgrep -u "$(id -u)" -f "gunicorn.*$WSGI_APP" 2>/dev/null || true); do
    cwd="$(readlink "/proc/$pid/cwd" 2>/dev/null || true)"
    [ "$cwd" = "$APP_DIR" ] || continue
    ppid_cmd="$(ps -o args= -p "$(ps -o ppid= -p "$pid" | tr -d ' ')" 2>/dev/null || true)"
    case "$ppid_cmd" in *gunicorn*) continue ;; esac   # skip workers, keep the master
    printf '%s' "$pid"; return 0
  done
  return 0
}

if [ -n "$GUNICORN_SERVICE" ]; then
  RESTART_METHOD="systemd"; RESTART_TARGET="$GUNICORN_SERVICE"
else
  UNIT="$(find_systemd_unit)"
  if [ -n "$UNIT" ]; then
    RESTART_METHOD="systemd"; RESTART_TARGET="$UNIT"
  elif [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    RESTART_METHOD="hup"; RESTART_TARGET="$(cat "$PID_FILE")"
  else
    MASTER="$(find_gunicorn_master)"
    if [ -n "$MASTER" ]; then
      RESTART_METHOD="hup"; RESTART_TARGET="$MASTER"
    elif [ -n "$APP_PORT" ]; then
      RESTART_METHOD="start"; RESTART_TARGET="127.0.0.1:$APP_PORT"
    fi
  fi
fi

case "$RESTART_METHOD" in
  systemd) log "Gunicorn: systemd unit '$RESTART_TARGET' (will run: sudo -n systemctl restart $RESTART_TARGET)" ;;
  hup)     log "Gunicorn: running master pid $RESTART_TARGET (will send HUP = graceful reload)" ;;
  start)   log "Gunicorn: not running; will start it on $RESTART_TARGET via deploy/start.sh" ;;
  *)       RESTART_METHOD="none"
           warn "Gunicorn for this project was NOT found (no systemd unit, no gunicorn.pid, no matching process)."
           warn "Set APP_PORT (CloudPanel App Port) or GUNICORN_SERVICE in $APP_DIR/.deploy.env." ;;
esac

if [ "$RESTART_METHOD" = "systemd" ]; then
  sudo -n -l systemctl >/dev/null 2>&1 \
    || warn "User $(id -un) has no passwordless sudo for systemctl – the restart step would fail. Ask the server admin, or run Gunicorn under this user (APP_PORT) instead."
fi

# Prints "engine|name|host|port" from Django settings (never the password).
db_info() {
  "$PY" - <<'PYEOF' 2>/dev/null || true
import os, sys
sys.path.insert(0, os.getcwd())
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
try:
    from django.conf import settings
    d = settings.DATABASES["default"]
    print("|".join([d["ENGINE"].rsplit(".", 1)[-1], str(d["NAME"]), str(d.get("HOST") or ""), str(d.get("PORT") or "")]))
except Exception:
    pass
PYEOF
}
DB_INFO="$(db_info)"
log "Database: ${DB_INFO:-<not readable yet – requirements may need installing; checked again during deploy>}"

if [ "$MODE" = "check" ]; then
  echo
  log "CHECK ONLY – nothing was changed. A real deploy would:"
  echo "    1. git merge --ff-only origin/$BRANCH"
  echo "    2. $VENV_DIR/bin/pip install -r requirements.txt"
  echo "    3. python manage.py check --deploy"
  echo "    4. back up the database (${DB_INFO:-see above}) to $APP_DIR/backups/"
  echo "    5. python manage.py migrate --noinput"
  echo "    6. python manage.py collectstatic --noinput"
  echo "    7. restart Gunicorn: $RESTART_METHOD ${RESTART_TARGET}"
  [ "$RESTART_METHOD" = "none" ] && exit 1
  exit 0
fi

[ "$RESTART_METHOD" = "none" ] && die "Cannot identify the Gunicorn process for this site (see messages above)."

# =============================================================================
# DEPLOY
# =============================================================================
log "Updating code (fast-forward only)"
git merge --ff-only --quiet "origin/$BRANCH"

log "Installing Python dependencies"
"$PY" -m pip install --quiet --disable-pip-version-check -r requirements.txt

log "Django system checks"
"$PY" manage.py check --deploy --fail-level ERROR

# --- Back up the database before migrating ------------------------------------
DB_INFO="$(db_info)"
[ -n "$DB_INFO" ] || die "Could not read DATABASES from Django settings (check .env)."
IFS='|' read -r DB_ENGINE DB_NAME DB_HOST DB_PORT <<< "$DB_INFO"
mkdir -p "$APP_DIR/backups"
chmod 700 "$APP_DIR/backups"
STAMP="$(date +%Y%m%d-%H%M%S)-$(git rev-parse --short "$LOCAL")"

if [ "${SKIP_DB_BACKUP:-0}" = "1" ]; then
  warn "SKIP_DB_BACKUP=1 – database backup skipped."
elif [ "$DB_ENGINE" = "mysql" ]; then
  command -v mysqldump >/dev/null 2>&1 || die "mysqldump not found – refusing to migrate without a backup (set SKIP_DB_BACKUP=1 in .deploy.env to override)."
  BACKUP="$APP_DIR/backups/db-$STAMP.sql.gz"
  CNF="$(mktemp)"; chmod 600 "$CNF"
  # Password goes into a private temp file, never onto the command line or into the log.
  "$PY" - "$CNF" <<'PYEOF'
import os, sys
sys.path.insert(0, os.getcwd())
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
from django.conf import settings
d = settings.DATABASES["default"]
with open(sys.argv[1], "w") as fh:
    password = d["PASSWORD"].replace("\\", "\\\\").replace('"', '\\"')
    fh.write("[client]\n")
    fh.write("user=%s\n" % d["USER"])
    fh.write('password="%s"\n' % password)
    fh.write("host=%s\n" % (d.get("HOST") or "127.0.0.1"))
    fh.write("port=%s\n" % (d.get("PORT") or "3306"))
PYEOF
  log "Backing up MySQL database $DB_NAME to $BACKUP"
  if ! mysqldump --defaults-extra-file="$CNF" --single-transaction --no-tablespaces --routines "$DB_NAME" | gzip > "$BACKUP"; then
    rm -f "$CNF" "$BACKUP"
    die "MySQL backup failed – migrations were NOT run."
  fi
  rm -f "$CNF"
  chmod 600 "$BACKUP"
elif [ "$DB_ENGINE" = "sqlite3" ] && [ -f "$DB_NAME" ]; then
  BACKUP="$APP_DIR/backups/db-$STAMP.sqlite3"
  log "Backing up SQLite database to $BACKUP"
  "$PY" - "$DB_NAME" "$BACKUP" <<'PYEOF'
import sqlite3, sys
src = sqlite3.connect(sys.argv[1]); dst = sqlite3.connect(sys.argv[2])
with dst:
    src.backup(dst)
dst.close(); src.close()
PYEOF
fi
# Keep the 15 most recent backups
ls -1t "$APP_DIR"/backups/db-* 2>/dev/null | tail -n +16 | while read -r old; do rm -f -- "$old"; done

log "Applying migrations"
"$PY" manage.py migrate --noinput

log "Collecting static files"
"$PY" manage.py collectstatic --noinput -v 0

log "Restarting Gunicorn ($RESTART_METHOD)"
case "$RESTART_METHOD" in
  systemd) sudo -n systemctl restart "$RESTART_TARGET"
           sudo -n systemctl is-active --quiet "$RESTART_TARGET" || die "systemd unit $RESTART_TARGET is not active after restart." ;;
  hup)     kill -HUP "$RESTART_TARGET" ;;
  # 9>&- : Gunicorn must not inherit the deploy lock, or every later deploy would think one is still running.
  start)   APP_PORT="$APP_PORT" GUNICORN_WORKERS="$GUNICORN_WORKERS" VENV_DIR="$VENV_DIR" bash "$APP_DIR/deploy/start.sh" 9>&- ;;
esac

# --- Health check (only when we know the local port) ---------------------------
if [ -n "$APP_PORT" ] && command -v curl >/dev/null 2>&1; then
  HOST_HEADER="$(grep -E '^DJANGO_ALLOWED_HOSTS=' .env | head -1 | cut -d= -f2 | cut -d, -f1 | tr -d ' "')"
  for i in $(seq 1 15); do
    CODE="$(curl -s -o /dev/null -w '%{http_code}' -H "Host: ${HOST_HEADER:-localhost}" -H 'X-Forwarded-Proto: https' \
            "http://127.0.0.1:$APP_PORT/accounts/login/" || true)"
    [ "$CODE" = "200" ] && break
    sleep 2
  done
  [ "$CODE" = "200" ] || die "Health check failed: /accounts/login/ returned HTTP $CODE on port $APP_PORT. See logs/error.log."
  log "Health check OK (HTTP 200)"
fi

log "Deployed $(git rev-parse --short HEAD) successfully"
