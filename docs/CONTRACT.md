# Implementation contract
Product: Prism, a no-login dataset-backed dashboard studio. Django + SQLite default, React/TypeScript/Vite. No external database, paid API or queue.

## Shared Python modules
`backend/studio/ingestion.py`: `inspect_source(filename: str, content: bytes, options: dict | None = None) -> dict` returns {tables:[{key,name,columns:[str],rows:[dict]}],warnings:[str]}; `fetch_sheet(url: str) -> (filename,bytes)` secure Google Sheets CSV access only. Source import size cap 25 MB, max rows 100000. Throw ValueError for friendly errors. Need csv/json/xlsx/xls/pdf, no arbitrary URL requests.
`backend/studio/analytics.py`: `profile(rows: list[dict], overrides: dict | None = None) -> dict` returns {row_count,column_count,columns:[{name,type,missing,unique,min,max,mean,median,std,categories?}],duplicates,warnings}; `recommend(profile:dict) -> list[dict]` each recommendation full chart spec {id,title,type,x,y,aggregation,series?,reason,score,group}; `query(rows, spec, schema=None) -> dict` return {labels:[],series:[{name,values:[]}],value:number|null,rows:[dict],columns:[str],... optional data for advanced charts}. One central safe formula, filtering + analytics engine. `CHART_TYPES` registry list with id/name/group and compatibility rules, `compatible(profile)` if helpful. Input chart config type defaults bar, x dimension, y measure, aggregation sum/count/distinct_count/average/min/max/median, formula, filters (list or {logic:'and'|'or',conditions:[]}) each {field,op,value}. `formula` syntax uses arithmetic and SUM(field),AVG(field),COUNT(field),MIN,MAX,MEDIAN; bracketed [Field Name] for spaces; no eval. Query returns rows raw/aggregated suitable tables/scatter etc. All JSON must be finite, null handled consistently. Chart registry and actual outputs coordinate with renderer agent.

## API
All URLs trailing slash. JSON error {error:string,details?:any}; 400 invalid, 403 ownership,404 missing,409 optimistic conflict. Cookies sessions, CSRF via `csrftoken` cookie and X-CSRFToken. API requests same origin or Vite proxy /api. Owner is anonymous server session, never a public token. IDs UUID strings.
GET /api/workspace/ -> {datasets:[dataset summary],dashboards:[dashboard summary]}
POST /api/imports/ multipart file OR JSON {sheets_url} -> {id,tables:[{key,name,columns:[str],preview:[dict],row_count}],warnings}. Staging previews only. original source retained privately.
POST /api/datasets/ {import_id,table_key,name,skip_rows?:number,header_row?:number,drop_duplicates?:bool,drop_empty?:bool} -> dataset detail.
GET /api/datasets/<id>/?page=1&page_size=50&search=&sort=&direction=asc -> {id,name,source_type,row_count,columns:[profile column],profile,preview:[dict],page,total_pages,version}
PATCH /api/datasets/<id>/ {name?,types?:{field:type},drop_duplicates?,drop_empty?}; DELETE.
POST /api/datasets/<id>/replace/ {import_id,table_key} -> dataset detail; reject if removes referenced fields, return details.
POST /api/datasets/<id>/refresh/ Google public only.
GET /api/datasets/<id>/recommendations/ -> {recommendations:[spec],chart_types:[{id,name,group}],kpis:[spec]}
POST /api/analytics/query/ {dataset_id,...spec} -> query result
POST /api/analytics/export/ {dataset_id,...spec} -> CSV safe spreadsheet output.
POST /api/dashboards/ {title,description?,config} -> full dashboard
GET/PATCH/DELETE /api/dashboards/<id>/; PATCH {title,description,config,revision} optional revision but client must send latest. Full: {id,title,description,config,revision,published_slug,published_at,updated_at}.
config = {widgets:[{id,type,title,dataset_id?,x?,y?,series?,aggregation?,formula?,...style fields,layout:{x,y,w,h},filters?:[],filter?:{field,op,value,targets?:[widget ids]},text?,image?}],theme:{mode,background,surface,text,accent,palette,font,...},grid:{columns:12,gap:16,rowHeight:70,padding:24},crossfilter?:boolean,template?:string}. Widget chart type direct `type` (bar,line,pie,kpi,table,etc), text/filter/image/shape special; all analytic config at widget root. Widget properties panel must use this shape.
POST /api/dashboards/<id>/publish/ {} -> {slug,url,version}; POST /unpublish/; POST /duplicate/.
GET /api/published/?search=&sort= -> {dashboards:[{title,description,slug,published_at,updated_at,config (NO private data or workspace)}]}
GET /api/published/<slug>/ -> {title,description,config,version,published_at,datasets:[{id,name,columns}]} (NO rows or private edit credentials).
POST /api/published/<slug>/query/ {widget_id,filters?:[]} -> query using immutable publication snapshot, widget config selected server side, no arbitrary configs or dataset refs. Filtering cannot access fields outside widget dataset. Public chart table shows only selected chart-visible fields. Export public not necessary unless safe.
GET /api/health/ -> {status:'ok'}.

## Frontend ownership
Root: App.tsx routing, workspace/dataset/import/templates pages, API utilities and integration, build config.
Editor agent: `frontend/src/pages/Builder.tsx`, `frontend/src/components/DashboardCanvas.tsx`, `frontend/src/components/Properties.tsx`, `frontend/src/templates.ts`, `frontend/src/editor.css`. Import shared from ../api, ../types. Export default Builder; routes /builder/:id and /dashboards/:slug public. Builder fetches route IDs via react-router-dom useParams. Public page export `PublishedDashboard` from Builder. templates export `TEMPLATES` array [{id,name,description,theme,layout?}], `makeConfig(templateId,dataset,recommendations)` => config. Root will build template selection and POST dashboards.
Renderer agent: `frontend/src/components/Chart.tsx`, `frontend/src/chartTypes.ts`; export default Chart component props {widget:Widget,data:QueryResult,theme?:Theme,onSelect?:(field:string,value:unknown)=>void}; data fetching outside component. Plotly genuine 3D scatter/surface/bar supported, no CSS-faked 3D pie. Registry UI must only advertise real supported renderers; document unsupported 3D pie.
Backend API agent: all backend project/settings/models/migrations/views/urls/tests EXCEPT ingestion.py,analytics.py and their unit tests (owned respective agents).
Ingestion agent tests `backend/studio/test_ingestion.py`; analytics agent tests `backend/studio/test_analytics.py`. Each can import stdlib unittest/Django SimpleTestCase.

## Tooling
Python dependencies root requirements.txt owned root: Django 5.2, pandas,numpy,openpyxl,xlrd,pdfplumber,requests,gunicorn,whitenoise. Venv .venv root. Frontend npm: React 19 + router, lucide-react, react-grid-layout 1.5.2, plotly.js-dist-min + react-plotly.js, react-resizable, TypeScript,Vite. API returns empty values never fabricated data; sample_data explicitly examples only.
