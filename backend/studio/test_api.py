"""Integration and access-control regression tests through the actual JSON API."""
import copy
import io
import json
import tempfile
from pathlib import Path
from unittest.mock import patch
from django.core.cache import cache
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from .models import Dataset, Publication


class StudioAPITests(TestCase):
    def setUp(self):
        cache.clear()
        self.storage = tempfile.TemporaryDirectory()
        self.media_override = override_settings(MEDIA_ROOT=self.storage.name)
        self.media_override.enable()
        self.addCleanup(self.media_override.disable)
        self.addCleanup(self.storage.cleanup)
        self.client = Client(enforce_csrf_checks=True)
        result = self.client.get('/api/workspace/')
        self.assertEqual(result.status_code, 200)
        self.csrf = self.client.cookies['csrftoken'].value

    def call(self, path, data=None, method='post', client=None, csrf=True):
        client = client or self.client
        headers = {'HTTP_X_CSRFTOKEN': client.cookies['csrftoken'].value} if csrf and 'csrftoken' in client.cookies else {}
        return getattr(client, method)(path, data=json.dumps(data or {}), content_type='application/json', **headers)

    def import_csv(self, contents=None, client=None):
        client = client or self.client
        contents = contents or b'Date,Region,Revenue,Cost,Customer Secret\n2025-01-01,North,100,40,private-a\n2025-01-02,South,200,100,private-b\n2025-02-01,North,300,150,private-c\n'
        uploaded = SimpleUploadedFile('sales.csv', contents, content_type='text/csv')
        result = client.post('/api/imports/', {'file': uploaded}, HTTP_X_CSRFTOKEN=client.cookies['csrftoken'].value)
        self.assertEqual(result.status_code, 201, result.content)
        return result.json()

    def create_dataset(self, contents=None):
        imported = self.import_csv(contents)
        result = self.call('/api/datasets/', {'import_id': imported['id'], 'table_key': imported['tables'][0]['key'], 'name': 'Quarterly sales'})
        self.assertEqual(result.status_code, 201, result.content)
        return result.json()

    def create_dashboard(self, dataset):
        config = {'widgets': [
            {'id': 'revenue', 'type': 'kpi', 'title': 'Total revenue', 'dataset_id': dataset['id'], 'y': 'Revenue', 'aggregation': 'sum', 'layout': {'x': 0, 'y': 0, 'w': 4, 'h': 2}},
            {'id': 'region', 'type': 'bar', 'title': 'Revenue by region', 'dataset_id': dataset['id'], 'x': 'Region', 'y': 'Revenue', 'aggregation': 'sum', 'layout': {'x': 0, 'y': 2, 'w': 8, 'h': 4}},
            {'id': 'datefilter', 'type': 'filter', 'title': 'Region', 'dataset_id': dataset['id'], 'filter': {'field': 'Region', 'op': 'eq', 'value': 'North', 'targets': []}, 'layout': {'x': 8, 'y': 2, 'w': 4, 'h': 2}},
        ], 'theme': {'mode': 'light', 'accent': '#4169e1'}, 'grid': {'columns': 12, 'gap': 16, 'rowHeight': 70, 'padding': 24}}
        result = self.call('/api/dashboards/', {'title': 'Sales performance', 'description': 'Actual uploaded sales', 'config': config})
        self.assertEqual(result.status_code, 201, result.content)
        return result.json()

    def test_excel_multiple_worksheet_import_and_preview(self):
        import openpyxl
        workbook = openpyxl.Workbook()
        sheet = workbook.active
        sheet.title = 'Sales'
        sheet.append(['Region', 'Revenue'])
        sheet.append(['West', 125])
        sheet = workbook.create_sheet('Inventory')
        sheet.append(['Product', 'Units'])
        sheet.append(['Desk', 7])
        content = io.BytesIO()
        workbook.save(content)
        result = self.client.post('/api/imports/', {'file': SimpleUploadedFile('book.xlsx', content.getvalue())}, HTTP_X_CSRFTOKEN=self.csrf)
        self.assertEqual(result.status_code, 201, result.content)
        tables = result.json()['tables']
        self.assertEqual(len(tables), 2)
        self.assertEqual([table['name'] for table in tables], ['Sales', 'Inventory'])
        self.assertEqual(tables[0]['preview'][0]['Revenue'], 125)

    def test_complete_upload_analytics_save_publish_republish(self):
        dataset = self.create_dataset()
        self.assertEqual(dataset['row_count'], 3)
        self.assertEqual({column['name'] for column in dataset['columns']}, {'Date', 'Region', 'Revenue', 'Cost', 'Customer Secret'})
        recommended = self.client.get(f'/api/datasets/{dataset["id"]}/recommendations/')
        self.assertEqual(recommended.status_code, 200)
        self.assertTrue(recommended.json()['recommendations'])
        metric = self.call('/api/analytics/query/', {'dataset_id': dataset['id'], 'type': 'kpi', 'y': 'Revenue', 'aggregation': 'sum'})
        self.assertEqual(metric.status_code, 200, metric.content)
        self.assertEqual(metric.json()['value'], 600)
        formula = self.call('/api/analytics/query/', {'dataset_id': dataset['id'], 'type': 'kpi', 'formula': 'SUM(Revenue) - SUM(Cost)'})
        self.assertEqual(formula.status_code, 200, formula.content)
        self.assertEqual(formula.json()['value'], 310)
        dashboard = self.create_dashboard(dataset)
        self.assertEqual(self.client.get('/api/published/').json()['dashboards'], [])
        url = f'/api/dashboards/{dashboard["id"]}/'
        saved = self.call(url, {'revision': 1, 'title': 'Updated sales', 'config': dashboard['config']}, 'patch')
        self.assertEqual(saved.status_code, 200, saved.content)
        self.assertEqual(saved.json()['revision'], 2)
        self.assertEqual(self.client.get(url).json()['config'], dashboard['config'])
        self.assertEqual(self.call(url, {'revision': 1, 'title': 'Stale title'}, 'patch').status_code, 409)
        publication = self.call(url + 'publish/').json()
        self.assertEqual(publication['version'], 1)
        slug = publication['slug']
        public = Client(enforce_csrf_checks=True)
        public.get('/api/workspace/')
        metadata = public.get(f'/api/published/{slug}/')
        self.assertEqual(metadata.status_code, 200)
        self.assertNotIn('owner', metadata.json())
        self.assertNotIn('records', metadata.content.decode())
        self.assertNotIn('Customer Secret', metadata.content.decode())
        metric = self.call(f'/api/published/{slug}/query/', {'widget_id': 'revenue'}, client=public)
        self.assertEqual(metric.status_code, 200, metric.content)
        self.assertEqual(metric.json()['value'], 600)
        selected = self.call(f'/api/published/{slug}/query/', {'widget_id': 'revenue', 'filters': [{'field': 'Region', 'op': 'eq', 'value': 'North'}]}, client=public)
        self.assertEqual(selected.json()['value'], 400)
        modified = copy.deepcopy(dashboard['config'])
        modified['widgets'][0]['y'] = 'Cost'
        self.assertEqual(self.call(url, {'revision': 2, 'config': modified}, 'patch').status_code, 200)
        # Draft edits do not affect the active publication.
        self.assertEqual(self.call(f'/api/published/{slug}/query/', {'widget_id': 'revenue'}, client=public).json()['value'], 600)
        second = self.call(url + 'publish/').json()
        self.assertEqual(second['slug'], slug)
        self.assertEqual(second['version'], 2)
        self.assertEqual(self.call(f'/api/published/{slug}/query/', {'widget_id': 'revenue'}, client=public).json()['value'], 290)
        self.assertEqual(Publication.objects.count(), 2)
        self.assertEqual(self.call(url + 'unpublish/').status_code, 200)
        self.assertEqual(public.get(f'/api/published/{slug}/').status_code, 404)

    def test_foreign_session_cannot_read_edit_or_query_private_objects(self):
        dataset = self.create_dataset()
        dashboard = self.create_dashboard(dataset)
        other = Client(enforce_csrf_checks=True)
        other.get('/api/workspace/')
        self.assertEqual(other.get('/api/workspace/').json()['datasets'], [])
        self.assertEqual(other.get(f'/api/datasets/{dataset["id"]}/').status_code, 403)
        self.assertEqual(other.get(f'/api/datasets/{dataset["id"]}/source/').status_code, 403)
        self.assertEqual(other.get(f'/api/dashboards/{dashboard["id"]}/').status_code, 403)
        self.assertEqual(self.call('/api/analytics/query/', {'dataset_id': dataset['id'], 'type': 'table'}, client=other).status_code, 403)
        for action in ['publish/', 'unpublish/', 'duplicate/']:
            self.assertEqual(self.call(f'/api/dashboards/{dashboard["id"]}/{action}', client=other).status_code, 403)
        self.assertEqual(self.call(f'/api/dashboards/{dashboard["id"]}/', {}, 'delete', client=other).status_code, 403)
        foreign_config = copy.deepcopy(dashboard['config'])
        self.assertEqual(self.call('/api/dashboards/', {'title': 'Foreign', 'config': foreign_config}, client=other).status_code, 403)

    def test_csrf_is_required_for_privileged_requests(self):
        result = self.call('/api/dashboards/', {'title': 'No CSRF'}, csrf=False)
        self.assertEqual(result.status_code, 403)
        self.assertIn('security cookie', result.json()['error'])
        self.assertFalse(self.client.cookies['sessionid']['httponly'] is False)

    def test_public_queries_cannot_change_widget_or_access_hidden_fields(self):
        dataset = self.create_dataset()
        dashboard = self.create_dashboard(dataset)
        slug = self.call(f'/api/dashboards/{dashboard["id"]}/publish/').json()['slug']
        path = f'/api/published/{slug}/query/'
        self.assertEqual(self.call(path, {'widget_id': 'revenue', 'dataset_id': dataset['id']}).status_code, 400)
        self.assertEqual(self.call(path, {'widget_id': 'revenue', 'filters': [{'field': 'Customer Secret', 'op': 'eq', 'value': 'private-a'}]}).status_code, 400)
        self.assertEqual(self.call(path, {'widget_id': 'missing'}).status_code, 400)
        self.assertEqual(self.call(path, {'widget_id': 'datefilter'}).status_code, 400)
        result = self.call(path, {'widget_id': 'region'})
        self.assertNotIn('private-a', result.content.decode())

    def test_invalid_config_formula_upload_and_request_errors(self):
        dataset = self.create_dataset()
        dashboard = self.create_dashboard(dataset)
        modified = copy.deepcopy(dashboard['config'])
        modified['widgets'][0]['formula'] = '__import__("os").system("id")'
        saved = self.call(f'/api/dashboards/{dashboard["id"]}/', {'revision': 1, 'config': modified}, 'patch')
        self.assertEqual(saved.status_code, 400)
        modified['widgets'][0]['formula'] = '1 +'
        self.assertEqual(self.call(f'/api/dashboards/{dashboard["id"]}/', {'revision': 1, 'config': modified}, 'patch').status_code, 200)
        self.assertEqual(self.call(f'/api/dashboards/{dashboard["id"]}/publish/').status_code, 400)
        invalid = self.call('/api/analytics/query/', {'dataset_id': dataset['id'], 'type': 'bar', 'x': 'Missing', 'y': 'Revenue'})
        self.assertEqual(invalid.status_code, 400)
        bad = self.client.post('/api/imports/', {'file': SimpleUploadedFile('payload.exe', b'MZbad')}, HTTP_X_CSRFTOKEN=self.csrf)
        self.assertEqual(bad.status_code, 400)
        malformed = self.client.post('/api/dashboards/', data='[invalid', content_type='application/json', HTTP_X_CSRFTOKEN=self.csrf)
        self.assertEqual(malformed.status_code, 400)
        self.assertEqual(self.call('/api/dashboards/', {'config': {'widgets': [{'id': 'x', 'type': 'image', 'image': 'javascript:alert(1)'}]}}).status_code, 400)
        self.assertEqual(self.client.get('/private-media/secrets.csv').status_code, 404)
        self.assertEqual(self.client.get('/api/missing/').status_code, 404)

    def test_replacement_detects_missing_fields_and_preserves_snapshot(self):
        dataset = self.create_dataset()
        dashboard = self.create_dashboard(dataset)
        publication = self.call(f'/api/dashboards/{dashboard["id"]}/publish/').json()
        invalid = self.import_csv(b'Region,Cost\nNorth,50\n')
        result = self.call(f'/api/datasets/{dataset["id"]}/replace/', {'import_id': invalid['id'], 'table_key': invalid['tables'][0]['key']})
        self.assertEqual(result.status_code, 409)
        self.assertEqual(Dataset.objects.get(pk=dataset['id']).version, 1)
        valid = self.import_csv(b'Date,Region,Revenue,Cost,Customer Secret\n2025-01-01,North,999,10,private-new\n')
        result = self.call(f'/api/datasets/{dataset["id"]}/replace/', {'import_id': valid['id'], 'table_key': valid['tables'][0]['key']})
        self.assertEqual(result.status_code, 200, result.content)
        self.assertEqual(result.json()['version'], 2)
        self.assertEqual(self.call(f'/api/published/{publication["slug"]}/query/', {'widget_id': 'revenue'}).json()['value'], 600)
        self.assertEqual(self.call(f'/api/datasets/{dataset["id"]}/', {}, 'delete').status_code, 409)

    def test_export_uses_real_filtered_data_and_prevents_formula_injection(self):
        dataset = self.create_dataset(b'Category,Amount\n=HYPERLINK("bad"),25\nSafe,75\n')
        result = self.call('/api/analytics/export/', {'dataset_id': dataset['id'], 'type': 'table', 'columns': ['Category', 'Amount']})
        self.assertEqual(result.status_code, 200, result.content)
        self.assertIn(b"'=HYPERLINK", result.content)
        self.assertIn(b'75', result.content)

    def test_duplicate_unpublished_dashboard_and_authorized_delete(self):
        dataset = self.create_dataset()
        dashboard = self.create_dashboard(dataset)
        result = self.call(f'/api/dashboards/{dashboard["id"]}/duplicate/')
        self.assertEqual(result.status_code, 201, result.content)
        duplicate = result.json()
        self.assertNotEqual(duplicate['id'], dashboard['id'])
        self.assertIsNone(duplicate['published_slug'])
        self.assertEqual(duplicate['config'], dashboard['config'])
        self.assertEqual(self.call(f'/api/dashboards/{duplicate["id"]}/', {}, 'delete').status_code, 200)

    def test_public_sheet_failure_is_a_clear_validation_error(self):
        with patch('studio.ingestion.fetch_sheet', side_effect=ValueError('This Google Sheet is private or unavailable. Share it publicly or configure server credentials.')):
            result = self.call('/api/imports/', {'sheets_url': 'https://docs.google.com/spreadsheets/d/abcd/edit'})
        self.assertEqual(result.status_code, 400)
        self.assertIn('private', result.json()['error'])

    def test_default_empty_range_filter_and_calculated_field_publish(self):
        dataset = self.create_dataset()
        dashboard = self.create_dashboard(dataset)
        config = copy.deepcopy(dashboard['config'])
        config['widgets'][0].update(y='Margin', calculated_fields=[{'name': 'Margin', 'formula': '[Revenue] - [Cost]'}])
        config['widgets'][2].update(filter={'field': 'Date', 'op': 'between', 'value': None}, control='date_range')
        path = f'/api/dashboards/{dashboard["id"]}/'
        saved = self.call(path, {'revision': 1, 'config': config}, 'patch')
        self.assertEqual(saved.status_code, 200, saved.content)
        publication = self.call(path + 'publish/')
        self.assertEqual(publication.status_code, 200, publication.content)
        result = self.call(f'/api/published/{publication.json()["slug"]}/query/', {'widget_id': 'revenue'})
        self.assertEqual(result.status_code, 200, result.content)
        self.assertEqual(result.json()['value'], 310)

    def test_public_saved_or_filters_keep_their_semantics(self):
        dataset = self.create_dataset()
        dashboard = self.create_dashboard(dataset)
        config = copy.deepcopy(dashboard['config'])
        config['widgets'][0].update(filters=[{'field': 'Region', 'op': 'eq', 'value': 'North'}, {'field': 'Revenue', 'op': 'gte', 'value': 200}], filter_logic='or')
        path = f'/api/dashboards/{dashboard["id"]}/'
        self.assertEqual(self.call(path, {'revision': 1, 'config': config}, 'patch').status_code, 200)
        publication = self.call(path + 'publish/').json()
        result = self.call(f'/api/published/{publication["slug"]}/query/', {'widget_id': 'revenue'})
        self.assertEqual(result.status_code, 200, result.content)
        self.assertEqual(result.json()['value'], 600)
        # Runtime filters combine with fixed OR conditions using AND.
        selected = self.call(f'/api/published/{publication["slug"]}/query/', {'widget_id': 'revenue', 'filters': [{'field': 'Region', 'op': 'eq', 'value': 'North'}]})
        self.assertEqual(selected.json()['value'], 400)

    def test_scientific_formula_and_mixed_column_sort(self):
        dataset = self.create_dataset(b'Category,Amount\nNorth,10\nSouth,not-numeric\nWest,30\n')
        result = self.client.get(f'/api/datasets/{dataset["id"]}/?sort=Amount')
        self.assertEqual(result.status_code, 200, result.content)
        dashboard = self.create_dashboard(self.create_dataset())
        config = copy.deepcopy(dashboard['config'])
        config['widgets'][0]['formula'] = 'SUM(Revenue) / 1e3'
        result = self.call(f'/api/dashboards/{dashboard["id"]}/', {'revision': 1, 'config': config}, 'patch')
        self.assertEqual(result.status_code, 200, result.content)

    def test_incomplete_image_draft_saves_but_cannot_publish(self):
        created = self.call('/api/dashboards/', {'title': 'Image draft', 'config': {'widgets': [{'id': 'logo', 'type': 'image', 'title': 'Company logo', 'layout': {'x': 0, 'y': 0, 'w': 4, 'h': 2}}]}})
        self.assertEqual(created.status_code, 201, created.content)
        result = self.call(f'/api/dashboards/{created.json()["id"]}/publish/')
        self.assertEqual(result.status_code, 400)
        self.assertIn('Choose an image', result.json()['error'])

    def test_preview_sort_coerces_measures_but_preserves_identifiers(self):
        dataset = self.create_dataset(b'Customer ID,Revenue\n001,100\n010,20\n2,3\n004,\n')
        ascending = self.client.get(f'/api/datasets/{dataset["id"]}/?sort=Revenue').json()['preview']
        self.assertEqual([row['Revenue'] for row in ascending], ['3', '20', '100', None])
        descending = self.client.get(f'/api/datasets/{dataset["id"]}/?sort=Revenue&direction=desc').json()['preview']
        self.assertEqual([row['Revenue'] for row in descending], ['100', '20', '3', None])
        identifiers = self.client.get(f'/api/datasets/{dataset["id"]}/?sort=Customer%20ID').json()['preview']
        self.assertEqual([row['Customer ID'] for row in identifiers], ['001', '004', '010', '2'])

    def test_hierarchy_options_preserve_real_paths_and_public_scope(self):
        dataset=self.create_dataset(b'From,To,Value,Private\nA,X,10,secret-a\nA,Y,20,secret-b\nB,X,30,secret-c\n')
        options=self.call(f'/api/datasets/{dataset["id"]}/filter-options/',{'fields':['From','To']})
        self.assertEqual(options.status_code,200,options.content)
        self.assertEqual(options.json()['paths'],[['A','X'],['A','Y'],['B','X']])
        stranger=Client(enforce_csrf_checks=True)
        stranger.get('/api/workspace/')
        denied=self.call(f'/api/datasets/{dataset["id"]}/filter-options/',{'fields':['Private']},client=stranger)
        self.assertEqual(denied.status_code,403)
        config={'widgets':[{'id':'path','type':'filter','control':'hierarchy','title':'Explore','dataset_id':dataset['id'],'filter':{'field':'From','op':'eq','value':None},'hierarchy_fields':['To'],'layout':{'x':0,'y':0,'w':6,'h':2}},{'id':'value','type':'kpi','title':'Actual total','dataset_id':dataset['id'],'y':'Value','aggregation':'sum','layout':{'x':6,'y':0,'w':6,'h':2}}]}
        created=self.call('/api/dashboards/',{'title':'Hierarchy','config':config}).json()
        published=self.call(f'/api/dashboards/{created["id"]}/publish/').json()
        public=self.call(f'/api/published/{published["slug"]}/filter-options/',{'widget_id':'path'},client=stranger)
        self.assertEqual(public.status_code,200,public.content)
        self.assertEqual(public.json()['paths'],options.json()['paths'])
        self.assertNotIn('secret-',public.content.decode())
        forged=self.call(f'/api/published/{published["slug"]}/filter-options/',{'widget_id':'path','fields':['Private']},client=stranger)
        self.assertEqual(forged.status_code,400)
