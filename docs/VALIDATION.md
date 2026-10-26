# Validation record — 26 October 2026

Validated against the actual application in this cloud workspace with Python 3.12, Node.js 24, Django 5.2.18, SQLite, and Chromium. The source repository started empty; the application, migrations, frontend, fixtures, documentation, and CI workflow were created here.

| Check | Result |
|---|---|
| Backend numerical, import, API, authorization and security suite | 82 tests passed |
| Clean minimal Python virtual environment | Installed requirements and passed the same 82 tests |
| TypeScript and Vite production build | Passed |
| Chart renderer verification | 47 figure checks plus geometry, numeric formatting and invalid-input assertions passed |
| Browser journeys against the production build served by Django | All 8 passed |
| Workspace management browser checks | All 8 passed, no browser errors |
| Complete reusable install script rehearsal | Passed: venv, pinned Python dependencies, npm ci, frontend build, migrations and Django checks |
| Django checks, migration consistency and pip dependency consistency | Passed |
| Django production security checks | Passed with isolated generated check-only secret and production settings |
| npm production dependency audit | No reported vulnerabilities |
| Bundled map artifact checksum | Matches recorded verified-HTTPS source provenance |

The eight production browser scenarios exercise:

1. Real multi-sheet Excel upload, table selection, profiling, recommendations, template generation, drag, resize, color changes, save/reload, formula KPI, date filtering, preview, publish, fresh visitor access, mobile layout, draft isolation and republish.
2. Invalid-file messages and usable mobile workspace.
3. Genuine WebGL pie meshes, scatter, surface and 3D bars using actual uploaded values.
4. Calculated-field GUI, known numerical results, undo/redo and Top/Bottom-N persistence.
5. Maps with exact uploaded coordinates and bundled offline geography; no external browser map requests.
6. Actual supplied interval bounds and weighted chord ribbons, including public queries.
7. Cascading parent/child filters, correct reset behavior, and two-field relationship cross-filtering in private and public views.
8. Blank-canvas creation, persisted text, real uploaded raster image, design elements and publication without a required dataset.

Workspace checks exercise duplication, confirmed deletion, cancel/focus behavior, accurate saved-layout thumbnails, search/reset states, public gallery sorting, and removal of a deleted publication's URL. Tests use isolated anonymous sessions and clean their created records. Earlier exploratory fixtures were selectively removed after retaining an ignored local database/source backup. No user workspace with unrecognized records was removed.

## External prerequisites and unrun targets

- Live Google Sheets export was attempted but the cloud proxy denied access to the Google export host. The draft contains docs.google.com and *.sheets.googleusercontent.com; review and save these network settings, then retry. Controlled-response Google access, URL, permission and redirect tests pass. No Google credential is needed for a public sheet.
- The GitHub Actions workflow is prepared; it has not been run on GitHub from this unpushed checkout.
- Windows installation and an external Nginx/TLS deployment are documented but were not executed on those platforms.
- OCR for scanned PDFs, a private-Google OAuth UI/scheduler, cross-dataset joins, and specialized unregistered chart forms remain outside the current implementation. See README for precise limits.

Saving cloud configuration does not publish its snapshot or deploy the application externally. This record describes current-instance validation and the saved installation/startup steps, not a restored future task or an external production deployment.
