# RELUX ELECTRIC – QR-Based Lead Management System

A single Django project (templates + Tailwind CSS + vanilla JavaScript, SQLite) that gives every
RELUX ELECTRIC charging station its own **permanent, unique QR code**. Customers scan it with Google
Lens or any phone camera, the station-specific enquiry form opens, and the lead lands in an admin
dashboard with location-wise and station-wise tracking.

No React / Node / DRF / PostgreSQL – everything runs inside one Django project.

---

## 1. Features

| Area | What it does |
| --- | --- |
| Authentication | Django auth login/logout, password validators, session expiry, login lockout after 5 failures, audit log of logins |
| Roles | **Super Admin** (everything), **Manager** (assigned locations: leads, analytics, read-only stations/QR), **Staff** (only leads assigned to them). Synced to Django Groups *Super Admin / Manager / Staff* |
| Locations | Add / edit / view / delete (blocked when stations or leads exist), search, filter (city, state, status), sort, activate/deactivate (single & bulk), Excel/CSV import (20,000 rows max per file) and export. Auto IDs `LOC-000001` |
| Charging stations | Add / edit / view, filter by location/city/state/status/charger type, activate/deactivate/maintenance, Excel/CSV import & export, QR preview. Auto IDs `STN-000001` |
| Permanent QR codes | 128-bit `secrets.token_urlsafe` token per station, created automatically. Token and station mapping can never be edited or deleted (model-level guard). Branded PNG, print-ready A4 PDF (1/2/4/6 per page), bulk ZIP with manifest. Regeneration needs typed Station ID + reason; old token kept in history and shows "QR replaced" (never redirected) |
| Customer enquiry | `/q/<token>/` – no login. Station resolved **only** from the token in the database. Shows logo, station, location, city/state, address, form (name, mobile, email, category, message, privacy consent). CSRF, server validation, honeypot, per-IP rate limit, one-time form key against double submits, duplicate flagging (same mobile + station within N minutes), thank-you page with reference ID |
| Scan tracking | Every visit recorded with device/OS/browser, UTM parameters, bot detection, repeat-open detection, form-visit beacon, submission flag. Funnel: **Scan → Form visit → Submission → Lead → Conversion** |
| Lead management | Searchable, filterable (location, station, city, state, category, status, assignee, date range, duplicates), sortable, paginated. Detail page with locked source, status updates (full history), follow-up notes with dates, assignment with history, bulk status/assign, Excel/CSV export of the filtered list |
| Analytics | Funnel cards, daily/weekly/monthly trends, category mix, location-wise & station-wise tables (sortable, searchable), city/state breakdowns, top/bottom 10 stations, device mix, drill-down location → stations → leads |
| Reports | Full management workbook, station/location performance, daily/weekly/monthly, city/state/category, lead list, raw scan log – Excel or CSV |
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
│   ├── locations/           Location model, CRUD, import/export
│   ├── stations/            ChargingStation model, CRUD, import/export, QR auto-creation signal
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
Location 1 ──< ChargingStation 1 ── 1 QRCodeMapping 1 ──< QRTokenHistory (retired tokens)
                     │                    │
                     ├──< QRScanEvent >───┘
                     └──< Lead >── LeadStatusHistory, LeadNote, LeadAssignment
User (role, assigned_locations) ;  AuditLog ;  SystemSetting (singleton)
```

* `Lead.location`, `Lead.station`, `Lead.qr_mapping` use `PROTECT` and are also snapshotted
  (`location_code`, `station_name`, `qr_token`, …). `Lead.save()` refuses to change them.
* Stations and QR mappings use `PROTECT`; locations with stations/leads cannot be deleted –
  deactivate instead.

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
python manage.py seed_demo_data --locations 30 --stations-per-location 2 --leads 400
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

1. Creating a station (form, import or admin) fires a signal that creates its `QRCodeMapping` with a
   new cryptographically secure token that has never been used by any station (current or retired).
2. The printed code encodes `QR_BASE_URL/q/<token>/`.
3. On scan, `apps/leads/public_views.py` looks the token up in the database – nothing else from the
   request is used to pick the station.
   * unknown token → "QR not recognised" (404)
   * retired token → "QR replaced" (410), no redirect
   * station, location or QR inactive → "not accepting enquiries", no redirect, no lead saved
   * otherwise the station form is shown and a `QRScanEvent` is recorded
4. When the page renders in a real browser, a small beacon marks the scan as a *form visit*.
5. On submit the lead is saved with the station/location/token from the database, plus device,
   browser and UTM data; the scan is marked *submitted*; the customer sees a thank-you page.

**Choose the production `QR_BASE_URL` before printing stickers.** Tokens never change, but the
domain is part of the printed code. If the domain must change later, keep the old domain
redirecting `/q/*` to the new one.

---

## 5. Excel / CSV import formats

Download the templates from **Locations → Import** and **Charging Stations → Import**.

*Locations:* `Location ID (optional)`, `Location Name*`, `Address*`, `City*`, `District`, `State*`,
`PIN Code*`, `Latitude`, `Longitude`, `Contact Person`, `Contact Number`, `Status (Active/Inactive)`.
Rows matching an existing Location ID (or the same name + PIN) are updated when "update existing" is ticked.

*Stations:* `Station ID (optional, to update)`, `Location ID*`, `Station Name*`, `Station Address*`,
`City`, `State`, `Charger Type`, `Charger Capacity (kW)`, `Status`. Each new station automatically
gets its permanent QR code; images are rendered on first preview/download.

Import 1,000+ locations first, then their stations.

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

Also back up `media/qrcodes/` (images can be regenerated, tokens cannot – tokens live in the DB).

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

* Station identity comes only from the stored token; customer-submitted IDs are ignored.
* Tokens: 128-bit random, globally unique across current and retired tokens, immutable, not deletable.
* Deactivation never redirects a QR code; regeneration is confirmed, reasoned, audited and kept in history.
* Lead source fields are immutable at the model level.
* CSRF on every form; login lockout; per-IP enquiry rate limit; honeypot; bot filtering in analytics.
* Role-based data scoping on every list, detail, export and analytics query.
* CSV/Excel exports neutralise spreadsheet formula injection.
* `next=` redirects are validated; secure cookie/HSTS/SSL settings when DEBUG is off.
