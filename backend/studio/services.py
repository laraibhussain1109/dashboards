"""Validation and serialization shared by editing and publishing endpoints."""
import ast
import copy
import csv
import io
import json
import math
import re
from datetime import date, datetime
from django.core.exceptions import PermissionDenied
from django.http import Http404
from .models import Dashboard, Dataset, ImportJob

SPECIAL_WIDGETS = {'text', 'filter', 'image', 'shape', 'divider'}
MAX_WIDGETS = 80
TYPE_NAMES = {'numeric', 'number', 'categorical', 'category', 'date', 'datetime', 'time', 'boolean', 'currency', 'percentage', 'geographic', 'identifier', 'ordinal', 'text'}


def json_safe(value):
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(v) for v in value]
    # Handle NumPy scalar values returned by analytical operations.
    if hasattr(value, 'item'):
        return json_safe(value.item())
    return value


def owned(model, object_id, owner):
    try:
        obj = model.objects.get(pk=object_id)
    except (model.DoesNotExist, ValueError, TypeError):
        raise Http404('The requested item does not exist.')
    if obj.owner != owner:
        raise PermissionDenied('This item belongs to another private workspace.')
    return obj


def text(value, field, maximum=160, required=False):
    if not isinstance(value, str):
        raise ValueError(f'{field} must be text.')
    value = value.strip()
    if required and not value:
        raise ValueError(f'{field} is required.')
    if len(value) > maximum:
        raise ValueError(f'{field} may contain at most {maximum} characters.')
    return value


def positive_int(value, field, minimum=1, maximum=100000):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or int(value) != value or not minimum <= value <= maximum:
        raise ValueError(f'{field} must be a whole number between {minimum} and {maximum}.')
    return int(value)


def fields_in_spec(spec):
    fields = set()
    for key in ('x', 'y', 'series', 'z', 'size', 'target_field', 'denominator', 'date', 'start', 'end', 'label', 'lower', 'upper'):
        value = spec.get(key)
        if isinstance(value, str) and value:
            fields.add(value)
        elif isinstance(value, list):
            fields.update(v for v in value if isinstance(v, str))
    for key in ('dimensions', 'measures', 'columns', 'hierarchy_fields'):
        values = spec.get(key, [])
        if isinstance(values, list):
            fields.update(v for v in values if isinstance(v, str))
    formula = spec.get('formula', '')
    if isinstance(formula, str):
        fields.update(re.findall(r'\[([^\]]+)\]', formula))
        fields.update(re.findall(r'\b(?:SUM|AVG|AVERAGE|COUNT|MIN|MAX|MEDIAN|DISTINCT_COUNT)\(\s*([A-Za-z_]\w*)\s*\)', formula, re.I))
        # Bare identifiers are also legal aggregate metric references.
        expression = formula.split('=', 1)[-1]
        functions = {'SUM', 'AVG', 'AVERAGE', 'COUNT', 'MIN', 'MAX', 'MEDIAN', 'DISTINCT_COUNT', 'ABS', 'ROUND'}
        try:
            tree = ast.parse(re.sub(r'\[[^\]]+\]', '0', expression), mode='eval')
            fields.update(node.id for node in ast.walk(tree) if isinstance(node, ast.Name) and node.id.upper() not in functions)
        except (SyntaxError, ValueError, RecursionError):
            # The query engine reports complete formula validation on publication.
            pass
    def scan(filters):
        if isinstance(filters, dict):
            if isinstance(filters.get('field'), str):
                fields.add(filters['field'])
            for c in filters.get('conditions', []):
                scan(c)
        elif isinstance(filters, list):
            for c in filters:
                scan(c)
    scan(spec.get('filters', []))
    scan(spec.get('filter', {}))
    scan(spec.get('condition', []))
    calculated = spec.get('calculated_fields', [])
    if isinstance(calculated, dict):
        calculated = [{'name': name, 'formula': value} for name, value in calculated.items()]
    calculated_names = set()
    if isinstance(calculated, list):
        for item in calculated:
            if isinstance(item, dict):
                if isinstance(item.get('name'), str):
                    calculated_names.add(item['name'])
                fields.update(fields_in_spec({'formula': item.get('formula', '')}))
    return fields - calculated_names


def chart_types():
    from .analytics import CHART_TYPES
    if isinstance(CHART_TYPES, dict):
        return [{'id': key, **value} if isinstance(value, dict) else {'id': key, 'name': str(value)} for key, value in CHART_TYPES.items()]
    return [dict(item) if isinstance(item, dict) else {'id': item, 'name': str(item).replace('_', ' ').title(), 'group': 'Charts'} for item in CHART_TYPES]


def validate_config(config, owner, *, run_queries=False):
    from .analytics import query
    if not isinstance(config, dict):
        raise ValueError('Dashboard configuration must be an object.')
    if len(json.dumps(config)) > 4 * 1024 * 1024:
        raise ValueError('Dashboard configuration exceeds the 4 MB limit.')
    widgets = config.get('widgets', [])
    if not isinstance(widgets, list) or len(widgets) > MAX_WIDGETS:
        raise ValueError(f'A dashboard supports at most {MAX_WIDGETS} widgets.')
    valid_types = {item['id'] for item in chart_types()} | SPECIAL_WIDGETS | {'kpi', 'table'}
    ids, datasets = set(), {}
    grid = config.get('grid', {})
    if not isinstance(grid, dict):
        raise ValueError('Grid settings must be an object.')
    columns = positive_int(grid.get('columns', 12), 'Grid columns', 1, 48)
    for key, default, low, high in [('gap', 16, 0, 80), ('rowHeight', 70, 20, 300), ('padding', 24, 0, 100)]:
        positive_int(grid.get(key, default), f'Grid {key}', low, high)
    if not isinstance(config.get('theme', {}), dict):
        raise ValueError('Theme settings must be an object.')
    for widget in widgets:
        if not isinstance(widget, dict):
            raise ValueError('Each widget must be an object.')
        widget_id = widget.get('id')
        if not isinstance(widget_id, str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}', widget_id) or widget_id in ids:
            raise ValueError('Every widget needs a unique valid ID.')
        ids.add(widget_id)
        widget_type = widget.get('type')
        if widget_type not in valid_types:
            raise ValueError(f'Unsupported widget type: {widget_type}.')
        text(widget.get('title', ''), 'Widget title', 300)
        if 'text' in widget:
            text(widget['text'], 'Widget text', 20000)
        if widget_type == 'image':
            image = widget.get('image', '')
            # Keep incomplete elements in drafts; a publication must render them.
            if image in ('', None) and not run_queries:
                pass
            elif not isinstance(image, str) or len(image) > 3 * 1024 * 1024 or not (image.startswith('https://') or re.match(r'^data:image/(?:png|jpeg|webp|gif);base64,', image)):
                raise ValueError('Choose an image before publishing. Images must use HTTPS or a PNG/JPEG/WebP/GIF data URL; SVG and scripts are not allowed.')
        layout = widget.get('layout', {})
        if not isinstance(layout, dict):
            raise ValueError('Widget layout must be an object.')
        x = positive_int(layout.get('x', 0), 'Widget x', 0, columns - 1)
        width = positive_int(layout.get('w', min(6, columns)), 'Widget width', 1, columns)
        if x + width > columns:
            raise ValueError('Widget layout extends beyond the canvas grid.')
        positive_int(layout.get('y', 0), 'Widget y', 0, 10000)
        positive_int(layout.get('h', 4), 'Widget height', 1, 100)
        dataset_id = widget.get('dataset_id')
        if widget_type not in SPECIAL_WIDGETS or widget_type == 'filter':
            if not dataset_id:
                raise ValueError(f'{widget.get("title") or widget_type} needs a dataset.')
        if dataset_id:
            dataset_id = str(dataset_id)
            if dataset_id not in datasets:
                datasets[dataset_id] = owned(Dataset, dataset_id, owner)
            dataset = datasets[dataset_id]
            names = {c['name'] for c in dataset.profile_data.get('columns', [])}
            missing = fields_in_spec(widget) - names
            if missing:
                raise ValueError('Referenced columns are missing: ' + ', '.join(sorted(missing)))
            if run_queries and widget_type not in SPECIAL_WIDGETS:
                query(dataset.records, widget, dataset.profile_data)
            if widget_type == 'filter':
                definition = widget.get('filter', {})
                if not isinstance(definition, dict) or not definition.get('field'):
                    raise ValueError('Filter widgets require a field.')
                if widget.get('control') == 'hierarchy':
                    levels = widget.get('hierarchy_fields', [])
                    if not isinstance(levels, list) or len(levels) > 2 or any(not isinstance(level, str) for level in levels):
                        raise ValueError('A hierarchy supports a parent and at most two child fields.')
                    if len(set([definition['field'], *levels])) != 1 + len(levels):
                        raise ValueError('Hierarchy levels must use distinct fields.')
                    if run_queries and not levels:
                        raise ValueError('Choose at least one child field for the hierarchy filter before publishing.')
                # Validate filter operators and value types using the same engine.
                if definition.get('value') not in (None, '', []):
                    query(dataset.records, {'type': 'table', 'filters': [dict(definition)]}, dataset.profile_data)
                else:
                    # A filter without a default is valid; still validate its field/operator.
                    query([], {'type': 'table', 'filters': [dict(definition)]}, dataset.profile_data)
    for widget in widgets:
        targets = (widget.get('filter') or {}).get('targets', []) if isinstance(widget.get('filter', {}), dict) else []
        if not isinstance(targets, list) or any(target not in ids for target in targets):
            raise ValueError('Filter targets must refer to existing widgets.')
    return datasets


def dataset_summary(dataset):
    return {'id': str(dataset.id), 'name': dataset.name, 'source_type': dataset.source_type, 'row_count': len(dataset.records), 'column_count': len(dataset.profile_data.get('columns', [])), 'version': dataset.version, 'created_at': dataset.created_at.isoformat(), 'updated_at': dataset.updated_at.isoformat()}


def dataset_detail(dataset, *, page=1, page_size=50, search='', sort='', direction='asc'):
    rows = dataset.records
    if search:
        needle = search.casefold()
        rows = [r for r in rows if any(needle in str(v).casefold() for v in r.values())]
    if sort:
        names = {c['name'] for c in dataset.profile_data.get('columns', [])}
        if sort not in names:
            raise ValueError('Sort column does not exist.')
        from .analytics import NUMERIC_TYPES, DATE_TYPES, date_value, missing, number
        kind = next(c['type'] for c in dataset.profile_data['columns'] if c['name'] == sort)
        parser = number if kind in NUMERIC_TYPES else date_value if kind in DATE_TYPES else lambda value: str(value).casefold()
        usable, invalid, empty = [], [], []
        for row in rows:
            value = row.get(sort)
            if missing(value):
                empty.append(row)
            elif (parsed := parser(value)) is None:
                invalid.append(row)
            else:
                usable.append((parsed, row))
        # Invalid and empty values stay at the end in either direction. IDs retain
        # their lexical identity; declared measures and dates use typed ordering.
        rows = [row for value, row in sorted(usable, key=lambda pair: pair[0], reverse=direction == 'desc')]
        rows += sorted(invalid, key=lambda row: str(row.get(sort)).casefold()) + empty
    total_pages = max(1, math.ceil(len(rows) / page_size))
    page = min(page, total_pages)
    return {**dataset_summary(dataset), 'columns': dataset.profile_data.get('columns', []), 'profile': dataset.profile_data, 'preview': rows[(page - 1) * page_size:page * page_size], 'page': page, 'page_size': page_size, 'total_pages': total_pages, 'filtered_rows': len(rows)}


def dashboard_detail(dashboard):
    return {'id': str(dashboard.id), 'title': dashboard.title, 'description': dashboard.description, 'config': dashboard.config, 'revision': dashboard.revision, 'published_slug': dashboard.slug if dashboard.active_version else None, 'published_at': dashboard.published_at.isoformat() if dashboard.active_version and dashboard.published_at else None, 'created_at': dashboard.created_at.isoformat(), 'updated_at': dashboard.updated_at.isoformat()}


def clean_rows(rows, options):
    if options.get('drop_empty'):
        rows = [r for r in rows if any(value is not None and value != '' for value in r.values())]
    if options.get('drop_duplicates'):
        seen, unique = set(), []
        for row in rows:
            marker = json.dumps(row, sort_keys=True, default=str)
            if marker not in seen:
                seen.add(marker)
                unique.append(row)
        rows = unique
    if not rows:
        raise ValueError('The selected table contains no records after applying import options.')
    return rows


def csv_bytes(rows, columns=None):
    columns = columns or list(rows[0]) if rows else columns or []
    output = io.StringIO(newline='')
    writer = csv.writer(output)
    def safe(value):
        if isinstance(value, str) and value.lstrip().startswith(('=', '+', '-', '@', '\t', '\r')):
            return "'" + value
        return '' if value is None else value
    writer.writerow([safe(c) for c in columns])
    for row in rows:
        writer.writerow([safe(row.get(column)) for column in columns])
    return ('\ufeff' + output.getvalue()).encode('utf-8')


def remove_unused_import(source):
    if source and not source.datasets.exists():
        source.source.delete(save=False)
        source.delete()
