from django.urls import path, re_path
from studio import views

urlpatterns = [
    path('api/health/', views.health),
    path('api/workspace/', views.workspace),
    path('api/imports/', views.import_source),
    path('api/datasets/', views.datasets),
    path('api/datasets/<uuid:dataset_id>/', views.dataset_item),
    path('api/datasets/<uuid:dataset_id>/source/', views.dataset_source),
    path('api/datasets/<uuid:dataset_id>/replace/', views.dataset_replace),
    path('api/datasets/<uuid:dataset_id>/refresh/', views.dataset_refresh),
    path('api/datasets/<uuid:dataset_id>/recommendations/', views.recommendations),
    path('api/datasets/<uuid:dataset_id>/filter-options/', views.dataset_filter_options),
    path('api/analytics/query/', views.analytics_query),
    path('api/analytics/export/', views.analytics_export),
    path('api/dashboards/', views.dashboards),
    path('api/dashboards/<uuid:dashboard_id>/', views.dashboard_item),
    path('api/dashboards/<uuid:dashboard_id>/publish/', views.dashboard_publish),
    path('api/dashboards/<uuid:dashboard_id>/unpublish/', views.dashboard_unpublish),
    path('api/dashboards/<uuid:dashboard_id>/duplicate/', views.dashboard_duplicate),
    path('api/published/', views.published),
    path('api/published/<slug:slug>/', views.published_item),
    path('api/published/<slug:slug>/query/', views.published_query),
    path('api/published/<slug:slug>/filter-options/', views.published_filter_options),
    re_path(r'^(?P<path>.*)$', views.app_shell),
]
handler404 = lambda request, exception: views.response({'error': 'Not found.'}, 404)
handler500 = lambda request: views.response({'error': 'An unexpected server error occurred.'}, 500)
