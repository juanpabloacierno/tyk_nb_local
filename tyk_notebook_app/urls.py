"""
URL configuration for TyK Notebook Application.
"""
from django.urls import path
from . import views

app_name = 'notebook'

urlpatterns = [
    # Notebook views
    path('', views.notebook_list, name='list'),
    path('notebook/<slug:slug>/', views.notebook_detail, name='detail'),
    path('notebook/<slug:slug>/setup/', views.run_setup, name='setup'),
    path('notebook/<slug:slug>/reset/', views.reset_session, name='reset'),
    path('notebook/<slug:slug>/history/', views.execution_history, name='history'),
    path('notebook/<slug:slug>/export/', views.notebook_export, name='export'),
    path('notebook/<slug:slug>/dataset-info/', views.notebook_dataset_info, name='dataset_info'),
    path('notebook/<slug:slug>/cluster-options/', views.notebook_cluster_options, name='cluster_options'),

    # Overview view
    path('overview/<slug:slug>/', views.overview_detail, name='overview'),
    path('notebook/<slug:slug>/dynamic-analysis/', views.notebook_dynamic_analysis, name='dynamic_analysis'),
    path('notebook/<slug:slug>/dialog-query/', views.notebook_dialog_query, name='dialog_query'),

    # Dashboard views
    path('dashboard/<slug:slug>/', views.dashboard_detail, name='dashboard'),
    path('dashboard/<slug:slug>/chart/', views.render_dashboard_chart, name='dashboard_chart'),

    # Cell execution
    path('cell/<int:cell_id>/run/', views.run_cell, name='run_cell'),
    path('cell/<int:cell_id>/parameters/', views.get_cell_parameters, name='cell_parameters'),

    # API
    path('api/execute/', views.api_execute, name='api_execute'),

    # Static data files (PDFs, etc.)
    path('pdf/<path:filepath>', views.serve_data_file, name='serve_data_file'),
]
