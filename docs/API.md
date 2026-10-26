# Prism JSON API

All API URLs have a trailing slash. The React application uses same-origin requests. Vite proxies `/api/` during development; Django serves `frontend/dist` in a built installation.

## Anonymous editing and privacy

Call `GET /api/workspace/` first. Django creates an anonymous private workspace using a server-side session; the browser retains a `sessionid` HttpOnly, SameSite=Lax cookie. This cookie is the editing capability. There is no public edit token, registration, or login screen. Keep the browser cookies to retain editing access. Clearing cookies or expiring the session loses access; account recovery and transferable edit links are not implemented.

Every unsafe request, including public analytical POST requests, requires the `X-CSRFToken` header matching the `csrftoken` cookie and the browser's same-origin credentials. Ownership applies to dataset reads, file downloads, import selection, queries, draft reads/writes, deletion, duplication, and publishing. Another anonymous workspace receives 403 when attempting to access an existing private ID. Private source storage is never mapped to a media-serving URL.

Published URLs are public. Visitors can query only analytical widgets stored in the active publication and supply filter selections on fields exposed by that dashboard. They cannot substitute chart specifications, data sources, formulas, or output columns. Public responses project out unrelated source fields. A published table intentionally exposes its selected columns. Publishing snapshots the data as well as the configuration, so subsequent dataset replacements and draft edits do not alter an existing publication. Republish explicitly to update it. Unpublishing immediately removes the public API entry while keeping versions privately stored.

## Response conventions

Success responses are JSON except CSV exports and authorized source-file downloads. Errors use `{ "error": "Actionable explanation", "details": optional }`.

| Status | Meaning |
|---|---|
| 400 | Invalid source, fields, formula, request, or configuration |
| 403 | CSRF failure or private workspace ownership mismatch |
| 404 | Missing item or unpublished dashboard |
| 409 | Stale dashboard revision, referenced dataset deletion, or schema-breaking replacement |
| 413 | File upload too large |
| 429 | Rate limit; retry after the supplied Retry-After duration |
| 500 | Unexpected failure; server-side logs contain diagnostic evidence |

## Import and datasets

1. `POST /api/imports/` accepts multipart `file`, or JSON `{ "sheets_url": "https://docs.google.com/spreadsheets/d/.../edit" }`. It returns an import `id`, independently selectable `tables` (`key`, `name`, `columns`, first 20 `preview` records, `row_count`), and extraction `warnings`.
2. `POST /api/datasets/` finalizes `{ "import_id": "uuid", "table_key": "sheet-0", "name": "Sales", "skip_rows": 0, "header_row": 0, "drop_duplicates": false, "drop_empty": false }`. Header/skip options are optional and zero-based; `header_row` is relative to rows remaining after `skip_rows`. Options reparse the privately retained original source.
3. `GET /api/datasets/<id>/` returns metadata, `columns`, `profile`, and a paginated `preview`. Parameters: `page`, `page_size` (1–200), `search`, `sort` (column), `direction` (`asc`/`desc`).
4. `PATCH /api/datasets/<id>/` supports `name`, `types` mapping column names to inferred type overrides, `drop_duplicates`, and `drop_empty`. Original source bytes remain retained. Type changes affect profiling and compatibility; raw source values are not silently rewritten.
5. `POST /api/datasets/<id>/replace/` accepts `import_id` and `table_key`, preserving the dataset UUID. It rejects removals of fields referenced by saved draft widgets with affected dashboard/widget details.
6. `POST /api/datasets/<id>/refresh/` reconnects a Google Sheets import. Other source types require replacement.
7. `GET /api/datasets/<id>/source/` downloads the original source privately.
8. `DELETE /api/datasets/<id>/` requires removing draft references first. An original import file is removed when no dataset still references that import.
9. `GET /api/datasets/<id>/recommendations/` returns `recommendations`, `kpis`, and the renderer registry `chart_types`, including `compatible` and a reason when not compatible.

Multiple sources/datasets are supported. Joins are not inferred automatically. Limits are 25 MB per source, 100,000 rows per table, 500 columns, 100 tables, 250,000 total extracted records, and bounded PDF/JSON/Excel parser resources. CSV encodings, JSON normalization, multi-sheet Excel, ruled text PDF extraction, and constrained Google Sheets fetches are handled by `studio.ingestion`. Image-only PDFs require external OCR before importing; uncertain extractions produce warnings. Optional private Google Sheets access uses `GOOGLE_SHEETS_ACCESS_TOKEN` server-side; public sheets do not require a credential. No OAuth consent/login flow or scheduled refresh service is included.

## Analytics

`POST /api/analytics/query/` accepts a private dataset ID plus a chart specification:

```json
{
  "dataset_id": "dataset-uuid",
  "type": "bar",
  "x": "Region",
  "y": "Revenue",
  "aggregation": "sum",
  "filters": {"logic": "and", "conditions": [
    {"field": "Date", "op": "between", "value": ["2025-01-01", "2025-12-31"]}
  ]},
  "sort": "value",
  "direction": "desc",
  "limit": 20
}
```

Standard outputs contain `labels`, `series` (`name`, `values`), `value`, `rows`, `columns`, `row_count`, and `truncated`. Advanced renderers receive additional fields such as correlation/surface `matrix`, Sankey `nodes`/`links`, Gantt task intervals, or KPI comparison values. Unsupported or incompatible configurations produce a validation error rather than fabricated values. All JSON numbers are finite.

KPIs accept aggregations or a restricted formula such as `SUM([Revenue]) - SUM([Cost])`. Expressions are parsed with an AST interpreter; imports, attributes, arbitrary function calls, Python execution, and SQL execution are unavailable. `calculated_fields` accepts up to 20 named row expressions and can be reused by the chart fields. Divide-by-zero results are represented as null, not Infinity. Charts and KPIs use the same filter and aggregation engine.

`POST /api/analytics/export/` uses the same private specification and produces actual chart/table data in UTF-8 CSV. Text cells beginning with spreadsheet formula characters are prefixed safely to prevent formula execution when opened in spreadsheet software.

## Dashboards and publication

- `POST /api/dashboards/`: `{title, description, config}` creates a private draft.
- `GET /api/dashboards/<id>/`: retrieves the draft, its `revision`, and publication metadata.
- `PATCH /api/dashboards/<id>/`: `{title?, description?, config?, revision}` updates the current draft. Send the last returned revision. A stale write returns 409; the client must reload rather than overwrite other edits.
- `POST /api/dashboards/<id>/duplicate/`: produces an unpublished independent draft.
- `DELETE /api/dashboards/<id>/`: removes the draft and all its publication snapshots.
- `POST /api/dashboards/<id>/publish/`: validates dataset ownership/references, analytical queries, formulas, filters, IDs, image URLs, and grid bounds before atomically creating a publication. Returns `{slug, url, version}`. Slugs remain stable across republishing and naming collisions are resolved automatically.
- `POST /api/dashboards/<id>/unpublish/`: withdraws public access.
- `GET /api/published/?search=&sort=newest|name`: public gallery. Drafts are excluded.
- `GET /api/published/<slug>/`: public configuration and metadata for exposed fields, with no source records or editing credentials.
- `POST /api/published/<slug>/query/`: `{ "widget_id": "saved-widget-id", "filters": [] }`. Runtime filters combine with fixed widget filters using AND; the saved fixed filter group preserves its configured AND/OR semantics.

Configurations support up to 80 widgets, unique widget IDs, 1–48 grid columns, bounded positions/sizes, independent theme settings, and a 4 MB JSON limit. Image widgets accept HTTPS URLs or raster PNG/JPEG/WebP/GIF data URLs; SVG/script URLs are rejected. Text is stored as plain text and rendered as escaped React text.

## Operations

`GET /api/health/` checks that the application is serving. Run migrations separately as part of startup preparation. The default database and upload directory live in `.local/`, which must be backed up together with the development secret if edit sessions must survive restoration. Do not serve `.local/` from Nginx.

Rate limits use Django's cache and the direct client IP: imports/publishing have tighter limits than analytical queries. The local cache is per process; multi-worker production deployments should configure a shared Django cache or enforce equivalent limits at the trusted reverse proxy. Production mode requires `DJANGO_DEBUG=0`, a private `DJANGO_SECRET_KEY`, explicit allowed hosts and HTTPS. Secure cookies, SSL redirect, HSTS, frame denial, and content-type sniffing protection are enabled in production. Only set `DJANGO_TRUST_PROXY=1` when the reverse proxy removes untrusted forwarded headers.

### Hierarchical filter options

`POST /api/datasets/<id>/filter-options/` accepts `{ "fields": ["Region", "City"] }` in the owning session. It returns `{ "fields": [...], "paths": [["North", "York"], ...], "truncated": false }` using actual distinct source combinations (up to three fields and 1,000 paths).

`POST /api/published/<slug>/filter-options/` accepts only `{ "widget_id": "saved-hierarchy-widget" }`. It reads the fields and data from that publication's immutable hierarchy configuration. Visitors cannot substitute other fields or source datasets. Hierarchy widgets store `control: "hierarchy"`, a parent in `filter.field`, and one or two child names in `hierarchy_fields`. Runtime selections become AND conditions; parent changes clear child selections.

Provided interval charts use `type: "confidence_band"`, `x`, `y`, `lower`, and `upper`. Bounds come from uploaded columns and must satisfy lower ≤ center ≤ upper; duplicate dimension values are rejected to avoid mathematically invalid interval aggregation. Weighted chord charts use `type: "chord"`, source `x`, destination `series`, and measure `y`.
