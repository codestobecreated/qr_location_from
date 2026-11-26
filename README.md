# RELUX ELECTRIC – QR-Based Lead Management System

A single Django project (templates + Tailwind CSS + vanilla JavaScript) for RELUX ELECTRIC enquiries.

**There is exactly one QR code.** It points to **`<your site>/qr`** (e.g. `https://qr.reluxelectric.com/qr`).
A customer scans it → the enquiry form opens → the submitted lead is stored → the dashboard shows
**leads per day, week, month and year**. The QR and its URL are created once and never change –
no matter what is updated, deployed or renamed. No location, station or address data exists anywhere.

No React / Node / DRF / PostgreSQL – everything runs inside one Django project.

---

## 1. Features

| Area | What it does |
| --- | --- |
| Authentication | Django auth login/logout, password validators, session expiry, login lockout after 5 failures, audit log of logins |
| Roles | **Super Admin** (everything), **Manager** (all leads and analytics, assigns leads), **Staff** (only leads assigned to them) |
| QR Code | Menu **QR Code** shows the one QR: image, its fixed link `/qr`, PNG / print PDF (1 or 4 per A4), scans, leads, and a pause/switch-on button. There is no create, import, rename or regenerate |
| Permanent QR URL | The QR is created automatically on first use with URL `QR_BASE_URL + "/qr"`, stored in the database (`QRCodeMapping.qr_url`, `is_main=True`) and never recalculated. Token/URL cannot be edited or deleted. The `/qr` route is pinned by tests |
| Customer enquiry | `/qr` – no login. Shows **only the RELUX logo and the enquiry form** (name, mobile, email, category, message, privacy consent). CSRF, validation, honeypot, per-IP rate limit, double-submit protection, duplicate flagging, thank-you page `/qr/thank-you/` with reference ID |
| Scan tracking | Every visit recorded with device/OS/browser, UTM parameters, bot detection, repeat-open detection, form-visit beacon, submission flag. Funnel: **Scan → Form visit → Submission → Lead → Conversion** |
| Lead management | Searchable, filterable (category, status, assignee, date range, duplicates), sortable, paginated. Status history, follow-up notes, assignment, bulk actions, Excel/CSV export |
| Dashboard & analytics | Leads **today / this week / this month / this year / all time**, charts and tables per **day (30 days), month (12 months) and year**, enquiry types, scan → form → lead funnel, devices |
| Reports | Full workbook, daily/weekly/monthly/yearly, category-wise, lead list, raw scan log – Excel or CSV |
| Settings | Profile & password for everyone; Super Admin edits company info, enquiry texts, privacy policy, duplicate window and rate limit; audit log viewer |

All numbers come from live database queries – there are no hard-coded statistics.

---

## 2. Project structure

```
relux_lead_management/
├── config/                  settings.py, urls.py, wsgi.py, asgi.py
├── apps/
│   ├── core/                shared models (SystemSetting), exports, UA parsing, template tags, seed command
│   ├── accounts/            User (role), AuditLog, login, users, settings, permissions/scoping
│   ├── locations/           (removed feature – kept only for its delete migration)
│   ├── stations/            the named-QR model (historical app name), QR auto-creation signal
│   ├── qrcodes/             QRCodeMapping, QRTokenHistory, QRScanEvent, PNG/PDF/ZIP generation
│   ├── leads/               Lead, LeadStatusHistory, LeadNote, LeadAssignment, public QR views
│   ├── dashboard/           overview dashboard
│   ├── analytics/           metrics engine + analytics pages
│   └── reports/             report exports
├── templates/               base.html + one folder per module, customer/ for public pages
├── static/                  css/, js/ (app.js, charts.js, tailwind.config.js), images/
├── tailwind/input.css       source for the optional compiled Tailwind stylesheet
├── media/qrcodes/           generated QR card PNGs (served only through logged-in views)
├── tests/                   automated tests (22)
├── manage.py, requirements.txt, .env.example
```

### Data model

```
QR name (stations.ChargingStation) 1 ── 1 QRCodeMapping (token + permanent qr_url)
                     │                    │
                     ├──< QRScanEvent >───┘
                     └──< Lead >── LeadStatusHistory, LeadNote, LeadAssignment
User (role, assigned QR codes) ;  AuditLog ;  SystemSetting (singleton)
```

* `Lead.station` and `Lead.qr_mapping` use `PROTECT` and are also snapshotted
  (`station_code`, `station_name`, `qr_token`). `Lead.save()` refuses to change them.
* QR codes use `PROTECT` and cannot be deleted – deactivate instead; the URL stays the same.

---

## 3. Local installation (Windows / macOS / Linux)

Requires **Python 3.10+** (tested on 3.12).

```powershell
cd relux_lead_management
py -3.12 -m venv .venv                      # macOS/Linux: python3 -m venv .venv
.venv\Scripts\activate                      # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env                      # macOS/Linux: cp .env.example .env
```

Edit `.env` for local development:

```
DJANGO_SECRET_KEY=any-long-random-string
DJANGO_DEBUG=True
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1
QR_BASE_URL=http://127.0.0.1:8000
```

```powershell
python manage.py migrate
python manage.py createsuperuser
python manage.py runserver
```

Open http://127.0.0.1:8000/ and sign in.

**Optional sample data (development only – refuses to run with DEBUG off):**

```powershell
python manage.py seed_demo_data --stations 60 --leads 400      # 60 sample QR codes
```

**Run the tests:**

```powershell
python manage.py test tests
```

### Testing QR scans from a phone on your network

Phones cannot open `127.0.0.1`. Run `python manage.py runserver 0.0.0.0:8000`, add your PC's LAN IP
to `DJANGO_ALLOWED_HOSTS`, set `QR_BASE_URL=http://<LAN-IP>:8000` and restart. QR images are
re-rendered automatically with the new base URL the next time they are previewed or downloaded
(or all at once with **QR Code Management → Refresh out-of-date QR images**). Tokens do not change.

---

## 4. How the QR flow works

1. Creating a QR (QR Codes → + Create QR, import or admin) creates its `QRCodeMapping` with a new
   cryptographically secure token that has never been used before.
2. The printed code encodes `QR_BASE_URL/q/<token>/`.
3. On scan, `apps/leads/public_views.py` looks the token up in the database – nothing else from the
   request is used to pick the QR.
   * unknown token → "QR not recognised" (404)
   * retired token → "QR replaced" (410), no redirect
   * QR inactive → "not accepting enquiries", no redirect, no lead saved
   * otherwise the enquiry form is shown and a `QRScanEvent` is recorded
4. When the page renders in a real browser, a small beacon marks the scan as a *form visit*.
5. On submit the lead is saved with the QR/token from the database, plus device,
   browser and UTM data; the scan is marked *submitted*; the customer sees a thank-you page.

**Choose the production `QR_BASE_URL` before printing stickers.** Tokens never change, but the
domain is part of the printed code. If the domain must change later, keep the old domain
redirecting `/q/*` to the new one.

---

## 5. Excel / CSV import formats

Download the template from **QR Codes → Import Excel/CSV**.

*QR codes:* `QR ID (optional, only to rename)`, `QR Name*`. Each new row gets its own permanent QR code; images are rendered on first preview/download.


---

## 6. Production deployment (Ubuntu + Gunicorn + Nginx)

> **Domain note:** `leads.reluxelectric.com` already serves the existing RELUX *Business Enquiry*
> Django form on the CloudPanel server. Deploy this system on its own sub-domain
> (e.g. `qr.reluxelectric.com`) unless you intend to replace that site.

### 6.1 Server setup (as the site user, never as root)

```bash
cd /home/<site-user>/htdocs/<domain>
git clone <repo-url> .            # or upload the project folder
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env              # then edit: SECRET_KEY, DEBUG=False, hosts, QR_BASE_URL
python manage.py migrate
python manage.py collectstatic --noinput
python manage.py createsuperuser
mkdir -p media/qrcodes
```

Keep `db.sqlite3` and `media/` outside any directory that `git reset --hard` touches, or point
`SQLITE_PATH` at a data folder, e.g. `SQLITE_PATH=/home/<site-user>/data/relux_qr.sqlite3`.

### 6.2 Gunicorn (systemd)

`/etc/systemd/system/relux-qr.service`

```ini
[Unit]
Description=RELUX QR Lead Management
After=network.target

[Service]
User=<site-user>
Group=<site-user>
WorkingDirectory=/home/<site-user>/htdocs/<domain>
EnvironmentFile=/home/<site-user>/htdocs/<domain>/.env
ExecStart=/home/<site-user>/htdocs/<domain>/.venv/bin/gunicorn config.wsgi:application \
          --bind 127.0.0.1:8130 --workers 3 --timeout 120
Restart=always

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload && sudo systemctl enable --now relux-qr
```

(`--timeout 120` leaves room for large bulk ZIP/PDF downloads. SQLite is in WAL mode, which is
fine for this workload; keep workers ≤ 4.)

### 6.3 Nginx

```nginx
server {
    server_name qr.reluxelectric.com;
    client_max_body_size 12M;           # Excel imports

    location / {
        proxy_pass http://127.0.0.1:8130;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
    # Static files are served by WhiteNoise through the app, so no /static/ alias is required.
    # /media/ is intentionally NOT exposed – QR images are served only to logged-in users.
}
```

Enable HTTPS (CloudPanel "Let's Encrypt" or `certbot --nginx`). The app enables secure cookies,
HSTS and HTTPS redirect automatically when `DJANGO_DEBUG=False`.

On **CloudPanel**, create a *Python* site with an App Port (e.g. 8130), use the Gunicorn command
above, and add the same `X-Forwarded-Proto` header so Django knows the request is HTTPS.

### 6.4 Updating

```bash
source .venv/bin/activate
git pull
pip install -r requirements.txt
python manage.py migrate
python manage.py collectstatic --noinput
sudo systemctl restart relux-qr
```

### 6.5 Backups

SQLite is a single file. Back it up safely while the app runs:

```bash
sqlite3 /path/to/db.sqlite3 ".backup '/backups/relux_qr_$(date +%F).sqlite3'"
```

Also back up `media/qrcodes/` (images can be re-rendered; tokens and QR URLs live in the DB).

### 6.6 Tailwind CSS in production (optional, no Node.js)

Templates use the Tailwind CDN runtime by default. For a faster, offline-capable stylesheet,
download the Tailwind **v3 standalone CLI** binary for your OS from the Tailwind GitHub releases and run,
from the project root:

```bash
./tailwindcss -c static/js/tailwind.config.js -i tailwind/input.css -o static/css/tailwind.build.css --minify
python manage.py collectstatic --noinput
```

When `static/css/tailwind.build.css` exists, every page uses it automatically.

---

## 7. Security summary

* The QR is identified only from the stored token; customer-submitted IDs are ignored.
* Tokens: 128-bit random, globally unique across current and retired tokens, immutable, not deletable.
* Deactivation never redirects a QR code, and QR codes can never be regenerated or re-assigned.
* Lead source fields are immutable at the model level.
* CSRF on every form; login lockout; per-IP enquiry rate limit; honeypot; bot filtering in analytics.
* Role-based data scoping on every list, detail, export and analytics query.
* CSV/Excel exports neutralise spreadsheet formula injection.
* `next=` redirects are validated; secure cookie/HSTS/SSL settings when DEBUG is off.

---

## 8. CI/CD – automatic deploy from GitHub (qr.reluxelectric.com)

Files:

| File | Purpose |
| --- | --- |
| `.github/workflows/deploy.yml` | On every push to `main`: runs Django checks + tests on GitHub, then (if enabled) SSHes into the VPS with `appleboy/ssh-action` and runs the deploy script. Also has a manual **Run workflow** button with a *dry run* option. |
| `deploy/deploy.sh` | Runs **on the server**. Verifies the repo, refuses if tracked files were edited on the server, fast-forwards to `origin/main`, finds the existing virtualenv, installs requirements, runs `check --deploy`, **backs up the SQLite DB**, `migrate --noinput`, `collectstatic --noinput`, reloads Gunicorn, health-checks. `--check` = read-only. |
| `deploy/start.sh` | Starts Gunicorn on the CloudPanel App Port (or reloads it). `start.sh ensure` is for a CloudPanel cron job so the site comes back after a reboot. |
| `.deploy.env` (server only, git-ignored) | Optional overrides: `VENV_DIR`, `GUNICORN_SERVICE`, `APP_PORT`, `GUNICORN_WORKERS`. |

GitHub secrets used (Settings → Secrets and variables → Actions): `SSH_HOST`, `SSH_PORT`, `SSH_USER`, `SSH_PRIVATE_KEY`.
Server path: `/home/reluxelectric-qr/htdocs/qr.reluxelectric.com`.

Never touched by a deploy: `.env`, `db.sqlite3` (backed up to `backups/` before each migrate, last 15 kept), `media/`,
other CloudPanel sites, SSH keys, CloudPanel/nginx config. Git is only fast-forwarded – no `reset --hard`, no `clean`.

### How Gunicorn is identified (nothing is assumed)

`deploy.sh` uses, in this order: `GUNICORN_SERVICE` from `.deploy.env` → a systemd unit whose file mentions this
project directory and gunicorn (restarted with `sudo -n systemctl restart`, needs passwordless sudo for that user) →
`gunicorn.pid` in the project → a running gunicorn master of the SSH user started from this directory (`kill -HUP`,
graceful) → if none is running and `APP_PORT` is set, it starts Gunicorn with `deploy/start.sh`. If none of these
match, the deploy stops with a message instead of guessing.

### First-time setup on the server (once, as the site's SSH user – not root)

```bash
cd /home/reluxelectric-qr/htdocs/qr.reluxelectric.com
git clone https://github.com/codestobecreated/qr_location_from.git .   # folder must be empty; private repo → use a deploy key
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env && nano .env          # SECRET_KEY, DEBUG=False, hosts, QR_BASE_URL=https://qr.reluxelectric.com
echo "APP_PORT=<CloudPanel App Port>" > .deploy.env
bash deploy/deploy.sh --check              # read-only: shows venv, DB path and Gunicorn method
```

CloudPanel → Cron Jobs: `*/5 * * * *  bash /home/reluxelectric-qr/htdocs/qr.reluxelectric.com/deploy/start.sh ensure`

### Testing the deployment

1. **Dry run from GitHub** – Actions → *Test & Deploy* → **Run workflow** → keep *Dry run* ticked → Run.
   The deploy job prints what it detected and changes nothing.
2. **First real deploy** – Run workflow again with *Dry run* unticked.
3. **Turn on automatic deploys** – Settings → Secrets and variables → Actions → **Variables** →
   New repository variable `AUTO_DEPLOY` = `true`. From then on every `git push origin main` deploys.

### Logs

* GitHub: repo → **Actions** → *Test & Deploy* → click a run → open the **Deploy to qr.reluxelectric.com** job →
  expand *Deploy over SSH* (every `==>` line from `deploy.sh`) and *Public smoke test*.
* Server: `logs/error.log`, `logs/access.log` (when started by `start.sh`), DB backups in `backups/`.
