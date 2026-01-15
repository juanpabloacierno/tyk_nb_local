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

    # Dashboard views
    path('dashboard/<slug:slug>/', views.dashboard_detail, name='dashboard'),
    path('dashboard/<slug:slug>/chart/', views.render_dashboard_chart, name='dashboard_chart'),

    # Cell execution
    path('cell/<int:cell_id>/run/', views.run_cell, name='run_cell'),
    path('cell/<int:cell_id>/parameters/', views.get_cell_parameters, name='cell_parameters'),

    # API
    path('api/execute/', views.api_execute, name='api_execute'),
]
