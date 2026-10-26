# Stavatech Prism Dashboard

Stavatech Prism Dashboard turns uploaded business data into editable, interactive dashboards. It combines a Django backend, a React/TypeScript editor, Plotly visualizations, and SQLite persistence. No account, external database, Redis, paid AI service, or Docker installation is required.

The application starts with an empty workspace. All analytical results come from datasets you import. Files in `sample_data/` are explicitly synthetic examples for trying the workflow; they are never substituted for uploaded data or automatically published.

## What works

- CSV, JSON, Excel `.xlsx`/`.xls`, text-based PDF tables, and accessible Google Sheets imports. Workbook sheets, detected PDF tables, and nested JSON table candidates can be previewed and selected before import.
- Configurable header/skip rows, dataset naming, controlled duplicate/empty-row cleanup, private original-file retention, multiple datasets, paginated previews, typed sorting, search, inferred-type overrides, quality warnings, replacement checks, and manual Google Sheets refresh.
- Deterministic field profiling, compatible chart recommendations, numeric/date/category classification, aggregation, filters, safe calculated fields and KPI formulas. Identifiers are treated separately from continuous measurements.
- A chart registry backed by real renderers: comparison and trend charts, contributions, distributions, statistical relationships, coordinate-based geographic maps, Sankey and hierarchical plots, business indicators, tables, and genuine WebGL 3D visualizations. Incompatible choices are disabled or produce actionable validation errors.
- Five distinct dashboard templates plus a blank canvas. Templates populate from applicable recommendations for the selected dataset.
- Drag/drop, grid-based positioning, live resizing, duplicate/delete, undo/redo, per-widget properties, text, raster images/logos, shapes, canvas/theme/typography controls, responsive layouts, and desktop/tablet/phone previews.
- Dashboard, selected-widget, and local filters; category cross-filtering; reusable calculated metrics; chart previews; autosave with revision conflict protection and local recovery of interrupted edits.
- Private drafts, stable public dashboard URLs, a searchable published gallery, immutable publication snapshots, authorized re-editing, republishing, duplication, and unpublishing.
- PNG/SVG chart export where supported, visible chart data CSV export, dashboard configuration export, and browser print/save-to-PDF. 3D SVG export may contain rasterized WebGL content.

The complete API and privacy model are documented in [docs/API.md](docs/API.md). The implementation contract is in [docs/CONTRACT.md](docs/CONTRACT.md).

## Requirements

Use Python 3.12 or 3.13 and Node.js 22.12+ or 24, with npm. Development was checked with Python 3.12 and Node.js 24. The backend dependencies are pinned in `requirements.txt`; the frontend uses `frontend/package-lock.json`.

SQLite is built into Python. A conventional virtual environment and local writable storage are sufficient.

## Install and run on Linux or macOS

Run these commands from the repository root:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
cd frontend
npm ci
npm run build
cd ..
.venv/bin/python backend/manage.py migrate
.venv/bin/python backend/manage.py runserver 127.0.0.1:8000
```

Open the development server address printed in the terminal. Django serves the built React application and API on the same origin. Rebuild the frontend after changing it if using this mode.

For frontend development with hot reload, keep Django running and open another terminal:

```bash
cd frontend
npm run dev
```

Open the Vite address printed in that terminal. Vite proxies `/api/` to Django on port 8000, preserving same-origin cookies and CSRF checks. Use one hostname consistently while editing; switching between hostnames creates a different browser cookie context. There is no separate registration or login step.

## Install and run on Windows 11

Use PowerShell from the repository root. Activation is optional; these commands invoke the virtual environment directly and avoid activation-policy changes:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
cd frontend
npm ci
npm run build
cd ..
.\.venv\Scripts\python.exe backend\manage.py migrate
.\.venv\Scripts\python.exe backend\manage.py runserver 127.0.0.1:8000
```

For hot reload, open a second PowerShell terminal, enter `frontend`, and run `npm run dev`. Gunicorn is a Linux production server; use Django's development server for local Windows development. Windows commands are provided but were not executed on a Windows machine in this workspace.

## Use the application

1. Open the workspace and choose **Upload dataset**. Drop a CSV, JSON, Excel workbook, or table-based PDF, or connect a Google Sheets URL.
2. Review the detected worksheets/tables and data preview. Name the dataset, adjust optional header/skip settings, choose cleanup explicitly, and import.
3. Review **Field insights** and quality warnings. Change inferred types when needed. Open **Recommended charts** to preview actual calculations.
4. Choose **Generate dashboard**, select a template, and open the visual editor. **Create From Scratch** starts an empty canvas.
5. Add recommended charts or elements, drag the widget handle to reposition, resize with a card edge/corner, and use Properties for fields, aggregation, colors, text, styles, filter controls, and calculated metrics. A dashboard may use more than one uploaded dataset; filters apply only to the configured dataset and targets.
6. Add filters and optionally enable **Cross-filter**. Preview desktop/tablet/mobile views and confirm the calculated results. Undo/redo and autosave protect normal edits; a stale revision is reported rather than silently overwriting another tab.
7. Choose **Publish** and review the privacy notice. Publishing validates the configuration and snapshots both data and layout. The dashboard appears at `/dashboards/` and receives a dedicated `/dashboards/<slug>/` URL.
8. Reopen the private draft from your workspace, make changes, and **Republish**. Draft edits and dataset replacements leave the current publication unchanged until a successful republish. **Unpublish** withdraws public access.

For a known-value example, import `sample_data/example_business.xlsx` and choose the Sales worksheet. Its companion README lists expected totals. The Operations worksheet exercises a separate operational schema.

### Safe formulas

KPI examples:

```text
SUM([Revenue]) - SUM([Cost])
SUM([Revenue]) / SUM([Units])
SUM([Accepted]) / SUM([Produced]) * 100
```

Row-level calculated fields use expressions such as `[Revenue] - [Cost]`; the field can then be selected as a measure. Aggregations and arithmetic run through a bounded AST interpreter, never unrestricted Python evaluation. Unsupported functions are rejected. Division by zero produces an actionable validation error rather than a fabricated value or Infinity.

## Anonymous ownership and publishing privacy

Editing authorization is the browser's private HttpOnly session cookie. Another anonymous workspace cannot read your source files, query private datasets, change drafts, or publish them. Keep the original browser cookies: clearing them or letting the session expire loses editing access. No account recovery, cross-device account, or transferable editing link is implemented.

Published dashboard URLs are public and intentionally expose their rendered results and selected table fields. Visitors can apply permitted filter contexts and export visible chart results. Do not publish sensitive information merely because the original file remains private. Public endpoints accept saved widget IDs and filters; they cannot replace datasets, formulas, or selected output columns.

Original sources, processed records, drafts, publication snapshots, and Django sessions are retained locally in the default `.local/` storage. The `.local/` directory is ignored by Git and must not be exposed by a web server.

## Configuration and persistence

Settings are read from process environment variables. `.env.example` documents supported names; copying it to `.env` does **not** automatically load it. Export variables in your shell or configure them through your service manager/hosting environment. Default local development does not require any environment variables.

| Variable | Default / purpose |
|---|---|
| `DJANGO_DEBUG` | `1` for local development; use `0` in production |
| `DJANGO_SECRET_KEY` | Local development creates a private `.local/django-secret`; production requires an explicit stable secret |
| `DJANGO_ALLOWED_HOSTS` | Any host in development; set explicit public hostnames for production |
| `DJANGO_CSRF_TRUSTED_ORIGINS` | Comma-separated trusted HTTPS origins when required by deployment |
| `PRISM_DATA_DIR` | `<repository>/.local`; stores database, private uploads, local secret, and local static output |
| `SQLITE_PATH` | `<PRISM_DATA_DIR>/db.sqlite3` |
| `DATABASE_URL` | Optional `sqlite`, `postgresql`/`postgres`, or `mysql` URL; install the selected external driver separately |
| `GOOGLE_SHEETS_ACCESS_TOKEN` | Optional server-side bearer token authorized to read a private Google Sheet; not exposed to the frontend |
| `DJANGO_TRUST_PROXY` | `0`; enable only behind a proxy that removes untrusted forwarded headers |
| `DJANGO_SECURE_SSL_REDIRECT` | `1` in production |

Back up the SQLite database, private uploads, and stable secret together. Preserve the database session table if editing capabilities must survive a restore. Publication snapshots are stored in SQLite; live server processes are not persistent state. A new machine must run the startup commands again.

No worktree is needed for an isolated cloud task; use its existing checkout. Cloud installation/startup instructions are saved separately in environment configuration. Saving those instructions does not publish the environment.

## Tests and validation

Backend unit, numerical, integration, and security tests:

```bash
.venv/bin/python backend/manage.py test studio
.venv/bin/python backend/manage.py check
.venv/bin/python backend/manage.py makemigrations --check --dry-run
```

Use `.\.venv\Scripts\python.exe` instead of `.venv/bin/python` in Windows PowerShell.

The suite exercises actual XLSX/XLS inputs, multiple worksheets, real text PDF extraction, CSV encoding/delimiters, JSON nesting, Google URL/authentication failures, type inference, known numerical results, formula safety, filters, publication version isolation, ownership boundaries, CSRF, safe CSV export, schema-breaking replacements, and save/reload conflicts.

Frontend build and renderer checks:

```bash
cd frontend
npm run build
npm run test:charts
```

Browser workflow tests require Django on port 8000, Vite on port 5173, and Chromium:

```bash
cd frontend
npm run test:e2e
npm run test:workspace
```

The Playwright configuration uses `CHROMIUM_PATH` when set, otherwise `/usr/bin/chromium`. On Windows set it to a Chrome/Chromium executable, for example:

```powershell
$env:CHROMIUM_PATH = "C:\Program Files\Google\Chrome\Application\chrome.exe"
```

`PRISM_TEST_URL` overrides the frontend test origin. The browser tests use their own anonymous sessions and explicitly uploaded fixtures. Trace/screenshots from failures are local generated artifacts, not source files. WebGL support is required for real 3D chart rendering; a browser that cannot provide it receives an actionable message.

## Production deployment on Ubuntu/Linux

Build the frontend, install the pinned backend requirements, and migrate the database before starting a production worker. Set `DJANGO_DEBUG=0`, a long private `DJANGO_SECRET_KEY`, explicit `DJANGO_ALLOWED_HOSTS`, and an HTTPS origin. Generate the secret once, store it securely, and reuse it across restarts; do not regenerate it in every startup command.

Place `PRISM_DATA_DIR` on persistent storage writable by the application user. Keep private uploads outside the web root. Start from one Gunicorn worker for a small SQLite installation; increasing worker counts requires reviewing SQLite write concurrency and the rate-limit/cache backend.

From the repository root:

```bash
.venv/bin/python backend/manage.py migrate --noinput
.venv/bin/python backend/manage.py check --deploy
.venv/bin/gunicorn --chdir backend config.wsgi:application --bind 127.0.0.1:8000 --workers 1 --threads 4 --timeout 120
```

Django/WhiteNoise serves `frontend/dist`; no Vite server is needed in production. Put Nginx or another trusted HTTPS reverse proxy in front of Gunicorn. An example Nginx server block, after configuring a valid TLS certificate:

```nginx
server {
    listen 443 ssl;
    server_name analytics.example.com;
    ssl_certificate /etc/letsencrypt/live/analytics.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/analytics.example.com/privkey.pem;
    client_max_body_size 30m;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_read_timeout 120s;
    }
}
```

Configure HTTP-to-HTTPS redirection and set `DJANGO_TRUST_PROXY=1` only with the trusted header handling above. Do not add an Nginx alias for `.local/` or private uploads. Production settings enable secure cookies, HSTS, HTTPS redirect, frame protection, and content-type sniffing protection. Run `check --deploy` with the actual deployment variables; the local development settings intentionally do not enforce HTTPS.

The built-in rate limiter uses Django's local cache and direct client IP, so it is per process and sees the reverse proxy's address. For a multi-user/multi-worker service, enforce limits at the trusted proxy or configure an appropriate shared cache and trusted client-identity handling. Redis is optional, not required for the local application.

## Current limits and known gaps

- Imports are bounded to 25 MB per source, 100,000 rows per table, 500 columns, 100 tables, and 250,000 total extracted rows. PDF pages, ZIP expansion, JSON depth, and cell lengths have additional safety bounds. Chart responses are bounded/downsampled and indicate truncation. Imports and analytical queries are synchronous; this is intended for bounded local/small-team workloads, not unbounded enterprise-scale processing.
- Configurations support up to 80 widgets, 1–48 backend grid columns, bounded sizes/positions, and 4 MB JSON. Raster image upload is limited to 2 MB in the interface. Protected source files are retained; source reimports/cleanup are explicit.
- Image-only/scanned PDFs require an external OCR step. Text PDF extraction is heuristic and must be reviewed. There is no fabricated fallback for an unreadable table.
- Public Google Sheets require no credentials when the server can reach the Google export hosts; the current cloud instance requires the saved Google network-domain changes to be applied before live access can be verified. Private access requires a server-authorized bearer token or a local exported file. No Google OAuth connection UI, worksheet discovery for a private account, scheduled refresh service, or automatic token renewal is included; use a worksheet URL with its `gid` for selection.
- Multiple datasets can feed a dashboard, but cross-dataset joins and relationship editing are not implemented. Filters do not infer joins from matching column names.
- Specialized forms outside the chart registry, including streamgraphs and floating bars, are not implemented. Confidence bands require explicitly supplied lower/upper bounds and do not invent confidence intervals. The interface only advertises actual renderers. Geographic maps require actual latitude/longitude columns and do not guess coordinates from place names; world outline data is bundled locally under its included license. 3D charts need a working browser WebGL implementation.
- Hierarchical category controls use actual parent–child combinations with up to three levels and 1,000 distinct paths; changing a parent resets its children. Category selections, numeric range sliders, and numeric/date range inputs are available. Server-side relative-date predicates are supported, but there is no scheduled/background service.
- Dashboard PDF output uses browser print/save-to-PDF; there is no server-side report renderer or whole-dashboard PNG capture. Configuration export does not bundle private source data.
- Anonymous sessions provide capability-based ownership without accounts. Recovery after cookie loss, transfer to another device, team roles, audits for regulated environments, and organizational identity integration remain outside this implementation.
- Linux/Python/Chromium checks run in the cloud workspace. Windows installation instructions and a live internet Google Sheets authorization flow require verification on those platforms/accounts. Nginx/TLS deployment is documented; no external production deployment is performed automatically.

These limitations are explicit scope boundaries; no unavailable feature is represented by a placeholder action or invented analytical result.

The exact current-instance results and unrun external targets are recorded in [docs/VALIDATION.md](docs/VALIDATION.md). GitHub Actions runs the backend suite, production build, renderer assertions, browser journeys and workspace-management checks on push/pull requests; that hosted workflow has not yet been executed from this checkout.
