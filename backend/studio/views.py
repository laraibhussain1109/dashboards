"""JSON APIs. Private editing is scoped to an anonymous, HttpOnly session."""
import copy
import functools
import hashlib
import json
import logging
import secrets
import uuid
from datetime import timedelta
from pathlib import Path
from django.conf import settings
from django.core.cache import cache
from django.core.exceptions import PermissionDenied, RequestDataTooBig, SuspiciousOperation
from django.core.files.base import ContentFile
from django.db import IntegrityError, transaction
from django.db.models import F, Max
from django.http import FileResponse, Http404, HttpResponse, JsonResponse
from django.utils import timezone
from django.utils.text import slugify
from django.views.decorators.csrf import ensure_csrf_cookie
from .models import Dashboard, Dataset, ImportJob, Publication
from .services import (TYPE_NAMES, SPECIAL_WIDGETS, chart_types, clean_rows, csv_bytes, dashboard_detail, dataset_detail, dataset_summary, fields_in_spec, json_safe, owned, positive_int, remove_unused_import, text, validate_config)

logger = logging.getLogger(__name__)


class APIConflict(Exception):
    pass


class APIRateLimit(Exception):
    pass


def response(data, status=200):
    return JsonResponse(json_safe(data), status=status, json_dumps_params={'allow_nan': False})


def csrf_failure(request, reason=''):
    return response({'error': 'Your security cookie is missing or expired. Reload the page and try again.'}, 403)


def owner(request):
    if not request.session.get('workspace'):
        request.session['workspace'] = secrets.token_urlsafe(32)
    return request.session['workspace']


def rate_limit(request, category, limit=120):
    # Per process by default. A shared Django cache can be configured for multi-worker deployments.
    address = request.META.get('REMOTE_ADDR', 'unknown')
    identity = hashlib.sha256(address.encode()).hexdigest()[:24]
    bucket = int(timezone.now().timestamp() // 60)
    key = f'prism:{category}:{identity}:{bucket}'
    if cache.add(key, 1, timeout=65):
        count = 1
    else:
        try:
            count = cache.incr(key)
        except ValueError:
            cache.set(key, 1, timeout=65)
            count = 1
    if count > limit:
        raise APIRateLimit('Too many requests. Wait a minute and try again.')


def api(methods, *, category='api', limit=240):
    def decorator(fn):
        @functools.wraps(fn)
        def wrapped(request, *args, **kwargs):
            if request.method not in methods:
                result = response({'error': 'Method not allowed.'}, 405)
                result['Allow'] = ', '.join(methods)
                return result
            try:
                rate_limit(request, category, limit)
                return fn(request, *args, **kwargs)
            except APIConflict as exc:
                return response({'error': str(exc)}, 409)
            except APIRateLimit as exc:
                result = response({'error': str(exc)}, 429)
                result['Retry-After'] = '60'
                return result
            except PermissionDenied as exc:
                return response({'error': str(exc) or 'This private item is not available in your workspace.'}, 403)
            except Http404 as exc:
                return response({'error': str(exc) or 'Not found.'}, 404)
            except RequestDataTooBig:
                return response({'error': 'The request exceeds the upload limit.'}, 413)
            except (ValueError, TypeError, KeyError, OverflowError, RecursionError) as exc:
                return response({'error': str(exc) or 'Invalid request.'}, 400)
            except IntegrityError:
                return response({'error': 'This item changed concurrently. Reload and try again.'}, 409)
            except SuspiciousOperation:
                return response({'error': 'The request could not be accepted.'}, 400)
            except Exception:
                logger.exception('Unexpected failure in %s', fn.__name__)
                return response({'error': 'The operation failed unexpectedly. Your saved data has been preserved.'}, 500)
        return wrapped
    return decorator


def body(request):
    if len(request.body) > 4 * 1024 * 1024:
        raise ValueError('JSON requests may not exceed 4 MB.')
    try:
        value = json.loads(request.body or b'{}', parse_constant=lambda value: (_ for _ in ()).throw(ValueError('Non-finite numbers are not allowed.')))
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise ValueError('Request body is not valid JSON.')
    if not isinstance(value, dict):
        raise ValueError('Request body must be a JSON object.')
    return value


@api(['GET'])
def health(request):
    return response({'status': 'ok'})


@ensure_csrf_cookie
@api(['GET'])
def workspace(request):
    workspace_owner = owner(request)
    return response({'datasets': [dataset_summary(d) for d in Dataset.objects.filter(owner=workspace_owner).order_by('-updated_at')], 'dashboards': [dashboard_detail(d) for d in Dashboard.objects.filter(owner=workspace_owner).order_by('-updated_at')]})


@api(['POST'], category='imports', limit=20)
def import_source(request):
    from .ingestion import fetch_sheet, inspect_source
    workspace_owner = owner(request)
    source_url = ''
    options = {}
    if request.content_type == 'multipart/form-data':
        upload = request.FILES.get('file')
        if not upload:
            raise ValueError('Choose a file to upload.')
        if upload.size > settings.PRISM_MAX_UPLOAD_BYTES:
            return response({'error': 'Files must be 25 MB or smaller.'}, 413)
        filename = Path(upload.name).name[:255]
        content = upload.read()
        if request.POST.get('options'):
            options = json.loads(request.POST['options'])
            if not isinstance(options, dict):
                raise ValueError('Import options must be an object.')
        source_type = Path(filename).suffix.lower().lstrip('.')
    else:
        data = body(request)
        source_url = text(data.get('sheets_url', ''), 'Google Sheets URL', 2048, True)
        filename, content = fetch_sheet(source_url)
        source_type = 'google_sheets'
    if not content:
        raise ValueError('The source file is empty.')
    if len(content) > settings.PRISM_MAX_UPLOAD_BYTES:
        return response({'error': 'Files must be 25 MB or smaller.'}, 413)
    result = inspect_source(filename, content, options)
    tables = result.get('tables', [])
    if not tables or not any(t.get('rows') for t in tables):
        raise ValueError('No usable data tables were found in this source.')
    if any(len(t.get('rows', [])) > settings.PRISM_MAX_ROWS for t in tables):
        raise ValueError('Each table supports up to 100,000 records.')
    # Expire this owner's unused staging sources; datasets keep their originals.
    stale = ImportJob.objects.filter(owner=workspace_owner, created_at__lt=timezone.now() - timedelta(days=1), datasets__isnull=True)
    for item in stale:
        remove_unused_import(item)
    job = ImportJob(owner=workspace_owner, filename=filename, source_type=source_type, source_url=source_url, tables=json_safe(tables), warnings=result.get('warnings', []))
    job.source.save(f'{uuid.uuid4().hex}{Path(filename).suffix.lower()}', ContentFile(content), save=True)
    return response({'id': str(job.id), 'tables': [{'key': str(t['key']), 'name': t['name'], 'columns': t.get('columns', []), 'preview': t.get('rows', [])[:20], 'row_count': len(t.get('rows', []))} for t in tables], 'warnings': job.warnings}, 201)


def selected_table(job, data):
    from .ingestion import inspect_source
    tables = job.tables
    options = {key: data[key] for key in ('header_row', 'skip_rows', 'delimiter', 'encoding', 'json_path') if key in data}
    for key in ('header_row', 'skip_rows'):
        if key in options:
            options[key] = positive_int(options[key], key, 0, 10000)
    if options:
        with job.source.open('rb') as handle:
            tables = inspect_source(job.filename, handle.read(), options)['tables']
    key = str(data.get('table_key', tables[0]['key'] if len(tables) == 1 else ''))
    table = next((table for table in tables if str(table['key']) == key), None)
    if not table:
        raise ValueError('Select one of the available tables or worksheets.')
    rows = json_safe(clean_rows(table['rows'], data))
    if len(rows) > settings.PRISM_MAX_ROWS:
        raise ValueError('Each dataset supports up to 100,000 records.')
    return table, rows


@api(['GET', 'POST'], category='datasets', limit=120)
def datasets(request):
    from .analytics import profile
    workspace_owner = owner(request)
    if request.method == 'GET':
        return response({'datasets': [dataset_summary(d) for d in Dataset.objects.filter(owner=workspace_owner).order_by('-updated_at')]})
    data = body(request)
    job = owned(ImportJob, data.get('import_id'), workspace_owner)
    table, rows = selected_table(job, data)
    dataset = Dataset.objects.create(owner=workspace_owner, name=text(data.get('name', table['name']), 'Dataset name', 160, True), source_type=job.source_type, source_import=job, source_table=str(table['key']), records=rows, profile_data=json_safe(profile(rows)))
    return response(dataset_detail(dataset), 201)


@api(['GET', 'PATCH', 'DELETE'], category='datasets', limit=180)
def dataset_item(request, dataset_id):
    from .analytics import profile
    dataset = owned(Dataset, dataset_id, owner(request))
    if request.method == 'GET':
        page = positive_int(int(request.GET.get('page', 1)), 'Page', 1, 100000)
        page_size = positive_int(int(request.GET.get('page_size', 50)), 'Page size', 1, 200)
        return response(dataset_detail(dataset, page=page, page_size=page_size, search=request.GET.get('search', '')[:200], sort=request.GET.get('sort', ''), direction=request.GET.get('direction', 'asc')))
    if request.method == 'DELETE':
        references = [d.title for d in Dashboard.objects.filter(owner=dataset.owner) if any(str(w.get('dataset_id')) == str(dataset.id) for w in d.config.get('widgets', []))]
        if references:
            return response({'error': 'Remove this dataset from its draft dashboards before deleting it.', 'details': {'dashboards': references}}, 409)
        source = dataset.source_import
        dataset.delete()
        remove_unused_import(source)
        return response({'deleted': True})
    data = body(request)
    if 'name' in data:
        dataset.name = text(data['name'], 'Dataset name', 160, True)
    if 'types' in data:
        if not isinstance(data['types'], dict):
            raise ValueError('Column types must be an object mapping column names to types.')
        names = {c['name'] for c in dataset.profile_data.get('columns', [])}
        for field, kind in data['types'].items():
            if field not in names or kind not in TYPE_NAMES:
                raise ValueError('Select a valid column name and supported column type.')
        dataset.type_overrides = {**dataset.type_overrides, **data['types']}
    if data.get('drop_duplicates') or data.get('drop_empty'):
        dataset.records = clean_rows(dataset.records, data)
    dataset.profile_data = json_safe(profile(dataset.records, dataset.type_overrides))
    dataset.version += 1
    dataset.save()
    return response(dataset_detail(dataset))


@api(['GET'])
def dataset_source(request, dataset_id):
    dataset = owned(Dataset, dataset_id, owner(request))
    if not dataset.source_import:
        raise Http404('The original source file is no longer available.')
    job = dataset.source_import
    return FileResponse(job.source.open('rb'), as_attachment=True, filename=job.filename, content_type='application/octet-stream')


def replace_dataset(dataset, job, data):
    from .analytics import profile
    table, rows = selected_table(job, data)
    new_profile = json_safe(profile(rows, dataset.type_overrides))
    names = {column['name'] for column in new_profile['columns']}
    broken = []
    for dashboard in Dashboard.objects.filter(owner=dataset.owner):
        for widget in dashboard.config.get('widgets', []):
            if str(widget.get('dataset_id')) == str(dataset.id):
                missing = fields_in_spec(widget) - names
                if missing:
                    broken.append({'dashboard': dashboard.title, 'widget': widget.get('title', widget['id']), 'missing_columns': sorted(missing)})
    if broken:
        return response({'error': 'Replacement would break saved widgets. Import it as a new dataset, remap the affected widget fields, and retry.', 'details': broken}, 409)
    old_source = dataset.source_import
    dataset.records = rows
    dataset.profile_data = new_profile
    dataset.source_import = job
    dataset.source_table = str(table['key'])
    dataset.source_type = job.source_type
    dataset.version += 1
    dataset.save()
    if old_source and old_source.id != job.id:
        remove_unused_import(old_source)
    return response(dataset_detail(dataset))


@api(['POST'], category='dataset_changes', limit=30)
def dataset_replace(request, dataset_id):
    workspace_owner = owner(request)
    dataset = owned(Dataset, dataset_id, workspace_owner)
    data = body(request)
    job = owned(ImportJob, data.get('import_id'), workspace_owner)
    return replace_dataset(dataset, job, data)


@api(['POST'], category='imports', limit=20)
def dataset_refresh(request, dataset_id):
    from .ingestion import fetch_sheet, inspect_source
    dataset = owned(Dataset, dataset_id, owner(request))
    source = dataset.source_import
    if not source or source.source_type != 'google_sheets' or not source.source_url:
        raise ValueError('Only Google Sheets connections can be refreshed. Use Replace for local files.')
    filename, content = fetch_sheet(source.source_url)
    result = inspect_source(filename, content)
    job = ImportJob(owner=dataset.owner, filename=filename, source_type='google_sheets', source_url=source.source_url, tables=json_safe(result['tables']), warnings=result.get('warnings', []))
    job.source.save(f'{uuid.uuid4().hex}.csv', ContentFile(content), save=True)
    result = replace_dataset(dataset, job, {'table_key': dataset.source_table})
    if result.status_code != 200:
        remove_unused_import(job)
    return result


@api(['GET'])
def recommendations(request, dataset_id):
    from .analytics import recommend, compatible
    dataset = owned(Dataset, dataset_id, owner(request))
    choices = recommend(dataset.profile_data)
    return response({'recommendations': choices, 'chart_types': compatible(dataset.profile_data), 'kpis': [item for item in choices if item.get('type') == 'kpi']})


@api(['POST'], category='analytics', limit=300)
def analytics_query(request):
    from .analytics import query
    data = body(request)
    dataset = owned(Dataset, data.get('dataset_id'), owner(request))
    return response(query(dataset.records, data, dataset.profile_data))


@api(['POST'], category='analytics', limit=120)
def analytics_export(request):
    from .analytics import query
    data = body(request)
    dataset = owned(Dataset, data.get('dataset_id'), owner(request))
    result = query(dataset.records, data, dataset.profile_data)
    rows = result.get('rows', [])
    if not rows:
        labels = result.get('labels', [])
        series = result.get('series', [])
        rows = [{'label': label, **{s['name']: s['values'][i] if i < len(s['values']) else None for s in series}} for i, label in enumerate(labels)]
    if not rows and result.get('value') is not None:
        rows = [{'metric': data.get('title', data.get('y', 'Value')), 'value': result['value']}]
    download = HttpResponse(csv_bytes(rows), content_type='text/csv; charset=utf-8')
    download['Content-Disposition'] = 'attachment; filename="chart-data.csv"'
    return download


@api(['GET', 'POST'], category='dashboard_changes', limit=120)
def dashboards(request):
    workspace_owner = owner(request)
    if request.method == 'GET':
        return response({'dashboards': [dashboard_detail(d) for d in Dashboard.objects.filter(owner=workspace_owner).order_by('-updated_at')]})
    data = body(request)
    config = data.get('config', {'widgets': [], 'theme': {}, 'grid': {'columns': 12, 'gap': 16, 'rowHeight': 70, 'padding': 24}})
    validate_config(config, workspace_owner)
    dashboard = Dashboard.objects.create(owner=workspace_owner, title=text(data.get('title', 'Untitled dashboard'), 'Dashboard title', 160, True), description=text(data.get('description', ''), 'Description', 4000), config=config)
    return response(dashboard_detail(dashboard), 201)


@api(['GET', 'PATCH', 'DELETE'], category='dashboard_changes', limit=180)
def dashboard_item(request, dashboard_id):
    dashboard = owned(Dashboard, dashboard_id, owner(request))
    if request.method == 'GET':
        return response(dashboard_detail(dashboard))
    if request.method == 'DELETE':
        dashboard.delete()
        return response({'deleted': True})
    data = body(request)
    revision = data.get('revision', dashboard.revision)
    if revision != dashboard.revision:
        raise APIConflict('This dashboard changed in another tab. Reload it before saving to avoid overwriting edits.')
    values = {'updated_at': timezone.now(), 'revision': F('revision') + 1}
    if 'title' in data:
        values['title'] = text(data['title'], 'Dashboard title', 160, True)
    if 'description' in data:
        values['description'] = text(data['description'], 'Description', 4000)
    if 'config' in data:
        validate_config(data['config'], dashboard.owner)
        values['config'] = data['config']
    changed = Dashboard.objects.filter(pk=dashboard.id, revision=revision).update(**values)
    if not changed:
        raise APIConflict('This dashboard changed while saving. Reload and try again.')
    dashboard.refresh_from_db()
    return response(dashboard_detail(dashboard))


@api(['POST'], category='dashboard_changes', limit=60)
def dashboard_duplicate(request, dashboard_id):
    dashboard = owned(Dashboard, dashboard_id, owner(request))
    duplicate = Dashboard.objects.create(owner=dashboard.owner, title=(dashboard.title[:153] + ' (copy)'), description=dashboard.description, config=copy.deepcopy(dashboard.config))
    return response(dashboard_detail(duplicate), 201)


@api(['POST'], category='publishing', limit=30)
def dashboard_publish(request, dashboard_id):
    workspace_owner = owner(request)
    with transaction.atomic():
        dashboard = owned(Dashboard, dashboard_id, workspace_owner)
        dashboard = Dashboard.objects.select_for_update().get(pk=dashboard.pk)
        datasets_by_id = validate_config(dashboard.config, workspace_owner, run_queries=True)
        if not dashboard.config.get('widgets'):
            raise ValueError('Add at least one widget before publishing this dashboard.')
        snapshot_datasets = {key: {'id': key, 'name': dataset.name, 'columns': dataset.profile_data.get('columns', []), 'profile': dataset.profile_data, 'records': copy.deepcopy(dataset.records), 'version': dataset.version} for key, dataset in datasets_by_id.items()}
        version = (dashboard.publications.aggregate(value=Max('version'))['value'] or 0) + 1
        Publication.objects.create(dashboard=dashboard, version=version, title=dashboard.title, description=dashboard.description, config=copy.deepcopy(dashboard.config), datasets=snapshot_datasets)
        if not dashboard.slug:
            base = slugify(dashboard.title)[:150] or 'dashboard'
            candidate = base
            while Dashboard.objects.filter(slug=candidate).exclude(pk=dashboard.id).exists():
                candidate = f'{base}-{secrets.token_hex(3)}'
            dashboard.slug = candidate
        dashboard.active_version = version
        dashboard.published_at = timezone.now()
        dashboard.save(update_fields=['slug', 'active_version', 'published_at', 'updated_at'])
    return response({'slug': dashboard.slug, 'url': f'/dashboards/{dashboard.slug}/', 'version': version})


@api(['POST'], category='publishing', limit=30)
def dashboard_unpublish(request, dashboard_id):
    dashboard = owned(Dashboard, dashboard_id, owner(request))
    dashboard.active_version = 0
    dashboard.save(update_fields=['active_version', 'updated_at'])
    return response({'unpublished': True})


def active_publication(slug):
    try:
        dashboard = Dashboard.objects.get(slug=slug, active_version__gt=0)
        return dashboard, Publication.objects.get(dashboard=dashboard, version=dashboard.active_version)
    except (Dashboard.DoesNotExist, Publication.DoesNotExist):
        raise Http404('This dashboard is not published or no longer available.')


def public_fields(publication, dataset_id):
    fields = set()
    for widget in publication.config.get('widgets', []):
        if str(widget.get('dataset_id')) != str(dataset_id):
            continue
        if widget.get('type') == 'table' and not widget.get('columns'):
            fields.update(c['name'] for c in publication.datasets[str(dataset_id)]['columns'][:12])
        if widget.get('type') == 'heatmap' and not widget.get('measures'):
            fields.update(c['name'] for c in publication.datasets[str(dataset_id)]['columns'] if c['type'] in {'numeric', 'currency', 'percentage', 'ordinal'})
        fields.update(fields_in_spec(widget))
    return fields


def public_metadata(dashboard, publication, *, include_datasets=False):
    data = {'title': publication.title, 'description': publication.description, 'slug': dashboard.slug, 'published_at': publication.created_at.isoformat(), 'updated_at': publication.created_at.isoformat(), 'config': publication.config, 'version': publication.version}
    if include_datasets:
        data['datasets'] = [{'id': dataset_id, 'name': dataset['name'], 'columns': [{'name': column['name'], 'type': column['type'], 'categories': [{'value': item['value']} for item in column.get('categories', [])]} for column in dataset['columns'] if column['name'] in public_fields(publication, dataset_id)]} for dataset_id, dataset in publication.datasets.items()]
    return data


@api(['GET'])
def published(request):
    search = request.GET.get('search', '')[:200].casefold()
    sort = request.GET.get('sort', 'newest')
    result = []
    for dashboard in Dashboard.objects.filter(active_version__gt=0).select_related():
        publication = dashboard.publications.filter(version=dashboard.active_version).first()
        if publication and (not search or search in publication.title.casefold() or search in publication.description.casefold()):
            result.append(public_metadata(dashboard, publication))
    result.sort(key=lambda d: d['title'].casefold() if sort == 'name' else d['published_at'], reverse=sort != 'name')
    return response({'dashboards': result})


@api(['GET'])
def published_item(request, slug):
    dashboard, publication = active_publication(slug)
    return response(public_metadata(dashboard, publication, include_datasets=True))


@api(['POST'], category='public_analytics', limit=300)
def published_query(request, slug):
    from .analytics import query
    dashboard, publication = active_publication(slug)
    data = body(request)
    if set(data) - {'widget_id', 'filters'}:
        raise ValueError('Public queries accept only a saved widget ID and filter selections.')
    widget = next((w for w in publication.config.get('widgets', []) if w.get('id') == data.get('widget_id')), None)
    if not widget or widget.get('type') in SPECIAL_WIDGETS:
        raise ValueError('Choose a saved analytical widget from this dashboard.')
    dataset_id = str(widget.get('dataset_id'))
    dataset = publication.datasets.get(dataset_id)
    if not dataset:
        raise ValueError('This widget has no published dataset.')
    allowed = public_fields(publication, dataset_id)
    selections = data.get('filters', [])
    if not isinstance(selections, (list, dict)):
        raise ValueError('Filters must be a list or a logical filter group.')
    if fields_in_spec({'filters': selections}) - allowed:
        raise ValueError('Filters may use only fields exposed by this published dashboard.')
    spec = copy.deepcopy(widget)
    original = spec.get('filters', [])
    if isinstance(original, list) and original:
        original = {'logic': spec.get('filter_logic', 'and'), 'conditions': original}
        spec['filters'] = original
    if selections:
        runtime = {'logic': 'and', 'conditions': selections} if isinstance(selections, list) else selections
        spec['filters'] = {'logic': 'and', 'conditions': [original, runtime]} if original else runtime
    # Project before querying: analytical response rows cannot expose unrelated source fields.
    rows = [{key: value for key, value in row.items() if key in allowed} for row in dataset['records']]
    schema = {**dataset['profile'], 'columns': [c for c in dataset['columns'] if c['name'] in allowed]}
    return response(query(rows, spec, schema))


def hierarchy_options(records, fields, available):
    if not isinstance(fields, list) or not 1 <= len(fields) <= 3 or any(not isinstance(field, str) or field not in available for field in fields) or len(set(fields)) != len(fields):
        raise ValueError('Choose one to three distinct dataset fields for the hierarchy.')
    paths, seen, truncated = [], set(), False
    for record in records:
        values = [record.get(field) for field in fields]
        if any(isinstance(value, (dict, list)) for value in values):
            raise ValueError('Hierarchy levels require scalar category values. Choose normalized tabular fields.')
        marker = json.dumps(values, sort_keys=True, ensure_ascii=False)
        if marker not in seen:
            if len(paths) >= 1000:
                truncated = True
                break
            seen.add(marker)
            paths.append(values)
    return {'fields': fields, 'paths': paths, 'truncated': truncated}


@api(['POST'], category='analytics', limit=180)
def dataset_filter_options(request, dataset_id):
    dataset = owned(Dataset, dataset_id, owner(request))
    data = body(request)
    return response(hierarchy_options(dataset.records, data.get('fields'), {column['name'] for column in dataset.profile_data['columns']}))


@api(['POST'], category='public_analytics', limit=300)
def published_filter_options(request, slug):
    dashboard, publication = active_publication(slug)
    data = body(request)
    if set(data) != {'widget_id'}:
        raise ValueError('Public hierarchy options accept only a saved filter widget ID.')
    widget = next((widget for widget in publication.config.get('widgets', []) if widget.get('id') == data['widget_id']), None)
    if not widget or widget.get('type') != 'filter' or widget.get('control') != 'hierarchy':
        raise ValueError('Choose a saved hierarchical filter from this dashboard.')
    dataset = publication.datasets.get(str(widget.get('dataset_id')))
    if not dataset:
        raise ValueError('The filter has no published dataset.')
    fields = [widget['filter']['field'], *widget.get('hierarchy_fields', [])]
    return response(hierarchy_options(dataset['records'], fields, {column['name'] for column in dataset['columns']}))


@ensure_csrf_cookie
def app_shell(request, path=''):
    if path.startswith(('api/', 'private-media/')):
        return response({'error': 'Not found.'}, 404)
    index = settings.FRONTEND_DIST / 'index.html'
    if index.is_file():
        return FileResponse(index.open('rb'), content_type='text/html')
    return HttpResponse('Prism frontend has not been built. Run npm install and npm run build in frontend/, or use the Vite development server.', status=503, content_type='text/plain')
